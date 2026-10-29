"""Broker-agnostic, READ-ONLY account snapshot (evo-13 phase 1).

One schema for every broker (ATLAS paper sim, Alpaca paper, OANDA practice, later IBKR paper / Questrade). Everything a broker may
not report is ``None`` (unknown), never a guessed number. The snapshot never carries a secret and never grants execution: it only
describes the account so the ML and the dashboard can see the constraints the deterministic control plane already enforces.
See ATLAS_ACCOUNT_AWARENESS.md."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
STATUSES = ("ok", "not_configured", "needs_verification", "verification_failed", "refused_live", "error")
ENVIRONMENTS = ("simulated", "paper", "practice")   # live is not representable on purpose


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def num(v: Any) -> float | None:
    """Broker JSON gives numbers as strings or null; anything unparsable or non-finite is unknown (None)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


@dataclass
class PositionView:
    symbol: str
    qty: float
    side: str = "long"
    avg_price: float | None = None
    market_value: float | None = None
    unrealized_pl: float | None = None
    asset_class: str | None = None


@dataclass
class OrderView:
    order_id: str
    symbol: str
    side: str
    qty: float | None = None
    notional: float | None = None
    order_type: str | None = None
    status: str | None = None
    submitted_at: str | None = None


@dataclass
class Balances:
    cash: float | None = None
    equity: float | None = None
    buying_power: float | None = None
    settled_cash: float | None = None
    margin_used: float | None = None
    margin_available: float | None = None
    leverage_max: float | None = None          # e.g. Alpaca "multiplier" (1 = cash account), OANDA 1/marginRate


@dataclass
class TradingRules:
    min_order_notional: float | None = None    # smallest order the venue accepts, account currency
    min_order_qty: float | None = None
    fractional: bool | None = None
    shorting_allowed: bool | None = None
    margin_enabled: bool | None = None
    pdt_applies: bool | None = None            # FINRA PDT rule: retired for US brokers on 2026-06-04 (Reg Notice 26-10); broker may still flag
    pdt_note: str | None = None
    settlement_days: int | None = None
    trading_blocked: bool | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class FeeSchedule:
    commission_per_order: float | None = None
    commission_per_unit: float | None = None
    commission_min: float | None = None
    commission_max_pct: float | None = None    # cap as % of trade value (IBKR Fixed: 1%)
    spread_bps_assumed: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class MarketState:
    is_open: bool | None = None
    next_open: str | None = None
    next_close: str | None = None
    source: str | None = None


@dataclass
class AccountSnapshot:
    broker: str
    environment: str = "simulated"
    status: str = "ok"
    reason: str = ""
    as_of: str = field(default_factory=now_iso)
    currency: str | None = None
    account_ref: str | None = None             # masked (last 4), never the full account number
    balances: Balances = field(default_factory=Balances)
    positions: list[PositionView] = field(default_factory=list)
    open_orders: list[OrderView] = field(default_factory=list)
    rules: TradingRules = field(default_factory=TradingRules)
    fees: FeeSchedule = field(default_factory=FeeSchedule)
    market: MarketState = field(default_factory=MarketState)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    read_only: bool = True
    execution_permission: str = "none"

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(f"environment must be one of {ENVIRONMENTS}; live accounts are not representable")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        self.read_only, self.execution_permission = True, "none"   # fixed, not configurable

    @property
    def usable(self) -> bool:
        return self.status == "ok" and self.balances.equity is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mask(account_id: str | None) -> str | None:
    s = str(account_id or "")
    return None if not s else ("…" + s[-4:] if len(s) > 4 else "…" + s)


def unavailable(broker: str, environment: str, status: str, reason: str) -> AccountSnapshot:
    """A snapshot that says why there is no data. No balances, no network was used."""
    return AccountSnapshot(broker=broker, environment=environment, status=status, reason=reason)
