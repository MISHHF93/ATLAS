"""Market calendars. Equities via exchange_calendars; crypto 24/7; FX 24/5
(Sun 17:00 -> Fri 17:00 America/New_York). Unknown venue or any error => CLOSED."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from functools import lru_cache
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

VENUE_TO_XC = {
    "XTSE": "XTSE",       # Toronto
    "XNYS": "XNYS",       # NYSE
    "XNAS": "XNAS",       # Nasdaq
    "XNYS_XNAS": "XNYS",  # schedule.yaml combined venue
    "XLON": "XLON",       # London
    "XETR": "XETR",       # Xetra
    "XTKS": "XTKS",       # Tokyo
    "XHKG": "XHKG",       # Hong Kong
    "XASX": "XASX",       # Sydney
    "XPAR": "XPAR",       # Paris
    "XPAR_XAMS": "XPAR",  # schedule.yaml combined venue (Paris calendar)
}
NY = ZoneInfo("America/New_York")


@lru_cache(maxsize=None)
def _cal(name: str):
    import exchange_calendars as xc
    return xc.get_calendar(name)


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("timestamp must be tz-aware")
    return ts.astimezone(timezone.utc)


def fx_open(ts: datetime) -> bool:
    t = _utc(ts).astimezone(NY)
    wd, hm = t.weekday(), t.time()  # Mon=0 .. Sun=6
    if wd == 5:
        return False
    if wd == 6:
        return hm >= time(17, 0)
    if wd == 4:
        return hm < time(17, 0)
    return True


def is_open(venue: str, ts: datetime) -> bool:
    try:
        if venue == "crypto":
            _utc(ts); return True
        if venue == "fx":
            return fx_open(ts)
        name = VENUE_TO_XC.get(venue)
        if name is None:
            return False
        return bool(_cal(name).is_open_on_minute(pd.Timestamp(_utc(ts))))
    except Exception:
        return False


def is_open_cross_checked(venue: str, ts: datetime, other: Callable[[str, datetime], bool]) -> bool:
    """schedule.on_calendar_mismatch: treat_closed."""
    try:
        return is_open(venue, ts) and bool(other(venue, ts))
    except Exception:
        return False


def sessions(venue: str, start: date, end: date) -> list[date]:
    if venue == "crypto":
        return [d.date() for d in pd.date_range(start, end, freq="D")]
    if venue == "fx":
        return [d.date() for d in pd.date_range(start, end, freq="D") if d.weekday() < 5]
    name = VENUE_TO_XC.get(venue)
    if name is None:
        return []
    return [d.date() for d in _cal(name).sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))]


def session_close(venue: str, d: date) -> datetime:
    if venue in ("crypto", "fx"):
        return datetime.combine(d, time(21, 0), tzinfo=timezone.utc)
    return _cal(VENUE_TO_XC[venue]).session_close(pd.Timestamp(d)).to_pydatetime()
