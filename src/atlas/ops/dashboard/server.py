"""Local dashboard server (stdlib only). Binds 127.0.0.1 ONLY.

GET  /                 dashboard (based on trading-bot/ui/index.html)
GET  /api/state        read-only JSON
GET  /api/equity       equity history [[iso_ts, equity], ...]
GET  /api/audit        last N audit entries (payloads redacted at write time, truncated here)
GET  /api/markets      follow-the-sun market-hours strip (cached 60 s)
GET  /api/models      model registry overview (status, last retrain, drift) + autonomy readiness
GET  /api/payments    payments/treasury summary via the READ-ONLY BalanceView (mode=ro); no write path
GET  /api/decisions   per-decision explanation trail (newest first; ?limit=N&final=submitted|dropped)
GET  /healthz          {"ok": bool}
POST /api/kill         engage kill switch; needs X-Dashboard-Token == env DASHBOARD_TOKEN
                       (constant-time), same-origin, JSON body {reason}. No reset/flatten/approve here.
Host-header allowlist (DNS-rebinding defence), strict CSP, no CORS.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

from atlas.risk.safety import assert_paper_only

COLORS = {"core": "#374151", "active": "#6b8fb3", "high_risk": "#d97706", "derivatives": "#d1d5db"}
STATIC = {"index.html": "text/html; charset=utf-8", "style.css": "text/css; charset=utf-8", "app.js": "application/javascript; charset=utf-8"}
MAX_BODY = 4096


def build_state(svc) -> dict[str, Any]:
    st = svc.get_status()
    snap = svc.broker.snapshot()
    cap = svc.engine.bot_capital(snap) or 1.0
    r = svc.cfg.risk
    sleeves = [{"name": k, "target_pct": v.target_pct, "actual_pct": snap.sleeve_exposure(k) / cap * 100,
                "drift_pp": snap.sleeve_exposure(k) / cap * 100 - v.target_pct, "locked": v.locked,
                "color": COLORS.get(k, "#9ca3af")} for k, v in r.sleeves.items()]
    pl, ll = r.position_limits, r.loss_limits
    rows = [("Bot capital cap", f"{r.capital.allocation_cap_pct}% of account (ceiling {r.capital.allocation_cap_hard_ceiling_pct}%)"),
            ("Daily / weekly loss", f"{ll.daily_pct}% / {ll.weekly_pct}%"), ("Max drawdown", f"{ll.max_drawdown_pct}%"),
            ("Max position", f"{pl.max_position_pct_bot_capital}% · ${pl.max_position_notional_base:,.0f}"),
            ("Gross exposure", f"≤ {pl.max_gross_exposure_pct}% (no leverage)"),
            ("FX net / single ccy", f"{pl.max_net_fx_exposure_pct}% / {pl.max_single_currency_pct}%"),
            ("Sector", f"{pl.max_sector_pct}%"), ("Price collar", f"±{pl.price_collar_pct}%"),
            ("Orders/min · open", f"{pl.max_orders_per_minute} · {pl.max_open_orders}"),
            ("Drift band · max cost", f"{r.rebalance.drift_band_pp}pp · {r.rebalance.max_cost_bps}bps")]
    return {"status": st, "pnl_today": snap.bot_equity - snap.start_of_day_equity, "sleeves": sleeves,
            "positions": svc.get_positions(), "approvals": svc.list_approvals(), "limit_rows": rows,
            "limits": {"policy_version": r.version, "loss_limits": ll.model_dump(), "autonomy_level": r.autonomy.level,
                       "approval_required": svc.approval_required, "drift_band_pp": r.rebalance.drift_band_pp}}


def audit_view(svc, limit: int = 50) -> list[dict]:
    rows = svc.audit.entries()[-max(1, min(limit, 500)):]
    out = []
    for r in reversed(rows):
        p = json.dumps(r["payload"], default=str)
        out.append({"seq": r["seq"], "ts": r["ts"], "event": r["event"], "actor": r["actor"],
                    "payload": p if len(p) <= 300 else p[:297] + "...", "hash": r["hash"][:12]})
    return out


_MKT_CACHE: dict = {}


def markets(svc, now=None) -> dict:
    from datetime import datetime, timezone
    from atlas.ops.sessions import SessionModel
    now = now or datetime.now(timezone.utc)
    c = _MKT_CACHE.get(id(svc))
    if c and (now - c[0]).total_seconds() < 60:
        return c[1]
    data = SessionModel(svc.cfg.schedule.model_dump()).strip(now)
    _MKT_CACHE[id(svc)] = (now, data)
    return data


def make_handler(svc, token: str | None, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "atlas-dashboard"

        def log_message(self, *a):  # keep stdout clean; audit log records mutations
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(421, b'{"error":"bad host"}')
            path = self.path.split("?")[0]
            if path == "/api/state":
                return self._send(200, json.dumps(build_state(svc), default=str).encode())
            if path == "/api/equity":
                from atlas.ops.equity import equity_series
                return self._send(200, json.dumps(equity_series(svc)).encode())
            if path == "/api/audit":
                q = self.path.partition("?")[2]
                lim = 50
                for kv in q.split("&"):
                    if kv.startswith("limit=") and kv[6:].isdigit():
                        lim = int(kv[6:])
                return self._send(200, json.dumps(audit_view(svc, lim), default=str).encode())
            if path == "/api/markets":
                return self._send(200, json.dumps(markets(svc), default=str).encode())
            if path == "/api/models":
                from atlas.models.quant.multi import models_overview
                return self._send(200, json.dumps({"models": models_overview(svc.models_root),
                                                   "autonomy": svc.store.get("autonomy_readiness")}, default=str).encode())
            if path == "/api/decisions":
                q = dict(kv.split("=", 1) for kv in self.path.partition("?")[2].split("&") if "=" in kv)
                lim = int(q["limit"]) if q.get("limit", "").isdigit() else 50
                from atlas.risk.trail import dedupe, outcome_counts
                raw = dedupe(svc.store.get("decision_trail") or [])  # also collapses legacy, un-merged stores
                trail = list(reversed(raw))
                f = q.get("final")
                if f in ("submitted", "dropped"):
                    trail = [t for t in trail if str(t.get("final", "")).startswith(f)]
                summ = outcome_counts(raw)
                return self._send(200, json.dumps({"decisions": trail[:min(lim, 500)], "outcomes": summ,
                                                   "sim": svc.store.get("sim_summary")}, default=str).encode())
            if path == "/api/payments":
                return self._send(200, json.dumps(payments_summary(), default=str).encode())
            if path == "/healthz":
                ok = svc.watchdog.healthy() and not svc.ks.engaged
                return self._send(200 if ok else 503, json.dumps({"ok": ok, "halted": svc.ks.engaged}).encode())
            name = "index.html" if path in ("/", "/index.html") else path.removeprefix("/static/")
            if name in STATIC:
                body = resources.files("atlas.ops.dashboard").joinpath("static", name).read_bytes()
                return self._send(200, body, STATIC[name])
            self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if not self._host_ok():
                return self._send(421, b'{"error":"bad host"}')
            if self.path != "/api/kill":
                return self._send(404, b'{"error":"not found"}')
            origin = self.headers.get("Origin")
            if origin is not None and origin.removeprefix("http://") not in allowed_hosts:
                return self._send(403, b'{"error":"cross-origin"}')
            if not token or not hmac.compare_digest((self.headers.get("X-Dashboard-Token") or "").encode(), token.encode()):
                svc.audit.append("dashboard.auth_failed", {}, actor="dashboard")
                return self._send(401, b'{"error":"unauthorized"}')
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY or "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._send(400, b'{"error":"bad request"}')
            try:
                reason = str(json.loads(self.rfile.read(n) or b"{}").get("reason", ""))[:200] or "dashboard"
            except Exception:
                return self._send(400, b'{"error":"bad json"}')
            res = svc.ks.engage(reason, channel="dashboard")
            self._send(200, json.dumps(res, default=str).encode())

        def do_PUT(self):
            self._send(405, b'{"error":"read-only"}')

        do_DELETE = do_PATCH = do_PUT

    return H



def payments_summary(db_path: str | None = None) -> dict:
    """Payments panel data. Only `atlas.ledgers.readonly.BalanceView` is imported: it opens the
    treasury DB with SQLite mode=ro and has no write methods. Missing DB/package => available: False."""
    db_path = db_path or os.environ.get("ATLAS_PAYMENTS_DB", "var/payments/payments.sqlite")
    if not os.path.exists(db_path):
        return {"available": False, "reason": "payments DB not found (read-only view)"}
    try:
        from atlas.ledgers.readonly import BalanceView
        v = BalanceView(db_path)
        return {"available": True, "read_only": True, **v.summary()}
    except Exception as e:  # noqa: BLE001  never let the payments panel break the trading dashboard
        return {"available": False, "reason": f"payments view error: {type(e).__name__}"}

def make_server(svc, port: int = 8765, token: str | None = None, bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    """bind defaults to loopback. A non-loopback bind is allowed ONLY inside a container
    (ATLAS_IN_CONTAINER=1), where docker-compose publishes the port on the HOST's 127.0.0.1."""
    assert_paper_only()
    if bind not in ("127.0.0.1", "localhost") and os.environ.get("ATLAS_IN_CONTAINER") != "1":
        raise ValueError("dashboard binds loopback only (non-loopback needs ATLAS_IN_CONTAINER=1)")
    token = token or None  # empty => kill button disabled
    if token is not None and (len(token) < 24 or token.startswith("<")):
        raise ValueError("DASHBOARD_TOKEN too short or placeholder")
    srv = ThreadingHTTPServer((bind, port), make_handler(svc, token, port))
    return srv


def serve_in_thread(svc, port: int, token: str | None = None) -> ThreadingHTTPServer:
    srv = make_server(svc, port, token if token is not None else os.environ.get("DASHBOARD_TOKEN") or None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    """Standalone demo: own paper service, shared state DB (kill switch / approvals)."""
    import argparse
    from atlas.mcp.trading.service import build_service
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    svc = build_service(a.config, os.environ.get("ATLAS_AUDIT_DB", ":memory:"), os.environ.get("ATLAS_STATE_DB", ":memory:"))
    svc.heartbeat()
    srv = make_server(svc, a.port, os.environ.get("DASHBOARD_TOKEN") or None, a.bind)
    stop = threading.Event()

    # viewer whenever the state DB is shared (a file): the core process owns execution and paper state;
    # a second executor would fork the persisted broker state. Only a pure in-memory demo executes.
    viewer = os.environ.get("ATLAS_DASHBOARD_VIEWER") == "1" or svc.store.path != ":memory:"

    def beat():
        from datetime import datetime, timezone
        from atlas.ops.equity import record_equity
        while not stop.wait(svc.watchdog.interval_s):
            svc.heartbeat()
            if not viewer:  # standalone demo only; in viewer mode the core process owns these
                svc.process_owner_actions()
                record_equity(svc, datetime.now(timezone.utc))
    threading.Thread(target=beat, daemon=True).start()
    print(f"dashboard on http://127.0.0.1:{a.port}  (kill button {'enabled' if os.environ.get('DASHBOARD_TOKEN') else 'DISABLED: set DASHBOARD_TOKEN'})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
