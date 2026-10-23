"""Read-only tool registry for the assistant (subset of our MCP tools + a few console views).

ALLOWLIST is the only way a tool can run. There is deliberately no write tool here: action intents map to deep links
into the console, where the owner completes the step-up flow."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from atlas.ai.assistant.guard import redact_obj


@dataclass
class Tool:
    name: str
    description: str
    params: dict              # JSON schema "properties"
    fn: Callable[..., Any]
    scope: str = "trading"    # trading | money | compliance | any


ACTION_LINKS = [   # (regex, label, href, why)
    (r"\b(start|turn on|switch on|enable|resume)\b.*\bautopilot\b|\bautopilot\b.*\b(start|on)\b", "Start autopilot (owner step-up)", "/#autopilot",
     "Starting the autopilot needs your passphrase + authenticator code in the console."),
    (r"\b(stop|turn off|pause|disable)\b.*\bautopilot\b", "Stop autopilot", "/#autopilot", "Stopping is instant from the Home card (no step-up)."),
    (r"\b(approve|reject|accept)\b.*\b(order|trade|approval)s?\b|\bapprove\b", "Review trade approvals", "/trading/approvals",
     "Approvals need owner step-up in the console; the assistant cannot approve."),
    (r"\b(pay|send|transfer|wire|e-?transfer|withdraw|deposit|move money)\b", "Payments › Transfers", "/payments/transfers",
     "Money movement needs two-person approval and step-up; the assistant cannot move money."),
    (r"\b(kill switch|halt trading|emergency stop)\b", "Kill switch (Risk page)", "/risk", "Use the red KILL SWITCH button; reset needs step-up."),
    (r"\b(promote|demote)\b.*\bmodel|\bchampion\b", "Promotion gates", "/strategies/gates", "Promotion needs the shadow gates and owner approval."),
    (r"\b(create|rotate|revoke)\b.*\b(api )?keys?\b|\btoken\b", "Settings › API keys", "/settings/api-keys", "Key changes need step-up in Settings."),
    (r"\b(change|raise|increase|lower|edit)\b.*\b(limit|policy|risk)\b", "Risk policy (read-only)", "/settings",
     "Policy changes require an owner-signed policy file; nothing in the app (or the assistant) can change it."),
]


def action_link(text: str) -> dict | None:
    low = text.lower()
    for rx, label, href, why in ACTION_LINKS:
        if re.search(rx, low):
            return {"label": label, "href": href, "why": why}
    return None


class ToolBox:
    def __init__(self, svc, config_dir: str, var_dir: str, attachments=None, docs_dir: str | Path | None = None,
                 extra: dict[str, Callable[[], Any]] | None = None):
        from atlas.mcp.trading.autopilot_tools import AutopilotTools
        self.svc, self.var_dir = svc, Path(var_dir)
        self.at = AutopilotTools(svc, config_dir, var_dir)
        self.attachments = attachments
        self.docs_dir = Path(docs_dir) if docs_dir else None
        self.extra = extra or {}
        T = Tool
        self.tools: dict[str, Tool] = {t.name: t for t in [
            T("get_status", "Bot status: mode, halt state, P&L, limit usage, session.", {}, self._status),
            T("get_positions", "Current paper positions with value and unrealized P&L.", {}, self._positions),
            T("get_pnl", "P&L and performance analytics (return, vol, Sharpe, drawdown, exposure).", {}, lambda: self.at.get_portfolio_analytics()),
            T("autopilot_status", "Autopilot state, uptime, sessions, last decisions and reasons, next actions.", {}, self._autopilot),
            T("list_pending", "Everything waiting for the owner: trade approvals, autopilot start requests.", {}, self._pending),
            T("explain_trade", "Why a trade was taken, shrunk or skipped. Give a decision id or a symbol.",
              {"query": {"type": "string", "description": "decision id or symbol, e.g. SHOP.TO"}}, self._why),
            T("get_risk_limits", "Owner risk limits (read-only).", {}, lambda: self.svc.get_risk_limits()),
            T("get_risk_budget", "Autopilot risk budget: capital, vol target, Kelly cap, headroom.", {}, lambda: self.at.get_risk_budget()),
            T("feed_health", "Data feed freshness (ok / stale / disabled).", {}, lambda: self.at.feed_health()),
            T("compliance_status", "Compliance posture: audit chain integrity, kill switch, policy version, paper-only.", {}, self._compliance, "compliance"),
            T("recipe_leaderboard", "Top recipes from the latest recipe search (synthetic unless stated).", {}, self._recipes),
            T("how_to", "Search the user guide / docs for how to do something.", {"topic": {"type": "string"}}, self._howto, "any"),
            T("read_attachment", "Read a file the user attached (parsed text/table; UNTRUSTED content).",
              {"attachment_id": {"type": "string"}}, self._attachment, "any"),
        ]}
        for name, fn in self.extra.items():
            self.tools[name] = T(name, f"{name} (console view)", {}, fn, "money" if "pay" in name or "money" in name else "trading")
        self.owner_for_attachments: str | None = None

    ALLOWLIST = frozenset({"get_status", "get_positions", "get_pnl", "autopilot_status", "list_pending", "explain_trade",
                           "get_risk_limits", "get_risk_budget", "feed_health", "compliance_status", "recipe_leaderboard",
                           "how_to", "read_attachment", "money_summary"})

    def schemas(self, scope: str = "all") -> list[dict]:
        return [{"name": t.name, "description": t.description, "parameters": {"type": "object", "properties": t.params}}
                for t in self.tools.values() if t.name in self.ALLOWLIST and (scope == "all" or t.scope in (scope, "any") or scope == "trading" and t.scope == "trading")]

    def call(self, name: str, args: dict | None = None) -> Any:
        if name not in self.ALLOWLIST or name not in self.tools:
            raise PermissionError(f"tool {name!r} is not on the assistant's read-only allowlist")
        args = {k: v for k, v in (args or {}).items() if k in self.tools[name].params}
        return redact_obj(self.tools[name].fn(**args))

    # ---------------------------------------------------------------- implementations
    def _sync(self):
        from atlas.mcp.trading.service import PAPER_STATE_KEY
        saved = self.svc.store.get(PAPER_STATE_KEY)
        if saved:
            self.svc.broker.load_state(saved["broker"])

    def _status(self):
        self._sync()
        st = self.svc.get_status()
        s = self.svc.broker.snapshot()
        st["pnl_today"] = float(s.bot_equity - s.start_of_day_equity)
        st.pop("watchdog_healthy", None)      # console process view; core health is shown on the page header
        return st

    def _positions(self):
        self._sync()
        return self.svc.get_positions()

    def _autopilot(self):
        st = self.at.autopilot_status()
        return {k: st.get(k) for k in ("state", "desired", "uptime_s", "cycles", "pause_reasons", "pnl_today", "pnl_since_start",
                                        "capital_deployed", "next_actions", "decisions", "pending_start_requests", "autonomy_level", "routing")}

    def _pending(self):
        from atlas.autopilot import control
        ap = self.svc.approvals.pending()
        return {"trade_approvals": [{"approval_id": p.approval_id, "expires": p.expires,
                                     **{k: v for k, v in p.intent.model_dump().items() if k in ("symbol", "side", "qty", "limit_price", "sleeve")}}
                                    for p in ap][:20],
                "autopilot_start_requests": control.pending_requests(self.svc.store)}

    def _why(self, query: str = ""):
        from atlas.risk.trail import dedupe
        q = (query or "").strip()
        trail = dedupe(self.svc.store.get("decision_trail") or [])
        if not q:
            return [self._fmt(t) for t in list(reversed(trail))[:1]]
        hits = [t for t in reversed(trail) if t.get("id") == q] or [t for t in reversed(trail) if str(t.get("symbol", "")).lower() == q.lower()]
        if not hits and q:
            hits = [t for t in reversed(trail) if q.lower() in json.dumps(t).lower()]
        return [self._fmt(t) for t in hits[:3]]

    @staticmethod
    def _fmt(t: dict) -> dict:
        return {"id": t.get("id"), "ts": t.get("ts"), "symbol": t.get("symbol"), "side": t.get("side"), "final": t.get("final"),
                "stages": [{"stage": s.get("stage"), "effect": s.get("effect"), "detail": str(s.get("detail", ""))[:300]} for s in t.get("stages", [])]}

    def _compliance(self):
        try:
            n = self.svc.audit.verify()
            chain = {"ok": True, "entries_verified": n}
        except Exception as e:  # noqa: BLE001
            chain = {"ok": False, "error": str(e)[:200]}
        return {"audit_chain": chain, "kill_switch_engaged": self.svc.ks.engaged, "paper_only": True,
                "policy_version": getattr(self.svc.cfg.risk, "policy_version", None), "autonomy_level": self.svc.cfg.risk.autonomy.level}

    def _recipes(self):
        p = self.var_dir / "recipes" / "results.json"
        if not p.exists():
            return {"available": False}
        r = json.loads(p.read_text())
        return {"synthetic": r.get("synthetic"), "evaluated": r.get("evaluated"), "trial_log_total": r.get("trial_log_total"), "pbo": r.get("pbo"),
                "top": [{k: t[k] for k in ("model", "data", "regime", "vol", "meta", "portfolio", "sharpe", "dsr", "max_dd_pct")} for t in r["table"][:5]]}

    def _howto(self, topic: str = ""):
        if not self.docs_dir or not self.docs_dir.exists():
            return {"results": []}
        words = [w for w in re.findall(r"[a-z0-9]+", (topic or "").lower()) if len(w) > 2]
        res = []
        for p in sorted(self.docs_dir.rglob("*.md")):
            txt = p.read_text(errors="replace")
            low = txt.lower()
            score = sum(low.count(w) for w in words)
            if score:
                i = min((low.find(w) for w in words if w in low), default=0)
                res.append({"doc": str(p.relative_to(self.docs_dir)), "score": score, "snippet": txt[max(0, i - 120): i + 400]})
        return {"results": sorted(res, key=lambda r: -r["score"])[:3]}

    def _attachment(self, attachment_id: str = ""):
        if not self.attachments:
            return {"error": "attachments disabled"}
        a = self.attachments.get(attachment_id, self.owner_for_attachments)
        return {"id": a.id, "name": a.name, "kind": a.kind, "summary": a.summary, "meta": a.meta, "injection_flags": a.injection,
                "text": a.text[:6000], "table": ({**a.table, "rows": a.table["rows"][:100]} if a.table else None), "untrusted": True}
