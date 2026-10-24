"""Instrument contract specs (futures): multiplier, tick, expiry cycle, roll rule, hours, cost assumptions.

Built on the existing InstrumentMaster (multiplier/tick come from there, never duplicated). Calendar facts are
the published CME product specs as understood at writing time; ``verified`` stays False until an owner checks
them against the exchange. Costs are explicit research *assumptions*, not broker quotes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .instruments import InstrumentMaster

MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


@dataclass(frozen=True)
class ContractSpec:
    instrument_id: str
    exchange: str
    multiplier: float
    tick_size: float
    contract_months: str            # month codes of the listed cycle used for the continuous series
    expiry_rule: str                # machine key, see last_trade_date
    roll_rule: str
    roll_days_before_expiry: int
    roll_anchor: str                # "first_notice" (physically delivered metals) | "last_trade" (cash-settled)
    trading_hours: str
    calendar: str                   # atlas TradingCalendar code
    cost_per_contract_rt_usd: float # assumption: commission + fees + 1 tick slippage, round trip
    cost_source: str = "research_assumption"
    verified: bool = False
    gold_only: bool = False

    @property
    def tick_value(self) -> float:
        return round(self.tick_size * self.multiplier, 10)

    @property
    def cost_price_units(self) -> float:
        """Round-trip cost per contract expressed in price units (what ReplayConfig.cost_per_unit expects)."""
        return self.cost_per_contract_rt_usd / self.multiplier

    def notional(self, price: float, qty: float = 1.0) -> float:
        return price * self.multiplier * qty

    def as_dict(self) -> dict:
        return {**asdict(self), "tick_value": self.tick_value, "cost_price_units": self.cost_price_units}


def _bdays_back(d: date, n: int) -> date:
    while n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def last_trade_date(spec: ContractSpec, year: int, month: int) -> date:
    """Exchange holidays are NOT modelled (weekday-only approximation); flagged via spec.verified=False."""
    if spec.expiry_rule == "third_last_business_day":
        end = (date(year + (month == 12), month % 12 + 1, 1))
        last = end - timedelta(days=1)
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        return _bdays_back(last, 2)
    if spec.expiry_rule == "third_friday":
        d = date(year, month, 15)
        return d + timedelta(days=(4 - d.weekday()) % 7)
    raise ValueError(f"unknown expiry_rule {spec.expiry_rule}")


def roll_anchor_date(spec: ContractSpec, year: int, month: int) -> date:
    if spec.roll_anchor == "first_notice":   # approx: last business day of the month before the contract month
        last = date(year, month, 1) - timedelta(days=1)
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        return last
    return last_trade_date(spec, year, month)


def front_contract(spec: ContractSpec, on: date) -> tuple[str, date, date]:
    """(code e.g. 'GCZ26', last_trade, roll_date) of the contract the continuous series should hold on ``on``."""
    months = sorted(MONTH_CODES[c] for c in spec.contract_months)
    inv = {v: k for k, v in MONTH_CODES.items()}
    for y in (on.year, on.year + 1):
        for m in months:
            lt = last_trade_date(spec, y, m)
            roll = _bdays_back(roll_anchor_date(spec, y, m), spec.roll_days_before_expiry)
            if on < roll:
                return f"{spec.instrument_id}{inv[m]}{y % 100:02d}", lt, roll
    raise RuntimeError("no contract found")


_HOURS = "CME Globex Sun-Fri 18:00-17:00 America/New_York, daily 60-min maintenance break"


def _spec(m: InstrumentMaster, iid, months, rule, roll, cost, gold=False):
    i = m.get(iid)
    return ContractSpec(iid, "COMEX" if iid in ("GC", "MGC", "SI") else "CME", float(i.multiplier), float(i.tick_size), months,
                        rule, f"roll N business days before {'first notice' if iid in ('GC', 'MGC', 'SI') else 'last trade'} (approx)", roll,
                        "first_notice" if iid in ("GC", "MGC", "SI") else "last_trade", _HOURS,
                        "COMEX" if iid in ("GC", "MGC", "SI") else "CME_EQUITY", cost, gold_only=gold)


def default_contracts(master: InstrumentMaster | None = None) -> dict[str, ContractSpec]:
    m = master or InstrumentMaster()
    out = {}
    for args in (("GC", "GJMQVZ", "third_last_business_day", 3, 25.0, True),
                 ("MGC", "GJMQVZ", "third_last_business_day", 3, 2.5, True),
                 ("SI", "HKNUZ", "third_last_business_day", 3, 125.0),
                 ("ES", "HMUZ", "third_friday", 8, 25.0)):
        if args[0] in m:
            out[args[0]] = _spec(m, *args)
    return out


def contract_for(iid: str) -> ContractSpec | None:
    return default_contracts().get(iid)
