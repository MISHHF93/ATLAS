"""Market calendars. Equities via exchange_calendars; crypto 24/7; FX 24/5
(Sun 17:00 -> Fri 17:00 America/New_York). Unknown venue or any error => CLOSED."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
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


class CalendarUnavailable(ValueError):
    """No trustworthy schedule is available for the requested venue and period."""


@dataclass(frozen=True)
class TradingWindow:
    """An actual continuous session interval, with an exclusive closing boundary.

    Lunch breaks split a session into windows. ``session_close`` remains the final
    close, so an entry buffer does not accidentally apply before lunch.
    """

    session_date: date
    open: datetime
    close: datetime
    session_close: datetime


def calendar_metadata(venue: str) -> dict:
    if venue in ("crypto", "fx"):
        return {"calendar": "24/7" if venue == "crypto" else "FX_24x5",
                "source": "ATLAS continuous-session convention", "version": None}
    name = VENUE_TO_XC.get(venue)
    if name is None:
        return {"calendar": None, "source": "unavailable", "version": None}
    try:
        import exchange_calendars as xc
        return {"calendar": name, "source": "exchange_calendars", "version": xc.__version__}
    except ImportError:
        return {"calendar": name, "source": "unavailable", "version": None}


@lru_cache(maxsize=None)
def _cal(name: str):
    import exchange_calendars as xc
    return xc.get_calendar(name)


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("timestamp must be tz-aware")
    return ts.astimezone(timezone.utc)


def trading_windows(venue: str, start: datetime, end: datetime) -> list[TradingWindow]:
    """Full continuous windows overlapping ``[start, end)``; never infer holidays.

    Unsupported venues, missing calendars, or dates outside calendar coverage raise
    ``CalendarUnavailable``. Callers must treat that condition as closed. The
    returned boundaries are UTC and are not clipped to the requested period.
    """
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError("end must be after start")
    windows = []
    if venue == "crypto":
        day = start.date()
        while day <= end.date():
            op = datetime.combine(day, time.min, tzinfo=timezone.utc)
            cl = op + timedelta(days=1)
            windows.append(TradingWindow(day, op, cl, cl))
            day += timedelta(days=1)
    elif venue == "fx":
        local_day = start.astimezone(NY).date()
        sunday = local_day - timedelta(days=(local_day.weekday() + 1) % 7)
        while sunday <= end.astimezone(NY).date():
            op = datetime.combine(sunday, time(17), tzinfo=NY).astimezone(timezone.utc)
            cl = datetime.combine(sunday + timedelta(days=5), time(17), tzinfo=NY).astimezone(timezone.utc)
            windows.append(TradingWindow(sunday, op, cl, cl))
            sunday += timedelta(days=7)
    else:
        name = VENUE_TO_XC.get(venue)
        if name is None:
            raise CalendarUnavailable(f"unsupported calendar venue: {venue}")
        try:
            cal = _cal(name)
            # Include overnight sessions whose session label differs from UTC day.
            first = start.date() - timedelta(days=1)
            last = end.date() + timedelta(days=1)
            if start.date() < cal.first_session.date() or end.date() > cal.last_session.date():
                raise CalendarUnavailable(f"{name} calendar does not cover requested dates")
            schedule = cal.schedule.loc[str(first):str(last)]
            for label, row in schedule.iterrows():
                op, cl = row["open"].to_pydatetime(), row["close"].to_pydatetime()
                if pd.notna(row["break_start"]) and pd.notna(row["break_end"]):
                    windows.append(TradingWindow(label.date(), op, row["break_start"].to_pydatetime(), cl))
                    windows.append(TradingWindow(label.date(), row["break_end"].to_pydatetime(), cl, cl))
                else:
                    windows.append(TradingWindow(label.date(), op, cl, cl))
        except CalendarUnavailable:
            raise
        except Exception as exc:
            raise CalendarUnavailable(f"{name} schedule unavailable ({type(exc).__name__})") from exc
    return [window for window in windows if window.open < end and window.close > start]


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
        now = _utc(ts)
        return bool(trading_windows(venue, now, now + timedelta(microseconds=1)))
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
