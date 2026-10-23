"""Autopilot state machine, driven by the core loop (ops/runner.py).

States: off -> running <-> paused (guards) / waiting (no venue open) -> off.
* safety_check(now): every safety tick (seconds). Honours stop instantly, starts on an owner-approved request,
  turns OFF on a kill switch (a new owner start is needed), pauses/resumes on guards.
* tick(now): on the worker thread under the book lock. For every venue that is open for new orders and whose cadence
  is due, runs one decision cycle (feeds -> pipeline -> risk-budget overlay -> risk engine -> approval queue at L1 /
  paper broker at L>=3) and records the decisions with reasons.
State lives in the shared state DB, so a restart resumes where it left off (and says so in the audit log)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from atlas.risk.safety import assert_paper_only
from atlas.autopilot import control
from atlas.autopilot.config import AutopilotCfg, UniverseItem
from atlas.autopilot.feeds import FeedRegistry
from atlas.autopilot.sizing import overlay_factor, risk_budget

ACTIVE = ("running", "paused", "waiting")


class Autopilot:
    def __init__(self, svc, cfg: AutopilotCfg, feeds: FeedRegistry, sessions=None, clock: Callable[[], float] = time.time,
                 cycle_fn: Callable | None = None):
        assert_paper_only()
        self.svc, self.cfg, self.feeds, self.clock = svc, cfg, feeds, clock
        if sessions is None:
            from atlas.ops.sessions import SessionModel
            sessions = SessionModel(svc.cfg.schedule.model_dump())
        self.sessions = sessions
        self.cycle_fn = cycle_fn or self._pipeline_cycle
        self._pipeline = None
        st = self.state()
        if control.desired(svc.store) == "on" and st.get("state") in ACTIVE:
            st["restarts"] = int(st.get("restarts", 0)) + 1
            st["resumed_at"] = self.clock()
            self._event(st, "resumed after restart", {"previous_state": st.get("state")})
            svc.audit.append("autopilot.resumed", {"state": st.get("state"), "restarts": st["restarts"]}, actor="autopilot")
            self.save(st)

    # ---------------------------------------------------------------- state
    def state(self) -> dict[str, Any]:
        return dict(self.svc.store.get(control.STATE) or {"state": "off", "cycles": 0, "decisions": [], "events": []})

    def save(self, st: dict) -> None:
        st["updated_at"] = self.clock()
        self.svc.store.set(control.STATE, st)

    def _event(self, st: dict, text: str, data: dict | None = None) -> None:
        st.setdefault("events", []).append({"at": self.clock(), "text": text, **(data or {})})
        st["events"] = st["events"][-30:]

    # ---------------------------------------------------------------- guards
    def guards(self) -> list[str]:
        svc, on = self.svc, set(self.cfg.pause_on)
        out = []
        if "watchdog" in on and not svc.watchdog.healthy():
            out.append("core watchdog unhealthy")
        if "daily_halt" in on and svc.engine.daily_halted:
            out.append("daily loss limit reached (halted until the next session)")
        if "loss_limits" in on:
            s = svc.broker.snapshot()
            lm, ll = svc.engine.loss_metrics(s), svc.cfg.risk.loss_limits
            if lm["weekly_loss_pct"] >= ll.weekly_pct:
                out.append(f"weekly loss {lm['weekly_loss_pct']:.2f}% >= limit {ll.weekly_pct}%")
            if lm["drawdown_pct"] >= svc.cfg.risk.loss_limits.max_drawdown_pct:
                out.append(f"drawdown {lm['drawdown_pct']:.2f}% >= limit {ll.max_drawdown_pct}%")
        if "feeds_stale" in on:
            stale = self.feeds.stale_bars()
            if stale:
                out.append("data feed stale or failing: " + ", ".join(stale))
        if "broker_disconnected" in on:
            for name, ad in (getattr(svc.router, "adapters", {}) or {}).items():
                if getattr(ad, "connected", True) is False:
                    out.append(f"broker adapter {name} disconnected")
        da = svc.store.get("autopilot.drift_alert") if "drift" in on else None
        if da and self.clock() - float(da.get("at", 0)) < 86400:   # champion was demoted; pause for 24 h, then resume
            out.append("model drift: " + ", ".join(da.get("kinds", []))[:120] + " (champion demoted; pause 24 h)")
        if "anomaly" in on and getattr(svc.anomaly, "tripped", False):
            out.append("anomaly monitor tripped")
        return out

    # ---------------------------------------------------------------- safety tick (fast, every heartbeat)
    def safety_check(self, now: datetime) -> dict[str, Any]:
        st, store = self.state(), self.svc.store
        want = control.desired(store)
        cur = st.get("state", "off")
        if want == "off" and cur != "off":
            c = store.get(control.CONTROL) or {}
            st.update(state="off", stopped_at=self.clock(), stop_reason=c.get("reason") or "stopped", pause_reasons=[])
            self._event(st, "stopped", {"by": c.get("by"), "reason": c.get("reason")})
            self.svc.audit.append("autopilot.stopped", {"reason": c.get("reason"), "by": c.get("by")}, actor="autopilot")
        elif want == "on" and cur == "off":
            c = store.get(control.CONTROL) or {}
            if self.svc.ks.engaged:
                control.request_stop(store, self.svc.audit, "autopilot", f"cannot start: kill switch engaged ({self.svc.ks.reason})", "core")
                st.update(stop_reason=f"cannot start: kill switch engaged ({self.svc.ks.reason})")
            else:
                s = self.svc.broker.snapshot()
                store.set("autopilot.capital_at_start", self.svc.engine.bot_capital(s))
                st.update(state="running", started_at=self.clock(), started_by=c.get("by"), equity_at_start=s.bot_equity,
                          stop_reason=None, pause_reasons=[], last_cycle={}, cycles=st.get("cycles", 0))
                self._event(st, "started", {"by": c.get("by"), "channel": c.get("channel")})
                self.svc.audit.append("autopilot.started", {"by": c.get("by"), "channel": c.get("channel")}, actor="autopilot")
        st = self._apply_guards(st)
        self.save(st)
        return st

    def _apply_guards(self, st: dict) -> dict:
        if st.get("state") not in ACTIVE:
            return st
        if self.svc.ks.engaged:   # a halt turns the autopilot OFF: the owner must reset the switch AND start again
            reason = f"kill switch engaged: {self.svc.ks.reason}"
            control.request_stop(self.svc.store, self.svc.audit, "autopilot", reason, "core")
            st.update(state="off", stopped_at=self.clock(), stop_reason=reason, pause_reasons=[])
            self._event(st, "stopped by kill switch", {"reason": self.svc.ks.reason})
            return st
        g = self.guards()
        if g and st["state"] != "paused":
            self._event(st, "paused", {"reasons": g})
            self.svc.audit.append("autopilot.paused", {"reasons": g}, actor="autopilot")
        elif not g and st["state"] == "paused":
            self._event(st, "resumed (guards cleared)")
            self.svc.audit.append("autopilot.resumed", {"reason": "guards cleared"}, actor="autopilot")
            st["state"] = "running"
        if g:
            st["state"] = "paused"
        st["pause_reasons"] = g
        return st

    # ---------------------------------------------------------------- work tick (slow, worker thread)
    def tick(self, now: datetime) -> dict[str, Any]:
        st = self.safety_check(now)
        if st.get("state") not in ("running", "waiting"):
            self._refresh(st, now)
            self.save(st)
            return st
        venues = sorted({u.venue for u in self.cfg.universe})
        status = {v: self._venue(v, now) for v in venues}
        open_v = [v for v, s in status.items() if s["new_orders_allowed"]]
        st["sessions"] = status
        if not open_v:
            st["state"] = "waiting"
        else:
            st["state"] = "running"
            last = st.setdefault("last_cycle", {})
            due = [v for v in open_v if self.clock() - float(last.get(v, 0)) >= self.cfg.cadence_s(v)]
            if due:
                items = [u for u in self.cfg.universe if u.venue in due]
                res = self._run(now, items, st)
                for v in due:
                    last[v] = self.clock()
                st["last_result"] = res
        self._refresh(st, now)
        self.save(st)
        return st

    def _venue(self, v: str, now: datetime) -> dict:
        try:
            s = self.sessions.status(v, now)
            return {"open": s["open"], "phase": s["phase"], "new_orders_allowed": s["new_orders_allowed"], "local_time": s["local_time"]}
        except Exception:  # noqa: BLE001  unknown venue => closed (fail closed)
            return {"open": False, "phase": "closed", "new_orders_allowed": False, "local_time": "-"}

    def _run(self, now: datetime, items: list[UniverseItem], st: dict) -> dict:
        from atlas.ops.equity import KEY as EQ_KEY
        budget = risk_budget(self.svc, self.cfg, self.svc.store.get(EQ_KEY) or [])
        st["budget"] = budget
        frames = self.feeds.frames(now, items)
        if not frames:
            self._event(st, "cycle skipped: no data from the bar feed")
            return {"skipped": "no data"}
        def overlay(intent):
            f = overlay_factor(intent, budget)
            if intent.side == "buy":   # consume headroom so several buys in one cycle share the budget
                budget["headroom"] = max(0.0, budget["headroom"] - f * intent.qty * intent.reference_price * (intent.fx_rate_to_base or 1.0))
            return f
        try:
            res = self.cycle_fn(now, frames, items, overlay, lambda: control.desired(self.svc.store) == "on")
        except Exception as e:  # noqa: BLE001  a failed cycle is logged; the loop and its guards keep running
            self.svc.audit.append("autopilot.cycle_error", {"error": repr(e)[:300]}, actor="autopilot")
            self._event(st, "cycle error", {"error": repr(e)[:160]})
            return {"error": repr(e)[:200]}
        st["cycles"] = int(st.get("cycles", 0)) + 1
        st["last_cycle_at"] = self.clock()
        self._record(st, now, res)
        self.svc.audit.append("autopilot.cycle", {"venues": sorted({u.venue for u in items}), "decisions": res.get("decisions"),
                                                  "queued": len(res.get("queued_for_approval", [])), "routed": len(res.get("routed", [])),
                                                  "shrunk": len(res.get("shrunk", []))}, actor="autopilot")
        return {k: (len(v) if isinstance(v, list) else v) for k, v in res.items() if k != "trail"}

    def _pipeline_cycle(self, now, frames, items, overlay, should_continue) -> dict:
        from atlas.research.backtest.engine import Instrument
        from atlas.ops.pipeline_full import FullPipeline
        from atlas.ops.pipeline_models import ModelSet
        from atlas.ops.pipeline_service import paper_pipeline_step
        from atlas.research.screener.news import NewsScreener
        if self._pipeline is None:
            svc = self.svc
            self._pipeline = FullPipeline(svc.cfg, ModelSet(svc.models_root, audit=svc.audit),
                                          NewsScreener(svc.cfg.risk.ai_controls.llm_screener, audit=svc.audit), audit=svc.audit)
            self._pipeline.trail_max = 500
        inst = {u.symbol: Instrument(u.symbol, u.currency, u.sleeve, u.asset_class, u.broker, u.sector) for u in items}
        for sym, df in frames.items():   # live marks for held positions (paper book)
            if sym in self.svc.broker.positions:
                self.svc.broker.mark(sym, float(df["close"].iloc[-1]))
        self.feeds.mark("quotes.paper_book", len(self.svc.broker.positions))
        return paper_pipeline_step(self.svc, frames, inst, now, pipeline=self._pipeline, size_overlay=overlay, should_continue=should_continue)

    def _record(self, st: dict, now: datetime, res: dict) -> None:
        routing = "owner approval queue (autonomy L1)" if self.svc.approval_required else "paper broker"
        shr = {(x["symbol"], x["side"]): x for x in res.get("shrunk", [])}
        rows = []
        for t in res.get("trail", []):
            stages = t.get("stages") or []
            why = next((f"{s.get('stage')}: {s.get('detail') or s.get('effect')}" for s in stages if "drop" in str(s.get("effect", ""))), None)
            x = shr.get((t["symbol"], t["side"]))
            rows.append({"at": now.isoformat(timespec="seconds"), "id": t.get("id"), "symbol": t["symbol"], "side": t["side"], "sleeve": t.get("sleeve"),
                         "outcome": t["final"] if t["final"] != "submitted" else f"submitted → {routing}",
                         "reason": why or (f"shrunk ×{x['factor']} by the risk budget" if x else "passed every stage"),
                         "models": [s.get("stage") for s in stages if s.get("stage")]})
        st["decisions"] = (st.get("decisions", []) + rows)[-self.cfg.max_decisions_kept:]

    def _refresh(self, st: dict, now: datetime) -> None:
        svc = self.svc
        s = svc.broker.snapshot()
        st["pnl_today"] = s.bot_equity - s.start_of_day_equity
        if st.get("equity_at_start") is not None:
            st["pnl_since_start"] = s.bot_equity - float(st["equity_at_start"])
        st["capital_deployed"] = float(s.gross_exposure_base)
        st["bot_capital"] = svc.engine.bot_capital(s)
        st["pending_approvals"] = len(svc.approvals.pending())
        st["autonomy_level"] = svc.cfg.risk.autonomy.level
        st["routing"] = "owner approval queue" if svc.approval_required else "paper broker"
        st["next_actions"] = self.next_actions(st, now)

    def next_actions(self, st: dict, now: datetime) -> list[str]:
        out = []
        if st.get("state") == "off":
            return ["Press Start (owner step-up) to begin. Stop is always instant."]
        if st.get("state") == "paused":
            out.append("Paused until: " + "; ".join(st.get("pause_reasons") or []) + " (resumes automatically)")
        last = st.get("last_cycle", {})
        for v, s in (st.get("sessions") or {}).items():
            if s.get("new_orders_allowed"):
                due = float(last.get(v, 0)) + self.cfg.cadence_s(v) - self.clock()
                out.append(f"{v}: next cycle in {max(0, int(due // 60))} min")
            else:
                try:
                    nxt = self.sessions.next_change(v, now)
                except Exception:  # noqa: BLE001
                    nxt = None
                out.append(f"{v}: closed{f', opens {nxt[11:16]} ET' if nxt else ''}")
        if st.get("pending_approvals"):
            out.append(f"{st['pending_approvals']} order(s) waiting for your approval (autonomy L{st.get('autonomy_level')}; they expire after the policy TTL)")
        out.append("Weekly: models retrain as challengers (weekend); drift check Sunday; daily summary 17:30 ET")
        return out


def build_autopilot(svc, config_dir: str = "config/founder", var_dir: str = "var") -> Autopilot:
    from atlas.autopilot.config import load_autopilot_cfg
    cfg = load_autopilot_cfg(config_dir)
    return Autopilot(svc, cfg, FeedRegistry(cfg, svc.store, var_dir))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
