"""Alpaca Trading API v2 PAPER adapter. Off by default; transport must be injected."""
from __future__ import annotations

from typing import Any, Protocol

from atlas.marketdata.pit.providers.base import ProviderDisabled, require_real_key
from atlas.risk.models import OrderIntent, RiskDecision
from atlas.execution.adapters.guards import ALPACA_PAPER_HOST, guard_alpaca_account, guard_alpaca_url


class HttpTransport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], json: Any | None = None) -> Any: ...


class OfflineHttp:
    def request(self, method, url, headers, json=None):
        raise ProviderDisabled(f"network disabled: {method} {url}")


class AlpacaPaperAdapter:
    name = "alpaca"

    def __init__(self, key_id: str | None = None, secret: str | None = None, enabled: bool = False,
                 transport: HttpTransport | None = None, base_url: str = f"https://{ALPACA_PAPER_HOST}"):
        self.base_url = guard_alpaca_url(base_url).rstrip("/")  # live URL => LiveTradingForbidden
        self.enabled = enabled
        self._key_id, self._secret = key_id, secret
        self.transport = transport or OfflineHttp()
        self._verified = False

    def __repr__(self) -> str:  # never print credentials
        return f"AlpacaPaperAdapter(enabled={self.enabled}, base_url={self.base_url})"

    def _call(self, method: str, path: str, body: Any | None = None) -> Any:
        if not self.enabled:
            raise ProviderDisabled("Alpaca paper adapter disabled")
        headers = {"APCA-API-KEY-ID": require_real_key(self._key_id, "ALPACA_API_KEY_ID"),
                   "APCA-API-SECRET-KEY": require_real_key(self._secret, "ALPACA_API_SECRET_KEY")}
        url = guard_alpaca_url(self.base_url + path)
        return self.transport.request(method, url, headers, body)

    def verify_paper_account(self) -> dict:
        acct = self._call("GET", "/v2/account")
        guard_alpaca_account(acct)
        self._verified = True
        return acct

    def _ensure(self) -> None:
        if not self._verified:
            self.verify_paper_account()

    @staticmethod
    def order_payload(intent: OrderIntent) -> dict:
        p = {"symbol": intent.symbol, "qty": str(intent.qty), "side": intent.side, "type": intent.order_type,
             "time_in_force": "day", "client_order_id": intent.intent_id}  # idempotency key
        if intent.order_type == "limit":
            p["limit_price"] = str(intent.limit_price)
        return p

    def submit(self, intent: OrderIntent, decision: RiskDecision) -> str:
        if not decision.approved or decision.intent_id != intent.intent_id:
            raise PermissionError("adapter accepts only risk-approved intents")
        self._ensure()
        return self._call("POST", "/v2/orders", self.order_payload(intent))["id"]

    def cancel_all(self, reason: str = "") -> int:
        return len(self._call("DELETE", "/v2/orders") or [])

    def flatten_all(self, reason: str = "") -> int:
        return len(self._call("DELETE", "/v2/positions?cancel_orders=true") or [])

    def positions_qty(self) -> dict[str, float]:
        return {p["symbol"]: float(p["qty"]) for p in self._call("GET", "/v2/positions")}

    def cash(self) -> float:
        return float(self._call("GET", "/v2/account")["cash"])
