"""Compose the console: auth + trading API + payments API + prefs/sessions + static SPA."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path

from atlas.governance.integrity.crypto import write_secret_json

from atlas.console import inbox
from atlas.console.auth import Sessions, Users
from atlas.console.payments_api import PaymentsAPI
from atlas.console.wallet_api import WalletAPI
from atlas.console.trading_api import TradingAPI
from atlas.console.web import App, Request, Router, make_handler

THEMES = ("system", "light", "dark")
NOTIFY_KEYS = ("kill_switch", "approvals", "transfers", "drift", "daily_summary", "recon_flags")
DEFAULT_PREFS = {"display_name": "", "theme": "system", "density": "comfortable",
                 "notifications": {k: True for k in NOTIFY_KEYS} | {"channel": "in-app"}}


@dataclass
class ConsolePaths:
    var: Path
    config: Path
    state_db: str
    audit_db: str
    tax_db: str
    models: Path
    reports: Path
    stepup: Path
    tokens: Path
    payments_var: Path
    users: Path
    prefs: Path

    @classmethod
    def under(cls, var: str | Path, config: str | Path = "config/founder", payments_var: str | Path | None = None) -> "ConsolePaths":
        v = Path(var)
        return cls(v, Path(config), str(v / "state.sqlite"), str(v / "audit.sqlite"), str(v / "tax.sqlite"), v / "models",
                   v / "reports", v / "owner_stepup.json", v / "mcp_tokens.json", Path(payments_var or v / "payments"),
                   v / "console_users.json", v / "console_prefs.json")


class Prefs:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def get(self, user: str) -> dict:
        d = json.loads(self.path.read_text()) if self.path.exists() else {}
        p = json.loads(json.dumps(DEFAULT_PREFS))
        u = d.get(user, {})
        p.update({k: v for k, v in u.items() if k != "notifications"})
        p["notifications"].update(u.get("notifications", {}))
        return p

    def set(self, user: str, body: dict) -> dict:
        cur = self.get(user)
        if "display_name" in body:
            cur["display_name"] = str(body["display_name"]).strip()[:60]
        if body.get("theme") in THEMES:
            cur["theme"] = body["theme"]
        if body.get("density") in ("comfortable", "compact"):
            cur["density"] = body["density"]
        n = body.get("notifications")
        if isinstance(n, dict):
            for k in NOTIFY_KEYS:
                if k in n:
                    cur["notifications"][k] = bool(n[k])
            if n.get("channel") in ("in-app", "email-placeholder", "off"):
                cur["notifications"]["channel"] = n["channel"]
        with self.lock:
            d = json.loads(self.path.read_text()) if self.path.exists() else {}
            d[user] = cur
            write_secret_json(self.path, d)
        return cur


def _money_summary(payments) -> dict:
    """Read-only payments view for the assistant (no account numbers; amounts and counts only)."""
    s = payments.summary(None)
    if not s.get("available"):
        return {"available": False}
    return {"available": True, "cash_cad_equiv": s["cash_cad_equiv"], "by_status": s["by_status"], "kill_switch": s["kill_switch"],
            "pending_manual": [{"id": t.get("id"), "amount": t.get("amount"), "currency": t.get("currency"), "status": t.get("status")}
                               for t in s["pending_manual"]][:10], "required_approvals": s["required_approvals"]}


def build_app(svc, paths: ConsolePaths, port: int, demo: bool = False) -> tuple[App, TradingAPI, PaymentsAPI]:
    router = Router()
    trading = TradingAPI(svc, paths.config, paths.stepup, paths.tokens, paths.reports, paths.models)
    payments = PaymentsAPI(paths.payments_var)
    users, sessions, prefs = Users(paths.users), Sessions(), Prefs(paths.prefs)
    wallet = WalletAPI(paths.payments_var)
    trading.routes(router)
    from atlas.console.chat_api import ChatAPI
    chat = ChatAPI(svc, paths.config, paths.var, Path(paths.config).resolve().parent / "docs",
                   {"money_summary": lambda: _money_summary(payments)})
    chat.routes(router)
    payments.routes(router)
    wallet.routes(router)

    def audit(event: str, payload: dict, actor: str) -> None:
        try:
            svc.audit.append(event, payload, actor=actor)
        except Exception:  # noqa: BLE001
            pass

    def me(req: Request):
        u = req.session.user
        return {"user": u, "prefs": prefs.get(u), "demo": demo,
                "enrolment": {"console_login": users.enrolled(u), "trading_stepup": trading.stepup_enrolled() and u == trading.owner,
                              "payments_approver": payments.approver_enrolled(u)},
                "sessions": [s.public(s.sid == req.session.sid) for s in sessions.list(u)]}

    def set_prefs(req: Request):
        return {"prefs": prefs.set(req.session.user, req.body)}

    def revoke_session(req: Request):
        ok = sessions.revoke(req.session.user, req.params["sid"])
        if not ok:
            raise KeyError(req.params["sid"])
        audit("console.session_revoked", {"session": req.params["sid"]}, req.session.user)
        return {"revoked": True}

    def inbox_view(req: Request):
        return inbox.build(svc, trading, payments, wallet, demo)

    def nav_counts(req: Request):
        """Sidebar badges = the Home 'Action needed' counts per section (same queries)."""
        out = {"approvals": len(svc.approvals.pending()), "halted": svc.ks.engaged}
        try:
            ib = inbox.build(svc, trading, payments, wallet, demo)
            out |= {"sections": ib["counts"], "payments_kill": any(i["kind"] == "payments_kill" for i in ib["items"])}
        except Exception:  # noqa: BLE001
            pass
        try:   # stale-data banner: enabled feeds whose cache is older than their freshness budget
            h = trading._ap_tools().feed_health()
            out["stale_feeds"] = sorted(f["name"] for f in h["feeds"] if f.get("status") == "stale")
        except Exception:  # noqa: BLE001
            out["stale_feeds"] = []
        return out

    router.add("GET", "/api/me", me)
    router.add("POST", "/api/prefs", set_prefs)
    router.add("POST", "/api/sessions/<sid>/revoke", revoke_session)
    router.add("GET", "/api/nav", nav_counts)
    router.add("GET", "/api/inbox", inbox_view)

    def info() -> dict:
        return {"demo": demo, "mode": "paper", "live_available": False, "owner": trading.owner}

    app = App(router, users, sessions, port, {"trading": trading.verify_stepup, "payments": payments.verify_stepup,
                                              "investor": wallet.verify_investor_stepup}, audit, info,
              portal_sessions=Sessions(), portal_login=wallet.portal_login)
    app.wallet = wallet
    return app, trading, payments


def make_server(svc, paths: ConsolePaths, port: int = 8770, demo: bool = False, bind: str = "127.0.0.1"):
    from atlas.risk.safety import assert_paper_only
    assert_paper_only()
    if bind not in ("127.0.0.1", "localhost") and os.environ.get("ATLAS_IN_CONTAINER") != "1":
        raise ValueError("console binds loopback only")
    app, _, _ = build_app(svc, paths, port, demo)
    srv = ThreadingHTTPServer((bind, port), make_handler(app))
    srv.daemon_threads = True
    srv.app = app
    return srv
