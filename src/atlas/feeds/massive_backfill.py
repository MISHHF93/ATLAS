"""Throttled, resumable stock/ETF backfill from Massive (Stocks Basic) into the feed store.

Every request goes through the adapter's shared 4-calls-per-minute limiter and its on-disk response cache. Each run asks only for
the tail the store is missing, so a re-run after a crash or the next day costs a couple of calls per ticker. The key is read by the
adapter from the environment; nothing here sees or prints it.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Callable, Iterable

from .aggregate import aggregate
from .core import INTERVALS
from .providers.polygon import et_midnight

PRIORITY = ("AAPL", "SPY", "QQQ", "GLD", "NVDA", "MSFT", "TSM", "AVGO", "MU", "CRWD",
            "ROK", "CEG", "OKLO", "VST", "RKLB", "SOFI", "ENPH")
PROVIDER = "polygon"
WINDOW_DAYS = {"1d": 725, "15m": 725}      # the free plan keeps 2 years


def _missing_weekdays(last_bar_end: int, end: int) -> int:
    """Weekdays (New York dates) after the day of the last stored bar and before ``end`` (a midnight ET).
    Holidays are not modelled: a holiday costs one empty call."""
    from .providers.polygon import NY
    d = dt.datetime.fromtimestamp(last_bar_end - 1, NY).date() + dt.timedelta(days=1)
    stop = dt.datetime.fromtimestamp(end + 3600, NY).date()
    n = 0
    while d < stop:
        n += d.weekday() < 5
        d += dt.timedelta(days=1)
    return n


def plan_window(last_bar_end: int | None, now: float, interval: str, days: int | None = None) -> tuple[int, int] | None:
    """(start, end) still missing, or None when the store is already up to the last completed ET day."""
    end = et_midnight(now)
    floor = end - (days or WINDOW_DAYS[interval]) * 86400
    start = max(floor, last_bar_end) if last_bar_end else floor
    if start >= end or (last_bar_end and _missing_weekdays(last_bar_end, end) == 0):
        return None
    return int(start), int(end)


def materialize_1h(feed, instrument: str, now: float) -> int:
    """Store 1h bars built from the stored 15m regular-session bars (half-hour anchored, like the chart fallback)."""
    bars15 = feed.store.bars(instrument, "15m", provider=PROVIDER)
    if not bars15:
        return 0
    have = feed.store.bars(instrument, "1h", provider=PROVIDER)
    cutoff = have[-1].event_time if have else 0
    agg = [b for b in aggregate(bars15, "1h", int(now), anchor=1800) if b.confirmed and b.event_time >= cutoff]
    return feed.store.ingest(agg, note="1h from stored 15m")["inserted"] if agg else 0


def jobs(feed, instruments: Iterable[str], phases: str = "ABC") -> list[tuple[str, str]]:
    ids = list(instruments)
    pri = [i for i in PRIORITY if i in ids]
    rest = [i for i in ids if i not in pri]
    out: list[tuple[str, str]] = []
    if "A" in phases:
        out += [(i, iv) for i in pri for iv in ("1d", "15m")]
    if "B" in phases:
        out += [(i, "1d") for i in rest]
    if "C" in phases:
        out += [(i, "15m") for i in rest]
    return out


def run(feed, instruments: Iterable[str], phases: str = "ABC", now: float | None = None, days: int | None = None,
        emit: Callable[[dict], None] = lambda r: None, make_1h: bool = True) -> list[dict]:
    now = time.time() if now is None else now
    results = []
    for inst, iv in jobs(feed, instruments, phases):
        a = feed.registry.get(PROVIDER)
        before = a._health.requests if a else 0
        last = feed.store.bars(inst, iv, provider=PROVIDER)
        win = plan_window(last[-1].bar_end if last else None, now, iv, days)
        row = {"instrument": inst, "interval": iv, "had": len(last)}
        if win is None:
            row.update(status="up_to_date", inserted=0)
        else:
            prov, res = feed.fetch(inst, iv, win[0], win[1], providers=[PROVIDER])
            row.update(status="ok" if prov else "no_data", inserted=res.get("inserted", 0), errors=res.get("errors") or None)
        if iv == "15m" and make_1h and (row["status"] in ("ok", "up_to_date")):
            row["inserted_1h"] = materialize_1h(feed, inst, now)
        row["calls"] = (a._health.requests - before) if a else 0
        allb = feed.store.bars(inst, iv, provider=PROVIDER)
        row["bars"] = len(allb)
        row["first"] = dt.datetime.fromtimestamp(allb[0].event_time, dt.timezone.utc).strftime("%Y-%m-%d") if allb else None
        row["last"] = dt.datetime.fromtimestamp(allb[-1].event_time, dt.timezone.utc).strftime("%Y-%m-%d") if allb else None
        results.append(row)
        emit(row)
    return results
