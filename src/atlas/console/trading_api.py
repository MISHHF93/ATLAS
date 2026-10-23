"""Trading (PAPER) endpoints for the console. Never imports atlas.ledgers.

Reads go through the TradingService views. Owner writes mirror `atlas-owner`:
approve => ApprovalQueue.mark_owner_approved (the CORE process re-checks risk and executes on its
next heartbeat; this process never executes), reset => KillSwitch.reset (step-up), kill => engage.
Policy is read-only here (no write route exists)."""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from atlas.ops.dashboard.server import build_state, markets
from atlas.mcp.trading.tokens import SCOPES, TokenRegistry
from atlas.risk.stepup import StepUp

from atlas.console.web import Request, Response, Router

SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
MAX_LIST = 500


def _int(q: dict, k: str, default: int, lo: int = 0, hi: int = MAX_LIST) -> int:
    v = q.get(k, "")
    return max(lo, min(hi, int(v))) if v.lstrip("-").isdigit() else default


def _match(obj: Any, needle: str) -> bool:
    return needle.lower() in json.dumps(obj, default=str).lower()


class TradingAPI:
    def __init__(self, svc, config_dir: str | Path, stepup_path: str | Path, tokens_path: str | Path,
                 reports_dir: str | Path, models_root: str | Path | None = None):
        self.svc, self.cfg = svc, svc.cfg
        self.config_dir = Path(config_dir)
        self.stepup = StepUp(stepup_path)
        self.tokens_path = Path(tokens_path)
        self.reports_dir = Path(reports_dir)
        self.models_root = Path(models_root or svc.models_root)
        self.owner = self.cfg.risk.owner
        self.lock = threading.RLock()

    # ---------------------------------------------------------------- step-up verifier (trading domain)
    def verify_stepup(self, session, passphrase: str, code: str) -> bool:
        return session.user == self.owner and self.stepup.verify(self.owner, passphrase, code)

    def stepup_enrolled(self) -> bool:
        return self.stepup.path.exists()

    def routes(self, r: Router) -> None:
        g = lambda p, f: r.add("GET", p, f)  # noqa: E731
        g("/api/t/state", self.state)
        g("/api/t/equity", self.equity)
        g("/api/t/markets", lambda q: markets(self.svc))
        g("/api/t/models", self.models)
        g("/api/t/decisions", self.decisions)
        g("/api/t/orders", self.orders)
        g("/api/t/approvals", self.approvals)
        g("/api/t/risk", self.risk)
        g("/api/t/strategies", self.strategies)
        g("/api/t/models/<kind>/<mid>/card", self.model_card)
        g("/api/t/trials", self.trials)
        g("/api/t/tax", self.tax)
        g("/api/t/tax/export/<kind>", self.tax_export)
        g("/api/t/fund", self.fund_nav)
        g("/api/t/reports", self.reports)
        g("/api/t/reports/file/<name>", self.report_file)
        g("/api/t/audit", self.audit)
        g("/api/t/settings", self.settings)
        g("/api/t/profile", self.profile)
        r.add("POST", "/api/t/kill", self.kill)
        r.add("POST", "/api/t/kill/reset", self.kill_reset, stepup="trading")
        r.add("POST", "/api/t/approvals/<aid>/approve", self.approve, stepup="trading")
        r.add("POST", "/api/t/approvals/<aid>/reject", self.reject)
        g("/api/t/autopilot", self.autopilot)
        g("/api/t/feeds", self.feeds)
        g("/api/t/ai-decisions", self.ai_decisions)
        g("/api/t/recipes", self.recipes)
        r.add("POST", "/api/t/autopilot/start", self.autopilot_start, stepup="trading")
        r.add("POST", "/api/t/autopilot/stop", self.autopilot_stop)          # stopping is instant: no step-up
        r.add("POST", "/api/t/autopilot/requests/<rid>/approve", self.autopilot_approve_request, stepup="trading")
        r.add("POST", "/api/t/autopilot/requests/<rid>/deny", self.autopilot_deny_request)
        r.add("POST", "/api/t/tokens", self.token_create, stepup="trading")
        r.add("POST", "/api/t/tokens/<client>/revoke", self.token_revoke, stepup="trading")

    # ---------------------------------------------------------------- overview / trading
    def _sync(self) -> None:
        """Viewer: reload the core's persisted paper state (positions, orders) before each read."""
        from atlas.mcp.trading.service import PAPER_STATE_KEY
        saved = self.svc.store.get(PAPER_STATE_KEY)
        if saved:
            self.svc.broker.load_state(saved["broker"])

    def core_heartbeat(self) -> dict:
        """The CORE process's heartbeat (shared state DB). The console never heartbeats on its behalf."""
        import time as _t
        from atlas.risk.watchdog_proc import CORE_HB, watchdog_alive
        hb = self.svc.store.get(CORE_HB)
        window = self.cfg.risk.watchdog.heartbeat_interval_s * self.cfg.risk.watchdog.missed_beats_to_halt
        age = (_t.time() - float(hb)) if hb is not None else None
        return {"age_s": age, "window_s": window, "healthy": age is not None and 0 <= age <= window,
                "watchdog_alive": watchdog_alive(self.svc.store, window)}

    def state(self, req: Request):
        with self.lock:
            self._sync()
            st = build_state(self.svc)
        hb = self.core_heartbeat()
        st["status"] |= {"owner": self.owner, "watchdog_healthy": hb["healthy"], "core_heartbeat": hb}
        return st

    def equity(self, req: Request):
        from atlas.ops.equity import equity_series
        return equity_series(self.svc)

    def models(self, req: Request):
        from atlas.models.quant.multi import models_overview
        return {"models": models_overview(self.models_root), "autonomy": self.svc.store.get("autonomy_readiness")}

    def _trail(self) -> list[dict]:
        from atlas.risk.trail import dedupe
        raw = dedupe(self.svc.store.get("decision_trail") or [])
        return [dict(t, id=i) for i, t in enumerate(raw)]

    def decisions(self, req: Request):
        from atlas.risk.trail import outcome_counts
        trail = self._trail()
        q = req.query
        items = list(reversed(trail))
        if q.get("final") in ("submitted", "dropped"):
            items = [t for t in items if str(t.get("final", "")).startswith(q["final"])]
        for k in ("sleeve", "side", "symbol"):
            if q.get(k):
                items = [t for t in items if str(t.get(k, "")).lower() == q[k].lower()]
        if q.get("stage"):
            items = [t for t in items if str(t.get("final", "")).endswith(q["stage"])]
        if q.get("q"):
            items = [t for t in items if _match({k: t.get(k) for k in ("symbol", "sleeve", "final", "side", "stages", "routing")}, q["q"])]
        off, lim = _int(q, "offset", 0, 0, 10**6), _int(q, "limit", 50, 1)
        facets = {"sleeves": sorted({str(t.get("sleeve")) for t in trail if t.get("sleeve")}),
                  "finals": sorted({str(t.get("final")) for t in trail if t.get("final")}),
                  "symbols": sorted({str(t.get("symbol")) for t in trail if t.get("symbol")})[:300]}
        return {"total": len(items), "offset": off, "decisions": items[off:off + lim], "outcomes": outcome_counts(trail),
                "facets": facets, "sim": self.svc.store.get("sim_summary")}

    def orders(self, req: Request):
        with self.lock:
            self._sync()
            oo = [{"order_id": oid, **o.intent.model_dump()} for oid, o in self.svc.broker.open_orders.items()]
        fills = [dict(e["payload"], seq=e["seq"], ts=e["ts"]) for e in self.svc.audit.entries("paper.fill")][-200:]
        return {"open_orders": oo, "fills": list(reversed(fills))}

    def approvals(self, req: Request):
        hist = [{"seq": e["seq"], "ts": e["ts"], "event": e["event"], "actor": e["actor"], "payload": e["payload"]}
                for e in self.svc.audit.entries() if e["event"].startswith("approval.")][-100:]
        return {"pending": self.svc.list_approvals(), "required": self.svc.approval_required, "history": list(reversed(hist))}

    def approve(self, req: Request):
        aid = req.params["aid"]
        p = self.svc.approvals.mark_owner_approved(aid, self.owner, True)   # step-up verified by the HTTP layer
        self.svc.audit.append("console.approval", {"approval_id": aid}, actor=self.owner)
        return {"approval_id": aid, "status": p.status if hasattr(p, "status") else "owner_approved",
                "note": "queued: the core process re-checks risk and executes on its next heartbeat"}

    def reject(self, req: Request):
        aid = req.params["aid"]
        self.svc.approvals.reject(aid, self.owner)
        return {"approval_id": aid, "status": "rejected"}

    # ---------------------------------------------------------------- risk
    def risk(self, req: Request):
        with self.lock:
            self._sync()
            st = self.svc.get_status()
            snap = self.svc.broker.snapshot()
            state = build_state(self.svc)
        st["watchdog_healthy"] = self.core_heartbeat()["healthy"]
        r = self.cfg.risk
        pl, ll = r.position_limits, r.loss_limits
        cap = st["bot_capital"] or 1.0
        largest = max((abs(p.market_value_base) for p in snap.positions.values()), default=0.0) / cap * 100
        rate = self.svc.store.get("rate:orders") or []
        now = datetime.now(timezone.utc).timestamp()
        per_min = len([t for t in rate if isinstance(t, (int, float)) and now - t < 60])
        gauges = [
            {"name": "Daily loss", "used": st["daily_loss_pct"], "limit": ll.daily_pct, "unit": "%"},
            {"name": "Weekly loss", "used": st.get("weekly_loss_pct") or 0, "limit": ll.weekly_pct, "unit": "%"},
            {"name": "Drawdown", "used": st.get("drawdown_pct") or 0, "limit": ll.max_drawdown_pct, "unit": "%"},
            {"name": "Gross exposure", "used": st["gross_exposure_pct"], "limit": pl.max_gross_exposure_pct, "unit": "%"},
            {"name": "Largest position", "used": largest, "limit": pl.max_position_pct_bot_capital, "unit": "%"},
            {"name": "Open orders", "used": st["open_orders"], "limit": pl.max_open_orders, "unit": ""},
            {"name": "Orders / min", "used": per_min, "limit": pl.max_orders_per_minute, "unit": ""},
        ]
        ents = self.svc.audit.entries()
        ks_hist = [{"ts": e["ts"], "event": e["event"], "actor": e["actor"], "payload": e["payload"]}
                   for e in ents if e["event"].startswith("kill_switch.")][-50:]
        anomalies = [{"ts": e["ts"], "event": e["event"], "actor": e["actor"], "payload": e["payload"]} for e in ents
                     if e["event"] in ("risk.daily_halt", "paper.persist_error", "tax.event_error")
                     or (e["event"] == "kill_switch.engage" and e["payload"].get("channel") in ("anomaly", "watchdog", "risk_engine"))][-50:]
        rejections: dict[str, int] = {}
        for e in ents[-2000:]:
            if e["event"] == "risk.decision" and not e["payload"].get("approved", True):
                for reason in e["payload"].get("reasons", [])[:1]:
                    k = str(reason).split(":")[0][:60]
                    rejections[k] = rejections.get(k, 0) + 1
        wd = r.watchdog
        return {"status": st, "gauges": gauges, "limit_rows": state["limit_rows"], "policy_version": r.version,
                "kill_switch": {"engaged": self.svc.ks.engaged, "reason": self.svc.ks.reason, "engaged_at": self.svc.ks.engaged_at,
                                "history": list(reversed(ks_hist))},
                "watchdog": {**self.core_heartbeat(), "interval_s": wd.heartbeat_interval_s,
                             "missed_beats_to_halt": wd.missed_beats_to_halt},
                "anomaly_policy": getattr(r, "anomaly_halts", None), "anomalies": list(reversed(anomalies)),
                "rejections": dict(sorted(rejections.items(), key=lambda kv: -kv[1])[:10])}

    def kill(self, req: Request):
        reason = str(req.body.get("reason", "")).strip()[:200] or "console"
        res = self.svc.ks.engage(reason, channel="console")
        return res

    # ---------------------------------------------------------------- autopilot (one button; the CORE runs the loop)
    def _ap_tools(self):
        if getattr(self, "_apt", None) is None:
            from atlas.mcp.trading.autopilot_tools import AutopilotTools
            self._apt = AutopilotTools(self.svc, str(self.config_dir), str(self.reports_dir.parent))
        return self._apt

    def autopilot(self, req: Request):
        from atlas.autopilot import control
        with self.lock:
            self._sync()
            st = control.status_view(self.svc.store)
            try:
                budget = self._ap_tools().get_risk_budget()
            except Exception as e:   # noqa: BLE001 - informational panel; never blocks the status card
                budget = {"error": str(e)[:200]}
        st["budget"] = budget
        st["kill_switch"] = self.svc.ks.engaged
        st["core_healthy"] = self.core_heartbeat()["healthy"]
        st["policy_note"] = (f"Autonomy level {self.cfg.risk.autonomy.level}: every order the autopilot proposes waits in "
                             "Approvals for the owner. Paper only; the autopilot never moves money.")
        return st

    def autopilot_start(self, req: Request):
        from atlas.autopilot import control
        if self.svc.ks.engaged:
            return Response.json({"error": "safe stop engaged: reset it first"}, 409)
        return control.request_start(self.svc.store, self.svc.audit, self.owner, True, "console")  # step-up verified upstream

    def autopilot_stop(self, req: Request):
        from atlas.autopilot import control
        reason = str((req.body or {}).get("reason", "")).strip()[:200] or "console stop"
        return control.request_stop(self.svc.store, self.svc.audit, req.session.user if req.session else "console", reason, "console")

    def autopilot_approve_request(self, req: Request):
        from atlas.autopilot import control
        if self.svc.ks.engaged:
            return Response.json({"error": "safe stop engaged: reset it first"}, 409)
        r = control.resolve_request(self.svc.store, req.params["rid"])
        if not r:
            return Response.json({"error": "request not found or expired"}, 404)
        self.svc.audit.append("autopilot.mcp_request_approved", {"id": r["id"], "client": r.get("client")}, actor=self.owner)
        return control.request_start(self.svc.store, self.svc.audit, self.owner, True, "console:mcp-request")

    def autopilot_deny_request(self, req: Request):
        from atlas.autopilot import control
        r = control.resolve_request(self.svc.store, req.params["rid"])
        if r:
            self.svc.audit.append("autopilot.mcp_request_denied", {"id": r["id"]}, actor=req.session.user if req.session else "console")
        return {"denied": bool(r)}

    AI_STAGES = {"scorer": "Per-sleeve LightGBM scorer", "factor_sleeve": "Factor sleeve model", "meta_label": "Meta-labeler",
                 "news": "News screener (FinBERT / LLM veto)", "sizing": "Sizing (vol / regime HMM / conformal)",
                 "portfolio": "Portfolio (HRP / HERC)", "cost": "Cost model", "tsfm": "Time-series foundation model"}

    def ai_decisions(self, req: Request):
        """Why each trade was taken, shrunk or vetoed, and which model contributed (AI stages only shrink or drop)."""
        trail = self._trail()
        per: dict[str, dict[str, int]] = {k: {"pass": 0, "shrink": 0, "drop": 0} for k in self.AI_STAGES}
        rows = []
        for t in reversed(trail[-300:]):
            contrib, verdict = [], "taken"
            for st in t.get("stages", []):
                name = st.get("stage")
                if name not in self.AI_STAGES:
                    continue
                eff = str(st.get("effect", ""))
                kind = "drop" if eff == "drop" else "shrink" if (eff.startswith("x") and eff != "x1.0") or (st.get("mult") or 1) < 1 else "pass"
                per[name][kind] += int(t.get("repeat", 1) or 1)
                if kind != "pass":
                    contrib.append({"stage": name, "model": self.AI_STAGES[name], "effect": kind, "detail": str(st.get("detail", ""))[:240]})
                    verdict = "vetoed" if kind == "drop" else ("shrunk" if verdict == "taken" else verdict)
            if str(t.get("final", "")).startswith("rejected"):
                verdict = "rejected by risk engine"
            rows.append({"id": t.get("id"), "ts": t.get("ts"), "symbol": t.get("symbol"), "side": t.get("side"), "final": t.get("final"),
                         "verdict": verdict, "contributors": contrib, "shadow": t.get("shadow") or {}, "repeat": t.get("repeat", 1)})
        from atlas.models.quant import textai, tsfm
        if getattr(self, "_ai_providers", None) is None:
            self._ai_providers = (tsfm.TSFMComponent("chronos-bolt"), textai.TextVeto())
        ts, tv = self._ai_providers
        return {"by_model": [{"stage": k, "model": v, **per[k]} for k, v in self.AI_STAGES.items()], "decisions": rows[:100],
                "providers": {"tsfm": {"active": ts.name, "status": ts.status}, "text": {"active": tv.provider.name}},
                "authority": "AI stages are advisory: they can shrink or drop a trade, never create, enlarge or approve one. "
                             "The deterministic risk engine has the final say."}

    def recipes(self, req: Request):
        p = self.reports_dir.parent / "recipes" / "results.json"
        if not p.exists():
            return {"available": False, "hint": "run: atlas-ml recipe-search --out <var>/recipes"}
        res = json.loads(p.read_text())
        from atlas.models.quant.registry import ModelRegistry
        root = self.models_root / "recipe"
        reg = ModelRegistry(root, kind="recipe") if (root / "index.json").exists() else None
        return {"available": True, **{k: res.get(k) for k in ("generated", "synthetic", "grid_size", "evaluated", "trial_log_total", "pbo",
                                                                "oos_start", "oos_end", "folds", "tsfm_provider", "feed_value", "baseline")},
                "table": res.get("table", [])[:25], "challenger": reg.challenger if reg else None,
                "champion": reg.champion if reg else None}

    def feeds(self, req: Request):
        from atlas.mcp.trading.external import catalogue
        t = self._ap_tools()
        h = t.feed_health()
        return {"feeds": [f | {k: d.get(k) for k in ("source", "enabled", "network", "env", "mcp", "note")}
                          for f, d in zip(h["feeds"], t.list_data_feeds())],
                "stale_bars": h["stale_bars"], "ok": h["ok"], "external_mcp": catalogue()}

    def kill_reset(self, req: Request):
        self.svc.ks.reset(self.owner, True, self.owner)
        return {"halted": self.svc.ks.engaged}

    # ---------------------------------------------------------------- strategies & models
    def _kinds(self) -> list[Path]:
        if not self.models_root.exists():
            return []
        return sorted(p for p in self.models_root.iterdir() if (p / "index.json").exists())

    def strategies(self, req: Request):
        from atlas.models.quant.registry import ModelRegistry
        promo = self.cfg.risk.ai_controls.model_promotion
        kinds = []
        for d in self._kinds():
            reg = ModelRegistry(d, kind=d.name)
            models = []
            for mid, m in reg.idx["models"].items():
                val = (m.get("metrics") or {}).get("validation") or {}
                gates = None
                if m.get("stage") in ("challenger", "champion"):
                    try:
                        gates = [{"name": g.name, "passed": bool(g.passed), "value": g.value, "threshold": g.threshold}
                                 for g in reg.gates(mid, promo)]
                    except Exception as e:  # noqa: BLE001
                        gates = [{"name": "error", "passed": False, "value": type(e).__name__, "threshold": ""}]
                models.append({"id": mid, "stage": m.get("stage"), "created": m.get("created"),
                               "dsr": val.get("dsr"), "pbo": val.get("pbo"), "n_trials": val.get("n_trials"),
                               "psr": val.get("psr"), "shadow": m.get("shadow") or {},
                               "card": (d / mid / "model_card.md").exists(), "gates": gates,
                               "metrics": {k: v for k, v in (m.get("metrics") or {}).items() if isinstance(v, (int, float, str))}})
            models.sort(key=lambda x: str(x["created"]), reverse=True)
            drift = [h for h in reg.idx["history"] if h["event"] in ("drift_check", "demote")][-20:]
            kinds.append({"kind": d.name, "champion": reg.champion, "challenger": reg.challenger, "n_models": len(models),
                          "models": models[:20], "drift": list(reversed(drift)),
                          "history": list(reversed(reg.idx["history"][-15:]))})
        return {"kinds": kinds, "gates_policy": promo.model_dump() if hasattr(promo, "model_dump") else str(promo),
                "autonomy": self.svc.store.get("autonomy_readiness")}

    def model_card(self, req: Request):
        kind, mid = req.params["kind"], req.params["mid"]
        d = self.models_root / kind
        if not (SAFE.match(kind) and SAFE.match(mid)) or not (d / "index.json").exists():
            raise KeyError(kind)
        if mid not in json.loads((d / "index.json").read_text())["models"]:
            raise KeyError(mid)
        f = d / mid / "model_card.md"
        return {"kind": kind, "model_id": mid, "markdown": f.read_text() if f.exists() else None}

    def trials(self, req: Request):
        from atlas.models.quant.validation import TrialLog
        out = []
        files = sorted(self.models_root.glob("*/trials.jsonl")) + sorted(self.models_root.glob("_nonalpha/*/trials.jsonl"))
        want = req.query.get("kind")
        for f in files:
            kind = f.parent.name
            if want and kind != want:
                continue
            recs = TrialLog(f).records()
            srs = [r["sr"] for r in recs]
            out.append({"kind": kind, "pool": "non-alpha" if f.parent.parent.name == "_nonalpha" else "alpha", "n": len(recs),
                        "best_sr": max(srs) if srs else None, "mean_sr": sum(srs) / len(srs) if srs else None,
                        "recent": list(reversed(recs[-30:]))})
        total_alpha = sum(k["n"] for k in out if k["pool"] == "alpha")
        return {"kinds": out, "total_alpha_trials": total_alpha,
                "note": "Deflated Sharpe deflates by the expected max SR over ALL alpha trials; non-alpha (cost/carry/tax) trials are a separate pool."}

    # ---------------------------------------------------------------- tax / fund
    def tax(self, req: Request):
        rep = self.svc.tax.report()
        tc = self.cfg.tax
        pools = [{"taxpayer": tp, "property": prop, "qty": str(qty), "acb": str(round(acb, 2)),
                  "acb_per_unit": str(round(acb / qty, 4)) if qty else "0"} for (tp, prop), (qty, acb) in sorted(rep.pools.items())]
        disp = [{"id": d.id, "date": d.date.isoformat(), "taxpayer": d.taxpayer, "entity": d.entity, "property": d.property,
                 "qty": str(d.qty), "proceeds": str(round(d.proceeds, 2)), "acb": str(round(d.acb, 2)), "gain": str(round(d.gain, 2)),
                 "denied_loss": str(round(d.denied_loss, 2)), "allowable": str(round(d.allowable, 2)), "treatment": d.treatment,
                 "fx_source": d.fx_source} for d in rep.dispositions]
        t1135 = [{"taxpayer": k[0], "year": k[1], **{kk: str(vv) for kk, vv in v.items()}} for k, v in sorted(rep.t1135.items())]
        years = sorted({d.date.year for d in rep.dispositions} | {k[1] for k in rep.t1135})
        ents = [{"id": tc.entity.id, "kind": tc.entity.kind, "taxpayer": tc.entity.taxpayer}] if tc else []
        ents += [{"id": e.id, "kind": e.kind, "taxpayer": e.taxpayer} for e in (tc.other_entities if tc else [])]
        sl = [w for w in rep.warnings if "superficial" in w.lower()]
        return {"pools": pools, "dispositions": disp, "warnings": rep.warnings[-100:], "superficial": sl[-100:],
                "t1135": t1135, "t1135_threshold_cad": "100000", "years": years, "entities": ents,
                "superficial_guard": tc.superficial_loss_guard if tc else "warn", "input_hash": rep.input_hash,
                "disclaimer": "NOT TAX ADVICE. Record keeping for review by a CPA."}

    def tax_export(self, req: Request):
        kind = req.params["kind"]
        rep = self.svc.tax.report()
        tp = req.query.get("taxpayer") or (self.cfg.tax.entity.taxpayer if self.cfg.tax else "")
        yr = int(req.query["year"]) if req.query.get("year", "").isdigit() else date.today().year
        if kind == "t5008.csv":
            return Response.download(rep.t5008_csv(tp or None, yr), "text/csv", f"t5008_{tp}_{yr}.csv")
        if kind == "schedule3.csv":
            return Response.download(rep.schedule3_csv(tp, yr), "text/csv", f"schedule3_{tp}_{yr}.csv")
        if kind == "evidence.csv":
            return Response.download(rep.evidence_csv(), "text/csv", "business_vs_capital_evidence.csv")
        if kind == "trades.csv":                                       # BRD US-12: trade history per broker and tax year
            return Response.download(self.trades_csv(req.query.get("broker") or "", req.query.get("year") or ""), "text/csv",
                                     f"trades_{req.query.get('broker') or 'all'}_{req.query.get('year') or 'all'}.csv")
        raise KeyError(kind)

    TRADE_COLS = ("ts", "broker", "symbol", "side", "qty", "price", "currency", "fx_rate", "commission", "cash_delta_cad",
                  "asset_class", "sleeve", "order_id", "intent_id", "audit_seq")

    def trades_csv(self, broker: str = "", year: str = "") -> str:
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(self.TRADE_COLS)
        for e in self.svc.audit.entries("paper.fill"):
            f = e["payload"]
            ts = f.get("ts") or e["ts"]
            if (broker and f.get("broker") != broker) or (year and not str(ts).startswith(year)):
                continue
            row = [ts, f.get("broker"), f.get("symbol"), f.get("side"), f.get("qty"), f.get("price"), f.get("currency"),
                   f.get("fx_rate"), f.get("commission"), round(float(f.get("cash_delta") or 0), 2), f.get("asset_class"),
                   f.get("sleeve"), f.get("order_id"), f.get("intent_id"), e["seq"]]
            w.writerow(["'" + v if isinstance(v, str) and v[:1] in "=+-@\t" else v for v in row])   # CSV-injection safe
        return buf.getvalue()

    def fund_nav(self, req: Request):
        """Trading-side NAV inputs (paper): bot equity/positions. Investor registry lives in payments."""
        st = self.svc.get_status()
        from atlas.ops.equity import equity_series
        return {"bot_equity": st["bot_equity"], "cash": st["cash"], "positions": len(self.svc.broker.positions),
                "equity": equity_series(self.svc)[-120:]}

    # ---------------------------------------------------------------- reports
    def _report_path(self, name: str) -> Path:
        if not SAFE.match(name) or name.startswith("."):
            raise KeyError(name)
        p = (self.reports_dir / name).resolve()
        if p.parent != self.reports_dir.resolve() or not p.is_file():
            raise KeyError(name)
        return p

    def reports(self, req: Request):
        from atlas.ops.summary import daily_summary
        files = []
        if self.reports_dir.exists():
            for p in sorted(self.reports_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if p.is_file() and p.suffix in (".md", ".json", ".csv", ".txt") and SAFE.match(p.name):
                    kind = "daily" if p.name.startswith("daily") else ("backtest" if "backtest" in p.name or "sim_summary" in p.name else "other")
                    files.append({"name": p.name, "size": p.stat().st_size, "kind": kind,
                                  "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
        with self.lock:
            today = daily_summary(self.svc, date.today())
        backtests = []
        for f in files:
            if f["kind"] == "backtest" and f["name"].endswith(".json"):
                try:
                    d = json.loads(self._report_path(f["name"]).read_text())
                    backtests.append({"name": f["name"], "period": d.get("period"), "metrics": d.get("metrics"),
                                      "fills": d.get("fills"), "decisions": d.get("decisions"), "outcomes": d.get("outcomes"),
                                      "final_bot_equity": d.get("final_bot_equity")})
                except Exception:  # noqa: BLE001
                    pass
        return {"files": files[:200], "today": today, "backtests": backtests, "sim": self.svc.store.get("sim_summary")}

    def report_file(self, req: Request):
        p = self._report_path(req.params["name"])
        if req.query.get("download") == "1":
            return Response.download(p.read_bytes(), "application/octet-stream", p.name)
        txt = p.read_text(errors="replace")
        return {"name": p.name, "content": txt[:200_000], "truncated": len(txt) > 200_000}

    # ---------------------------------------------------------------- audit
    def audit(self, req: Request):
        from atlas.governance.audit.log import AuditTamperError
        q = req.query
        rows = self.svc.audit.entries()
        try:
            chain = {"ok": True, "verified_entries": self.svc.audit.verify()}
        except AuditTamperError as e:
            chain = {"ok": False, "error": str(e)}
        events = sorted({r["event"].split(".")[0] for r in rows})
        if q.get("event"):
            rows = [r for r in rows if r["event"].startswith(q["event"])]
        if q.get("actor"):
            rows = [r for r in rows if r["actor"] == q["actor"]]
        if q.get("q"):
            rows = [r for r in rows if _match([r["event"], r["actor"], r["payload"]], q["q"])]
        rows = list(reversed(rows))
        off, lim = _int(q, "offset", 0, 0, 10**7), _int(q, "limit", 100, 1)
        out = []
        for r in rows[off:off + lim]:
            p = json.dumps(r["payload"], default=str)
            out.append({"seq": r["seq"], "ts": r["ts"], "event": r["event"], "actor": r["actor"],
                        "payload": p if len(p) <= 600 else p[:597] + "...", "hash": r["hash"][:16], "prev": r["prev_hash"][:16]})
        return {"total": len(rows), "entries": out, "chain": chain, "event_groups": events,
                "actors": sorted({r["actor"] for r in rows})[:50]}

    # ---------------------------------------------------------------- settings / profile
    def settings(self, req: Request):
        from atlas.control.policy.signing import verify_policy
        cd = self.config_dir
        issues = verify_policy(cd)
        if (cd / "risk_policy.yaml.sig").exists():
            mode = "ed25519 signature"
        elif (cd / "risk_policy.yaml.sha256").exists():
            mode = "sha256 pin"
        else:
            mode = "unsigned"
        def y(name):
            p = cd / name
            return yaml.safe_load(p.read_text()) if p.exists() else None
        brokers = y("brokers.yaml") or {}
        for p in (brokers.get("platforms") or {}).values():
            if isinstance(p, dict) and isinstance(p.get("credentials"), dict):
                p["credentials"] = {k: f"env:{v}" for k, v in p["credentials"].items()}  # names only, never values
        tax = y("tax.yaml") or {}
        return {"policy": {"text": (cd / "risk_policy.yaml").read_text(), "version": self.cfg.risk.version,
                           "read_only": True, "signature": {"mode": mode, "ok": not issues, "issues": issues},
                           "digests": getattr(self.cfg, "digests", {})},
                "venues": y("venues.yaml"), "brokers": brokers, "schedule": y("schedule.yaml"),
                "data_sources": [
                    {"name": "Market data", "source": "synthetic / local files (offline by default)", "network": False},
                    {"name": "FX for tax", "source": (tax.get("fx") or {}).get("source", "fill"), "network": False},
                    {"name": "Bank of Canada Valet fetch", "source": "BoC Valet API",
                     "network": bool((tax.get("boc_fetch") or {}).get("enabled"))},
                    {"name": "SEDI / CIRO screens", "source": "local CSV exports only", "network": False},
                    {"name": "Earnings (PEAD)", "source": "fixture provider; paid feed placeholder (disabled)", "network": False},
                    {"name": "Brokers", "source": "paper adapters only; live disabled in this build", "network": False}]}

    def profile(self, req: Request):
        tc = self.cfg.tax
        ents = ([{"id": tc.entity.id, "kind": tc.entity.kind}] + [{"id": e.id, "kind": e.kind} for e in tc.other_entities]) if tc else []
        return {"owner": self.owner, "entities": ents, "base_currency": getattr(self.cfg.risk, "base_currency", "CAD"),
                "timezone": "America/Toronto", "trading_stepup_enrolled": self.stepup_enrolled(),
                "tokens": self.tokens_list(), "token_scopes": sorted(SCOPES)}

    def tokens_list(self) -> list[dict]:
        if not self.tokens_path.exists():
            return []
        d = json.loads(self.tokens_path.read_text())
        now = datetime.now(timezone.utc).timestamp()
        return [{"client": c, "scopes": e["scopes"], "expires": datetime.fromtimestamp(e["expires"], timezone.utc).isoformat(),
                 "expired": now > e["expires"], "sha256_prefix": e["sha256"][:8]} for c, e in sorted(d.get("tokens", {}).items())]

    def token_create(self, req: Request):
        client = str(req.body.get("client", "")).strip()
        if not SAFE.match(client):
            raise ValueError("client: 1-80 chars [A-Za-z0-9_.:-]")
        scopes = set(req.body.get("scopes") or ["read"])
        ttl = float(req.body.get("ttl_days", 30))
        if not 0 < ttl <= 365:
            raise ValueError("ttl_days must be in (0, 365]")
        tok = TokenRegistry(self.tokens_path).create(client, scopes, ttl)
        self.svc.audit.append("mcp.token_created", {"client": client, "scopes": sorted(scopes), "ttl_days": ttl, "via": "console"}, actor=self.owner)
        return {"client": client, "token": tok, "note": "shown once; only its SHA-256 is stored"}

    def token_revoke(self, req: Request):
        client = req.params["client"]
        if client not in {t["client"] for t in self.tokens_list()}:
            raise KeyError(client)
        TokenRegistry(self.tokens_path).revoke(client)
        self.svc.audit.append("mcp.token_revoked", {"client": client, "via": "console"}, actor=self.owner)
        return {"client": client, "revoked": True}
