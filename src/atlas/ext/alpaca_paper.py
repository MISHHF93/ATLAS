"""Alpaca PAPER broker facade (get_account, get_positions, get_orders, get_clock, place_order incl. bracket,
cancel_all_orders) over the existing guarded ``AlpacaPaperAdapter``.

* Only https://paper-api.alpaca.markets is ever called; any other base URL (including the live api.alpaca.markets) is
  refused by ``guards.guard_alpaca_url`` and reported as "refused_live_endpoint".
* Keys come only from the process environment or the local gitignored .env (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY).
  Without them every call reports "not_configured" and nothing is sent.
* place_order first goes through ``ActionableControlPlaneEngine.submit_order`` (track open_market). A rejected order is
  never sent. A stop-loss (bracket) is mandatory so the control plane can check the stop distance."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

from atlas.execution.adapters.alpaca import AlpacaPaperAdapter
from atlas.execution.adapters.guards import ALPACA_PAPER_HOST
from atlas.risk.safety import LiveTradingForbidden

PAPER_URL = f"https://{ALPACA_PAPER_HOST}"


class UrllibTransport:
    def request(self, method: str, url: str, headers: dict[str, str], json_body: Any | None = None) -> Any:
        data = None if json_body is None else json.dumps(json_body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - guarded paper host only
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"alpaca paper HTTP {e.code}: {e.read()[:300]!r}") from None
        return json.loads(raw) if raw else None


class _Adapt:
    """AlpacaPaperAdapter passes json= by keyword; adapt to UrllibTransport."""
    def __init__(self, t):
        self.t = t

    def request(self, method, url, headers, json=None):
        return self.t.request(method, url, headers, json)


def _env(env_file: str | Path) -> dict[str, str]:
    from atlas.control.policy.loader import parse_env_file
    keys = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ALPACA_BASE_URL")
    file = parse_env_file(Path(env_file))
    return {k: os.environ.get(k) or file.get(k, "") for k in keys}


class AlpacaPaperBroker:
    def __init__(self, env_file: str | Path = ".env", transport=None, env: dict[str, str] | None = None):
        e = env if env is not None else _env(env_file)
        self.base_url = (e.get("ALPACA_BASE_URL") or PAPER_URL).rstrip("/")
        self.status, self.reason, self.adapter = "ok", "", None
        if self.base_url.endswith("/v2"):
            self.base_url = self.base_url[:-3]
        try:
            from atlas.execution.adapters.guards import guard_alpaca_url
            guard_alpaca_url(self.base_url)
        except LiveTradingForbidden as ex:
            self.status, self.reason = "refused_live_endpoint", str(ex)
            return
        if not e.get("ALPACA_API_KEY_ID") or not e.get("ALPACA_API_SECRET_KEY"):
            self.status, self.reason = "not_configured", "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set in the environment or .env"
            return
        self.adapter = AlpacaPaperAdapter(e["ALPACA_API_KEY_ID"], e["ALPACA_API_SECRET_KEY"], enabled=True,
                                          transport=_Adapt(transport or UrllibTransport()), base_url=self.base_url)

    def describe(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "base_url": self.base_url if self.status != "refused_live_endpoint" else None,
                "paper_only": True, "live_endpoint": "hard-refused", "order_gate": "ActionableControlPlaneEngine.submit_order"}

    def _wrap(self, fn) -> dict[str, Any]:
        if self.adapter is None:
            return {"status": self.status, "reason": self.reason, "data": None}
        try:
            return {"status": "ok", "data": fn()}
        except LiveTradingForbidden as ex:
            return {"status": "refused_live_account", "reason": str(ex), "data": None}
        except Exception as ex:  # network / http
            return {"status": "error", "reason": f"{type(ex).__name__}: {ex}"[:300], "data": None}

    def get_account(self):
        def f():
            acct = self.adapter.verify_paper_account()    # refuses a non-PA… account
            keep = ("account_number", "status", "currency", "cash", "equity", "buying_power", "portfolio_value", "pattern_day_trader", "trading_blocked")
            return {k: acct.get(k) for k in keep}
        return self._wrap(f)

    def get_positions(self):
        return self._wrap(lambda: self.adapter._call("GET", "/v2/positions"))

    def get_orders(self, status: str = "open"):
        if status not in ("open", "closed", "all"):
            raise ValueError("status must be open|closed|all")
        return self._wrap(lambda: self.adapter._call("GET", f"/v2/orders?status={status}&limit=100"))

    def get_clock(self):
        return self._wrap(lambda: self.adapter._call("GET", "/v2/clock"))

    def cancel_all_orders(self):
        return self._wrap(lambda: self.adapter._call("DELETE", "/v2/orders"))

    @staticmethod
    def order_payload(symbol: str, qty: float, side: str, order_type: str, stop_loss: float, take_profit: float | None,
                      limit_price: float | None, time_in_force: str, client_order_id: str) -> dict[str, Any]:
        p: dict[str, Any] = {"symbol": symbol.upper(), "qty": str(qty), "side": side, "type": order_type, "time_in_force": time_in_force,
                             "client_order_id": client_order_id}
        if order_type == "limit":
            p["limit_price"] = str(limit_price)
        if take_profit is not None:
            p.update(order_class="bracket", take_profit={"limit_price": str(take_profit)}, stop_loss={"stop_price": str(stop_loss)})
        else:
            p.update(order_class="oto", stop_loss={"stop_price": str(stop_loss)})
        return p

    def place_order(self, engine, *, symbol: str, qty: float, side: str, reference_price: float, stop_loss: float,
                    take_profit: float | None = None, order_type: str = "market", limit_price: float | None = None,
                    time_in_force: str = "day", data_age_ms: float = 0.0) -> dict[str, Any]:
        if side not in ("buy", "sell") or order_type not in ("market", "limit") or qty <= 0 or reference_price <= 0:
            raise ValueError("bad order fields")
        if order_type == "limit" and not limit_price:
            raise ValueError("limit order needs limit_price")
        if (side == "buy" and stop_loss >= reference_price) or (side == "sell" and stop_loss <= reference_price):
            raise ValueError("stop_loss must be on the losing side of the reference price")
        if take_profit is not None and ((side == "buy" and take_profit <= reference_price) or (side == "sell" and take_profit >= reference_price)):
            raise ValueError("take_profit must be on the winning side of the reference price")
        if self.adapter is None:
            return {"status": self.status, "reason": self.reason, "control_plane": None, "sent": False}
        from atlas.control.engine import ActionableOrderRequest
        bps = Decimal(str(round(abs(reference_price - stop_loss) / reference_price * 1e4, 2)))
        dec = engine.submit_order(ActionableOrderRequest(track="open_market", instrument_id=symbol.upper(), side=side,
                                                         notional_usd=Decimal(str(round(qty * reference_price, 2))), stop_kind="structure",
                                                         stop_distance_bps=bps, data_age_ms=data_age_ms))
        cp = {"decision": dec.control_plane_decision, "order_id": dec.order_id, "violations": list(dec.violations)}
        if dec.control_plane_decision != "authorized_and_executed":
            return {"status": "rejected_by_control_plane", "control_plane": cp, "sent": False}
        payload = self.order_payload(symbol, qty, side, order_type, stop_loss, take_profit, limit_price, time_in_force, f"atlas-{dec.order_id}")
        r = self._wrap(lambda: (self.adapter._ensure(), self.adapter._call("POST", "/v2/orders", payload))[1])
        return {"status": r["status"], "reason": r.get("reason"), "control_plane": cp, "sent": r["status"] == "ok", "order": r["data"], "payload": payload}
