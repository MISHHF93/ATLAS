"""Instrument contract specs (futures): multiplier, tick, expiry cycle, roll rule, hours, cost assumptions.

SINGLE SOURCE OF TRUTH for futures contract facts (mandate section 6): sizing (``control.engine``, ``risk.sizing.
contracts_for_risk``), replay/lab/markers costs (``intel.data.SPEC`` is derived from here) and the UI
(``/api/intel/contracts``) all read these records. Built on the existing InstrumentMaster (multiplier/tick come from
there, never duplicated). Calendar facts are
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
    hold_bars: int = 96             # research replay max hold (15m bars = 24h)

    @property
    def suite_calendar(self) -> str:
        """TradingCalendar code used by the level suite / replay (COMEX, CMES)."""
        return _XC.get(self.calendar, self.calendar)

    @property
    def field_status(self) -> dict:
        """Honest provenance per field. Nothing is marked verified until an owner checks it against the exchange."""
        v = "verified" if self.verified else "unverified"
        return {"multiplier": f"published CME spec, {v}", "tick_size": f"published CME spec, {v}",
                "contract_months": f"published listing cycle, {v}", "expiry_rule": f"approximation of the exchange rule, {v}",
                "roll_rule": "ATLAS research convention (not an exchange fact)",
                "trading_hours": f"summary, {v}; holidays from exchange_calendars when installed",
                "cost_per_contract_rt_usd": "research assumption (commission + fees + ~1 tick slippage), not a broker quote"}

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
        return {**asdict(self), "tick_value": self.tick_value, "cost_price_units": self.cost_price_units,
                "suite_calendar": self.suite_calendar, "field_status": self.field_status}


_XC = {"COMEX": "COMEX", "CME_EQUITY": "CMES", "CMES": "CMES", "NYMEX": "NYMEX"}


def _sessions(code: str, y0: int, y1: int) -> frozenset[date] | None:
    """Exchange session dates from ``exchange_calendars`` (holidays included); None if the library/calendar is unavailable."""
    xc_code = _XC.get(code)
    if xc_code is None:
        return None
    return _sessions_cached(xc_code, y0, y1)


from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=None)
def _sessions_cached(xc_code: str, y0: int, y1: int) -> frozenset[date] | None:
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar(xc_code, start=f"{max(y0, 2006)}-01-01", end=f"{y1}-12-31")
    except Exception:  # pragma: no cover - library missing or calendar out of range
        return None
    return frozenset(d.date() for d in cal.sessions)


def _is_bday(d: date, sessions: frozenset[date] | None) -> bool:
    return d in sessions if sessions is not None else d.weekday() < 5


def _bdays_back(d: date, n: int, sessions: frozenset[date] | None = None) -> date:
    while n:
        d -= timedelta(days=1)
        if _is_bday(d, sessions):
            n -= 1
    return d


def holiday_source(spec: ContractSpec, year: int) -> str:
    """Which calendar backs the business-day arithmetic: exchange_calendars:<code> or the weekday-only fallback."""
    return f"exchange_calendars:{_XC[spec.calendar]}" if _sessions(spec.calendar, year - 1, year + 1) is not None else "weekday_only"


def last_trade_date(spec: ContractSpec, year: int, month: int) -> date:
    """Business days come from the exchange_calendars session list for the spec's venue (holidays modelled);
    falls back to weekday-only if the library/calendar is unavailable. Rules remain approximations (spec.verified=False)."""
    ses = _sessions(spec.calendar, year - 1, year + 1)
    if spec.expiry_rule == "third_last_business_day":
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        while not _is_bday(last, ses):
            last -= timedelta(days=1)
        return _bdays_back(last, 2, ses)
    if spec.expiry_rule == "third_friday":
        d = date(year, month, 15)
        d = d + timedelta(days=(4 - d.weekday()) % 7)
        while not _is_bday(d, ses):        # exchange holiday on the 3rd Friday -> preceding business day
            d -= timedelta(days=1)
        return d
    raise ValueError(f"unknown expiry_rule {spec.expiry_rule}")


def roll_anchor_date(spec: ContractSpec, year: int, month: int) -> date:
    ses = _sessions(spec.calendar, year - 1, year + 1)
    if spec.roll_anchor == "first_notice":   # approx: last business day of the month before the contract month
        last = date(year, month, 1) - timedelta(days=1)
        while not _is_bday(last, ses):
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
            roll = _bdays_back(roll_anchor_date(spec, y, m), spec.roll_days_before_expiry, _sessions(spec.calendar, y - 1, y + 1))
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


# Round-trip cost assumptions (USD per contract). Consolidated in pass 9 from two copies that disagreed
# (feeds.contracts vs intel.data.SPEC); the HIGHER (more conservative) value of each pair was kept:
# GC 25 (both), MGC 3.5 (was 2.5 / 3.5), SI 125 (was 125 / 75), ES 30 (was 25 / 30).


def default_contracts(master: InstrumentMaster | None = None) -> dict[str, ContractSpec]:
    m = master or InstrumentMaster()
    out = {}
    for args in (("GC", "GJMQVZ", "third_last_business_day", 3, 25.0, True),
                 ("MGC", "GJMQVZ", "third_last_business_day", 3, 3.5, True),
                 ("SI", "HKNUZ", "third_last_business_day", 3, 125.0),
                 ("ES", "HMUZ", "third_friday", 8, 30.0)):
        if args[0] in m:
            out[args[0]] = _spec(m, *args)
    return out


@lru_cache(maxsize=1)
def _defaults_cached() -> dict[str, ContractSpec]:
    return default_contracts()


def contract_for(iid: str) -> ContractSpec | None:
    return _defaults_cached().get(iid)
