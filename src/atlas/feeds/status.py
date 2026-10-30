"""Quote status classification: live / delayed / market_closed / stale / no_data.

The market-hours calendar is the exchange_calendars XNYS calendar (US holidays and early closes included) via
``atlas.marketdata.pit.calendars``; a small built-in NYSE holiday table is the fallback when that package is missing.
CME Globex: Sun 18:00 -> Fri 17:00 ET with the daily 17:00-18:00 ET maintenance break (CME holiday schedule not
modelled: on a CME holiday the series shows ``stale``, never a fake ``live``). Crypto is 24x7; FX is 24x5.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

try:
    import exchange_calendars as _xc  # noqa: F401
    from atlas.marketdata.pit import calendars as _pit_calendars
    _HAS_XC = True
except ImportError:
    _pit_calendars = None  # type: ignore[assignment]
    _HAS_XC = False

NY = ZoneInfo("America/New_York")
TORONTO = ZoneInfo("America/Toronto")

LIVE = "live"
DELAYED = "delayed"
MARKET_CLOSED = "market_closed"
STALE = "stale"
NO_DATA = "no_data"
STATUSES = (LIVE, DELAYED, MARKET_CLOSED, STALE, NO_DATA)

# Providers whose prints are exchange real-time (websocket/trade feeds). Everything else is labelled delayed when open.
REALTIME_PROVIDERS = {"coinbase", "kraken", "alpaca", "polygon", "databento", "ibkr", "questrade"}
# Live-tolerance per session: a print older than this while the market is open is no longer "live".
LIVE_MAX_AGE = {"24x7": 120, "us_equity_rth": 120, "cme_globex": 180, "fx_24x5": 180}
# A delayed source (Yahoo ~ up to 15-20 min for some venues) becomes stale past this while open.
DELAYED_MAX_AGE = 30 * 60

# Fallback NYSE full-day holidays 2025-2027 (used only when exchange_calendars is unavailable).
_NYSE_HOLIDAYS = {date(*d) for d in (
    (2025, 1, 1), (2025, 1, 9), (2025, 1, 20), (2025, 2, 17), (2025, 4, 18), (2025, 5, 26), (2025, 6, 19), (2025, 7, 4),
    (2025, 9, 1), (2025, 11, 27), (2025, 12, 25), (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3), (2026, 5, 25),
    (2026, 6, 19), (2026, 7, 3), (2026, 9, 7), (2026, 11, 26), (2026, 12, 25), (2027, 1, 1), (2027, 1, 18), (2027, 2, 15),
    (2027, 3, 26), (2027, 5, 31), (2027, 6, 18), (2027, 7, 5), (2027, 9, 6), (2027, 11, 25), (2027, 12, 24))}


def _utc(t: float) -> datetime:
    return datetime.fromtimestamp(t, timezone.utc)


@lru_cache(maxsize=512)
def _nyse_open_min(t_min: int) -> bool:
    t = float(t_min * 60)
    if _HAS_XC and _pit_calendars is not None:
        return _pit_calendars.is_open("XNYS", _utc(t))
    ny = _utc(t).astimezone(NY)
    return ny.weekday() < 5 and ny.date() not in _NYSE_HOLIDAYS and time(9, 30) <= ny.time() < time(16, 0)


def nyse_open(t: float) -> bool:
    return _nyse_open_min(int(t) // 60)


@lru_cache(maxsize=512)
def _last_nyse_close_min(t_min: int) -> float:
    t = float(t_min * 60)
    d = _utc(t).astimezone(NY).date()
    if _HAS_XC and _pit_calendars is not None:
        for back in range(0, 15):
            day = d - timedelta(days=back)
            ss = _pit_calendars.sessions("XNYS", day, day)
            if ss:
                c = _pit_calendars.session_close("XNYS", ss[0]).timestamp()
                if c <= t:
                    return c
    else:
        for back in range(0, 15):
            day = d - timedelta(days=back)
            if day.weekday() < 5 and day not in _NYSE_HOLIDAYS:
                c = datetime.combine(day, time(16, 0), NY).timestamp()
                if c <= t:
                    return c
    return t - 3 * 86400


def last_nyse_close(t: float) -> float:
    """Epoch of the most recent XNYS session close at or before ``t`` (early closes honoured)."""
    return _last_nyse_close_min(int(t) // 60)


def globex_open(t: float) -> bool:
    ny = _utc(t).astimezone(NY)
    wd, hm = ny.weekday(), ny.time()
    if wd == 5:
        return False
    if wd == 6:
        return hm >= time(18, 0)
    if wd == 4 and hm >= time(17, 0):
        return False
    return not (time(17, 0) <= hm < time(18, 0))


def fx_open(t: float) -> bool:
    ny = _utc(t).astimezone(NY)
    wd, hm = ny.weekday(), ny.time()
    return not (wd == 5 or (wd == 6 and hm < time(17, 0)) or (wd == 4 and hm >= time(17, 0)))


def market_open(session: str, t: float) -> bool:
    if session == "24x7":
        return True
    if session == "us_equity_rth":
        return nyse_open(t)
    if session == "cme_globex":
        return globex_open(t)
    if session == "fx_24x5":
        return fx_open(t)
    return False


def last_session_end(session: str, t: float) -> float:
    """When the market last closed (for a closed market): the last price should be at or after this minus a bar."""
    if session == "us_equity_rth":
        return last_nyse_close(t)
    step = 60
    x = int(t) // step * step
    for _ in range(4 * 24 * 60):  # walk back minute by minute (bounded to 4 days: covers weekends)
        if market_open(session, x - 1):
            return float(x)
        x -= step
    return t - 4 * 86400


def classify(session: str, provider: str | None, price_time: float | None, now: float, interval_s: int = 60) -> str:
    """Status of the latest print for an instrument. Never returns ``live`` for a print that is old or from a closed
    market; never invents a price (``no_data`` when there is none)."""
    if not price_time or not provider:
        return NO_DATA
    age = now - price_time
    if market_open(session, now):
        realtime = provider in REALTIME_PROVIDERS
        if realtime and age <= max(LIVE_MAX_AGE.get(session, 120), 2 * interval_s):
            return LIVE
        if not realtime and age <= DELAYED_MAX_AGE:
            return DELAYED
        return STALE
    # Closed: OK if we hold a print from (around) the last session close; else the last session is missing -> stale.
    closed_at = last_session_end(session, now)
    tolerance = max(30 * 60, 2 * interval_s)
    return MARKET_CLOSED if price_time >= closed_at - tolerance else STALE


def toronto(t: float | None) -> str | None:
    if not t:
        return None
    return _utc(t).astimezone(TORONTO).strftime("%Y-%m-%d %H:%M:%S %Z")
