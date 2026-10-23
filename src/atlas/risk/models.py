from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderIntent(BaseModel):
    """What a strategy/AI may *propose*. Never an order by itself."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    qty: float = Field(gt=0, allow_inf_nan=False)
    order_type: Literal["market", "limit"]
    limit_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reference_price: float | None = Field(default=None, gt=0, allow_inf_nan=False,
                                          description="last NBBO mid in instrument currency")
    fx_rate_to_base: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    sleeve: str
    asset_class: str
    broker: str
    source: Literal["ai", "strategy", "owner"] = "ai"
    currency: str = Field(default="CAD", min_length=3, max_length=3)
    sector: str | None = None
    issuer: str | None = Field(default=None, description="ISIN; used for issuer netting across listings")
    quote_age_s: float | None = Field(default=None, ge=0, allow_inf_nan=False,
                                      description="age of reference quote; None => treated as stale")

    @model_validator(mode="after")
    def _limit_needs_price(self) -> "OrderIntent":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        return self


class Position(BaseModel):
    symbol: str
    qty: float
    avg_price: float
    last_price: float
    sleeve: str
    fx_rate_to_base: float = 1.0
    currency: str = "CAD"
    sector: str | None = None
    issuer: str | None = None
    asset_class: str = "equity"

    @property
    def issuer_key(self) -> str:
        return self.issuer or self.symbol

    @property
    def market_value_base(self) -> float:
        return self.qty * self.last_price * self.fx_rate_to_base


class PortfolioState(BaseModel):
    """Snapshot in base currency. `total_account_equity_base` spans all brokers
    (bot + non-bot money); bot capital is capped at allocation_cap_pct of it."""
    total_account_equity_base: float = Field(gt=0)
    bot_cash_base: float = Field(ge=0)
    positions: dict[str, Position] = {}
    start_of_day_equity: float = Field(gt=0)
    start_of_week_equity: float = Field(gt=0)
    peak_equity: float = Field(gt=0)
    open_orders: int = Field(default=0, ge=0)
    settled_cash_base: float | None = Field(default=None, ge=0, description="None => all cash settled")
    pending_sell_qty: dict[str, float] = Field(default_factory=dict, description="qty in resting sell orders per symbol")

    @property
    def settled_cash(self) -> float:
        return self.bot_cash_base if self.settled_cash_base is None else min(self.settled_cash_base, self.bot_cash_base)

    def currency_exposure(self, ccy: str) -> float:
        return sum(p.market_value_base for p in self.positions.values() if p.currency == ccy)

    def sector_exposure(self, sector: str, sectorless: frozenset = frozenset()) -> float:
        def key(p):
            return p.sector or (None if p.asset_class in sectorless else "unknown")
        return sum(p.market_value_base for p in self.positions.values() if key(p) == sector)

    def issuer_exposure(self, issuer_key: str) -> float:
        return sum(p.market_value_base for p in self.positions.values() if p.issuer_key == issuer_key)

    @property
    def gross_exposure_base(self) -> float:
        return sum(abs(p.market_value_base) for p in self.positions.values())

    @property
    def bot_equity(self) -> float:
        return self.bot_cash_base + sum(p.market_value_base for p in self.positions.values())

    def sleeve_exposure(self, sleeve: str) -> float:
        return sum(p.market_value_base for p in self.positions.values() if p.sleeve == sleeve)


class RiskDecision(BaseModel):
    intent_id: str
    approved: bool
    reasons: list[str]
    checks: dict[str, bool]
    halted: bool
    policy_version: int
    warnings: list[str] = []
    executes: bool = False  # this build: decision only unless routed to the paper sim
