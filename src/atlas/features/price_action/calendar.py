"""Trading-day calendars for price-level definitions (store UTC, interpret per venue).

- ``crypto``: 24/7, trading day = UTC calendar date.
- any exchange_calendars code (``XNYS``, ``COMEX``, ``CMES``, ``NYMEX`` ...): the exchange schedule, including holidays,
  early closes and DST (exchange_calendars stores UTC open/close per session).
``session_of(ts)`` returns (session_date, open_utc, close_utc) for the session containing ts, else None.
Unknown calendar codes raise: callers must not silently guess a calendar.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timezone
from functools import lru_cache


@lru_cache(maxsize=None)
def _schedule(code: str, y0: int, y1: int) -> tuple[list[int], list[int], list[date]]:
    import exchange_calendars as xc
    cal = xc.get_calendar(code, start=f"{max(y0, 2006)}-01-01", end=f"{y1}-12-31")
    s = cal.schedule
    return ([int(t.timestamp()) for t in s["open"]], [int(t.timestamp()) for t in s["close"]], [d.date() for d in s.index])


class TradingCalendar:
    def __init__(self, code: str):
        self.code = code
        if code != "crypto":
            import exchange_calendars as xc
            if code not in xc.get_calendar_names():
                raise ValueError(f"unknown calendar {code!r}")

    def session_of(self, ts: int) -> tuple[date, int, int] | None:
        if self.code == "crypto":
            d = datetime.fromtimestamp(ts, timezone.utc).date()
            o = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
            return d, o, o + 86400
        y = datetime.fromtimestamp(ts, timezone.utc).year
        opens, closes, days = _schedule(self.code, y - 1, y + 1)
        i = bisect_right(opens, ts) - 1
        if i >= 0 and ts < closes[i]:
            return days[i], opens[i], closes[i]
        return None


CALENDAR_FOR_ASSET = {"crypto": "crypto", "equity": "XNYS", "etf": "XNYS", "future": "CMES"}
CALENDAR_FOR_INSTRUMENT = {"GC": "COMEX", "MGC": "COMEX", "SI": "COMEX", "HG": "COMEX", "CL": "NYMEX", "NG": "NYMEX"}


def calendar_for(instrument: str, asset_class: str) -> TradingCalendar:
    code = CALENDAR_FOR_INSTRUMENT.get(instrument) or CALENDAR_FOR_ASSET.get(asset_class)
    if code is None:
        raise ValueError(f"no trading calendar for {instrument} ({asset_class})")
    return TradingCalendar(code)
