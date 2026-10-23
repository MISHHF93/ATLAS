"""IBKR PAPER adapter over an injected client (e.g. an ib_async wrapper).
Ports and accounts are hard-guarded to paper. Off by default."""
from __future__ import annotations

from typing import Any, Protocol

from atlas.marketdata.pit.providers.base import ProviderDisabled
from atlas.risk.models import OrderIntent, RiskDecision
from atlas.execution.adapters.guards import guard_ibkr_account, guard_ibkr_port

EXCHANGE_BY_CCY = {"CAD": ("SMART", "TSE"), "USD": ("SMART", "NYSE"), "JPY": ("SMART", "TSEJ"),
                   "HKD": ("SEHK", "SEHK"), "GBP": ("LSE", "LSE"), "EUR": ("SMART", "IBIS")}


class IbClient(Protocol):
    def connect(self, host: str, port: int, client_id: int, readonly: bool) -> None: ...
    def managed_accounts(self) -> list[str]: ...
    def place_order(self, contract: dict, order: dict) -> str: ...
    def global_cancel(self) -> int: ...
    def positions(self) -> list[dict[str, Any]]: ...
    def cash_balance(self, account: str, currency: str) -> float: ...


class IbkrPaperAdapter:
    name = "ibkr"

    def __init__(self, host: str = "127.0.0.1", port: int = 4002, account: str = "", client_id: int = 17,
                 enabled: bool = False, client: IbClient | None = None, base_currency: str = "CAD"):
        self.port = guard_ibkr_port(port)
        self.account = guard_ibkr_account(account) if enabled else account
        self.host, self.client_id, self.enabled, self.client = host, client_id, enabled, client
        self.base_currency = base_currency
        self._connected = False

    def _ensure(self) -> IbClient:
        if not self.enabled or self.client is None:
            raise ProviderDisabled("IBKR paper adapter disabled / no client")
        if not self._connected:
            guard_ibkr_port(self.port)
            self.client.connect(self.host, self.port, self.client_id, False)
            accts = self.client.managed_accounts()
            for a in accts:  # every account on the connection must be paper
                guard_ibkr_account(a)
            if self.account not in accts:
                raise PermissionError(f"account {self.account} not on this connection")
            self._connected = True
        return self.client

    @staticmethod
    def contract(intent: OrderIntent) -> dict:
        if intent.asset_class in ("crypto_spot", "option", "future"):
            raise ValueError(f"asset class {intent.asset_class} not routed to IBKR in this build")
        if intent.asset_class in ("fx", "fx_spot"):
            return {"secType": "CASH", "symbol": intent.symbol[:3], "currency": intent.symbol[-3:], "exchange": "IDEALPRO"}
        ex, primary = EXCHANGE_BY_CCY.get(intent.currency, ("SMART", ""))
        return {"secType": "STK", "symbol": intent.symbol, "currency": intent.currency, "exchange": ex, "primaryExchange": primary}

    def order(self, intent: OrderIntent) -> dict:
        o = {"action": intent.side.upper(), "totalQuantity": intent.qty, "orderType": "MKT" if intent.order_type == "market" else "LMT",
             "tif": "DAY", "account": self.account, "orderRef": intent.intent_id, "outsideRth": False}
        if intent.order_type == "limit":
            o["lmtPrice"] = intent.limit_price
        return o

    def submit(self, intent: OrderIntent, decision: RiskDecision) -> str:
        if not decision.approved or decision.intent_id != intent.intent_id:
            raise PermissionError("adapter accepts only risk-approved intents")
        c = self._ensure()
        return c.place_order(self.contract(intent), self.order(intent))

    def cancel_all(self, reason: str = "") -> int:
        return self._ensure().global_cancel()

    def flatten_all(self, reason: str = "") -> int:
        c = self._ensure()
        n = 0
        for p in c.positions():
            if p["account"] == self.account and float(p["position"]) > 0:
                c.place_order(p["contract"], {"action": "SELL", "totalQuantity": float(p["position"]), "orderType": "MKT",
                                              "tif": "DAY", "account": self.account, "orderRef": f"flatten:{reason[:40]}"})
                n += 1
        return n

    def positions_qty(self) -> dict[str, float]:
        return {p["contract"]["symbol"]: float(p["position"]) for p in self._ensure().positions() if p["account"] == self.account}

    def cash(self) -> float:
        return self._ensure().cash_balance(self.account, self.base_currency)
