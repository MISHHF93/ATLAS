"""In-memory paper broker: open orders, slippage + commission model, T+N
settlement, cancel-all, fill listeners. No network, ever."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from atlas.risk.models import OrderIntent, PortfolioState, Position, RiskDecision

SETTLEMENT_DAYS = {"crypto_spot": 0, "fx": 0, "fx_spot": 0}  # equities/ETFs default T+1


@dataclass(frozen=True)
class CostModel:
    slippage_bps: float = 5.0          # applied adversely to market/marketable orders
    commission_per_order: float = 1.0  # base currency
    commission_bps: float = 0.0

    def commission(self, notional_base: float) -> float:
        return self.commission_per_order + notional_base * self.commission_bps / 1e4


@dataclass
class Fill:
    order_id: str
    intent_id: str
    symbol: str
    side: str
    qty: float
    price: float
    reference_price: float
    commission: float
    cash_delta: float  # base currency, signed
    currency: str = "CAD"
    fx_rate: float = 1.0
    asset_class: str = "equity"
    issuer: str | None = None
    broker: str = "paper_sim"
    sleeve: str = ""
    ts: str | None = None  # ISO timestamp (set by broker clock if any)


@dataclass
class OpenOrder:
    order_id: str
    intent: OrderIntent


@dataclass
class PaperBroker:
    total_account_equity_base: float
    bot_cash_base: float
    costs: CostModel = field(default_factory=CostModel)
    positions: dict[str, Position] = field(default_factory=dict)
    open_orders: dict[str, OpenOrder] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    pending_settlements: list[tuple[date, float]] = field(default_factory=list)
    today: date = field(default_factory=date.today)
    start_of_day_equity: float | None = None
    start_of_week_equity: float | None = None
    peak_equity: float | None = None
    fill_listeners: list[Callable[[Fill], None]] = field(default_factory=list)
    clock: Callable[[], object] | None = None  # returns tz-aware datetime for fill timestamps
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def __post_init__(self) -> None:
        eq = self.bot_equity()
        self.start_of_day_equity = self.start_of_day_equity or eq
        self.start_of_week_equity = self.start_of_week_equity or eq
        self.peak_equity = self.peak_equity or eq

    # ---------------------------------------------------------------- state
    def bot_equity(self) -> float:
        return self.bot_cash_base + sum(p.market_value_base for p in self.positions.values())

    @property
    def unsettled(self) -> float:
        return sum(a for _, a in self.pending_settlements)

    @property
    def settled_cash(self) -> float:
        return max(0.0, self.bot_cash_base - self.unsettled)

    def snapshot(self) -> PortfolioState:
        eq = self.bot_equity()
        self.peak_equity = max(self.peak_equity or eq, eq)
        return PortfolioState(total_account_equity_base=self.total_account_equity_base, bot_cash_base=max(0.0, self.bot_cash_base),
                              positions={k: v.model_copy() for k, v in self.positions.items()},
                              start_of_day_equity=self.start_of_day_equity, start_of_week_equity=self.start_of_week_equity,
                              peak_equity=self.peak_equity, open_orders=len(self.open_orders),
                              settled_cash_base=self.settled_cash, pending_sell_qty=self.pending_sells())

    def pending_sells(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for oo in self.open_orders.values():
            if oo.intent.side == "sell":
                out[oo.intent.symbol] = out.get(oo.intent.symbol, 0.0) + oo.intent.qty
        return out

    # ---------------------------------------------------------------- persistence (survives restart)
    def to_state(self) -> dict:
        return {"v": 1, "total": self.total_account_equity_base, "cash": self.bot_cash_base,
                "positions": {k: p.model_dump() for k, p in self.positions.items()},
                "open_orders": {k: o.intent.model_dump() for k, o in self.open_orders.items()},
                "pending_settlements": [[d.isoformat(), a] for d, a in self.pending_settlements],
                "today": self.today.isoformat(), "sod": self.start_of_day_equity, "sow": self.start_of_week_equity,
                "peak": self.peak_equity, "sod_week": list(getattr(self, "_sod_week", None) or []) or None,
                "next_id": int(str(self._ids).split("(")[1].rstrip(")")), "n_fills": len(self.fills)}

    def load_state(self, d: dict) -> None:
        self.total_account_equity_base = d["total"]; self.bot_cash_base = d["cash"]
        self.positions = {k: Position(**p) for k, p in d["positions"].items()}
        self.open_orders = {k: OpenOrder(k, OrderIntent(**i)) for k, i in d["open_orders"].items()}
        self.pending_settlements = [(date.fromisoformat(x), a) for x, a in d["pending_settlements"]]
        self.today = date.fromisoformat(d["today"])
        self.start_of_day_equity, self.start_of_week_equity, self.peak_equity = d["sod"], d["sow"], d["peak"]
        if d.get("sod_week"):
            self._sod_week = tuple(d["sod_week"])
        self._ids = itertools.count(d["next_id"])

    def positions_qty(self) -> dict[str, float]:
        return {k: v.qty for k, v in self.positions.items()}

    # ---------------------------------------------------------------- session
    def roll_day(self, new_day: date) -> None:
        self.today = new_day
        self.pending_settlements = [(d, a) for d, a in self.pending_settlements if d > new_day]
        eq = self.bot_equity()
        wk = tuple(new_day.isocalendar())[:2]  # (ISO year, week): week number alone repeats every year
        if wk != getattr(self, "_sod_week", None):
            self.start_of_week_equity = eq
        self._sod_week = wk
        self.start_of_day_equity = eq

    def mark(self, symbol: str, price: float) -> None:
        if symbol in self.positions:
            self.positions[symbol].last_price = price

    # ---------------------------------------------------------------- orders
    def submit(self, intent: OrderIntent, decision: RiskDecision) -> str:
        if not decision.approved or decision.intent_id != intent.intent_id:
            raise PermissionError("paper broker accepts only risk-approved intents")
        oid = f"paper-{next(self._ids)}"
        ref = intent.reference_price
        assert ref is not None
        if intent.order_type == "market" or self._marketable(intent, ref):
            self._fill(oid, intent, ref)
        else:
            self.open_orders[oid] = OpenOrder(oid, intent)
        return oid

    @staticmethod
    def _marketable(intent: OrderIntent, price: float) -> bool:
        lp = intent.limit_price
        return lp is not None and ((intent.side == "buy" and lp >= price) or (intent.side == "sell" and lp <= price))

    def on_price(self, symbol: str, price: float) -> list[Fill]:
        """Feed a new market price: marks positions and fills crossing resting limits."""
        self.mark(symbol, price)
        out = []
        for oid, oo in list(self.open_orders.items()):
            if oo.intent.symbol == symbol and self._marketable(oo.intent, price):
                del self.open_orders[oid]
                out.append(self._fill(oid, oo.intent, price))
        return out

    def _fill(self, oid: str, intent: OrderIntent, ref: float) -> Fill:
        sign = 1 if intent.side == "buy" else -1
        px = ref * (1 + sign * self.costs.slippage_bps / 1e4)
        if intent.limit_price is not None:  # never worse than the limit
            px = min(px, intent.limit_price) if intent.side == "buy" else max(px, intent.limit_price)
        notional = intent.qty * px * intent.fx_rate_to_base
        fee = self.costs.commission(notional)
        pos = self.positions.get(intent.symbol)
        if intent.side == "buy":
            cash_delta = -(notional + fee)
            if pos:
                newq = pos.qty + intent.qty
                pos.avg_price = (pos.avg_price * pos.qty + px * intent.qty) / newq
                pos.qty, pos.last_price = newq, px
            else:
                self.positions[intent.symbol] = Position(
                    symbol=intent.symbol, qty=intent.qty, avg_price=px, last_price=px, sleeve=intent.sleeve,
                    fx_rate_to_base=intent.fx_rate_to_base, currency=intent.currency, sector=intent.sector,
                    issuer=intent.issuer, asset_class=intent.asset_class)
        else:
            if not pos or pos.qty < intent.qty - 1e-9:
                raise ValueError("paper broker: no shorting")
            cash_delta = notional - fee
            pos.qty -= intent.qty
            if pos.qty <= 1e-12:
                del self.positions[intent.symbol]
            days = SETTLEMENT_DAYS.get(intent.asset_class, 1)
            if days > 0:
                self.pending_settlements.append((self.today + timedelta(days=days), cash_delta))
        self.bot_cash_base += cash_delta
        f = Fill(oid, intent.intent_id, intent.symbol, intent.side, intent.qty, px, ref, fee, cash_delta,
                 currency=intent.currency, fx_rate=intent.fx_rate_to_base, asset_class=intent.asset_class,
                 issuer=intent.issuer, broker=intent.broker, sleeve=intent.sleeve,
                 ts=self.clock().isoformat() if self.clock else None)
        self.fills.append(f)
        for cb in self.fill_listeners:
            cb(f)
        return f

    def flatten_all(self, reason: str = "") -> int:
        """Kill-switch flatten: market-sell every position at last price (with slippage).
        Bypasses the risk gate by design because it can only REDUCE risk; audited by caller."""
        n = 0
        for sym, p in list(self.positions.items()):
            i = OrderIntent(symbol=sym, side="sell", qty=p.qty, order_type="market", reference_price=p.last_price,
                            fx_rate_to_base=p.fx_rate_to_base, currency=p.currency, sleeve=p.sleeve,
                            asset_class=p.asset_class, broker="paper_sim", source="owner", quote_age_s=0)
            self._fill(f"flatten-{next(self._ids)}", i, p.last_price)
            n += 1
        return n

    def cancel_all(self, reason: str = "") -> int:
        n = len(self.open_orders)
        self.open_orders.clear()
        return n
