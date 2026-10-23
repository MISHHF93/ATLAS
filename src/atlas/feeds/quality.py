"""Gap detection, freshness and cross-provider sanity -> quality flags consumed by predict() abstention."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .core import INTERVALS, FeedBar

FLAG_STALE = "stale"
FLAG_GAP = "gap"
FLAG_UNCONFIRMED = "unconfirmed_last_bar"
FLAG_DISAGREE = "provider_disagreement"
FLAG_EMPTY = "no_data"
FLAG_INVALID = "invalid_bar"
FLAG_OFF_GRID = "off_grid_bar"


def _rth_open(t: int) -> int:
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    d = datetime.fromtimestamp(t, ny)
    return int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=ny).timestamp())


def on_grid(t: int, session: str, interval: str) -> bool:
    """True if a bar start sits on the session's bar grid (RTH intraday bars anchor at 09:30 ET; others at UTC multiples)."""
    step = INTERVALS[interval]
    if step >= 86400:
        return True
    if session == "us_equity_rth":
        return (t - _rth_open(t)) % step == 0
    return t % step == 0


def expected_starts(session: str, interval: str, start: int, end: int) -> list[int]:
    """Bar starts the session calendar says must exist in [start, end)."""
    step = INTERVALS[interval]
    t0 = (start + step - 1) // step * step
    if session == "24x7":
        return list(range(t0, end, step))
    if session == "us_equity_rth":
        from zoneinfo import ZoneInfo
        from atlas.marketdata.pit.calendars import session_close, sessions
        ny = ZoneInfo("America/New_York")
        d0 = datetime.fromtimestamp(start, timezone.utc).date()
        d1 = datetime.fromtimestamp(end, timezone.utc).date()
        out = []
        for d in sessions("XNYS", d0, d1):
            op = int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=ny).timestamp())
            cl = int(session_close("XNYS", d).timestamp())   # handles half days
            full_day = cl - op >= 6.5 * 3600
            # early-close days: providers omit a bar that would straddle the close (e.g. 12:30 1h bar on 13:00 close)
            out += [t for t in range(op, cl, step) if start <= t < end and (full_day or t + step <= cl)]
        return out
    if session == "fx_24x5":
        return [t for t in range(t0, end, step) if datetime.fromtimestamp(t, timezone.utc).weekday() < 5 or
                (datetime.fromtimestamp(t, timezone.utc).weekday() == 6 and datetime.fromtimestamp(t, timezone.utc).hour >= 22)]
    return list(range(t0, end, step))


def find_gaps(bars: list[FeedBar], session: str, interval: str, start: int, end: int) -> list[tuple[int, int]]:
    have = {b.event_time for b in bars}
    missing = [t for t in expected_starts(session, interval, start, end) if t not in have]
    step, gaps = INTERVALS[interval], []
    for t in missing:
        if gaps and t - gaps[-1][1] <= step * 4 and session == "24x7":
            gaps[-1] = (gaps[-1][0], t + step)
        elif gaps and gaps[-1][1] == t:
            gaps[-1] = (gaps[-1][0], t + step)
        else:
            gaps.append((t, t + step))
    return gaps


@dataclass
class Quality:
    instrument: str
    interval: str
    as_of: int
    last_bar_end: int | None
    age_seconds: int | None
    gaps: list = field(default_factory=list)
    flags: tuple = ()
    disagreement_bps: float | None = None

    def ok(self) -> bool:
        return not self.flags


def assess(bars: list[FeedBar], session: str, interval: str, now: int, lookback_bars: int = 200,
           max_age_seconds: int | None = None, cross: list[FeedBar] | None = None, tolerance_bps: float = 50.0) -> Quality:
    step = INTERVALS[interval]
    inst = bars[-1].instrument if bars else "?"
    flags = []
    if not bars:
        return Quality(inst, interval, now, None, None, [], (FLAG_EMPTY,))
    last_end = bars[-1].bar_end
    # freshness: the most recent bar the calendar expects must be present
    win_start = now - lookback_bars * step
    exp = expected_starts(session, interval, max(win_start, bars[0].event_time), now - step + 1)
    expected_last_end = (exp[-1] + step) if exp else last_end
    age = now - last_end
    limit = max_age_seconds if max_age_seconds is not None else 2 * step
    if expected_last_end - last_end > 0 and age > limit:
        flags.append(FLAG_STALE)
    gaps = find_gaps([b for b in bars if b.event_time >= win_start], session, interval, max(win_start, bars[0].event_time), last_end)
    if gaps:
        flags.append(FLAG_GAP)
    if not bars[-1].confirmed:
        flags.append(FLAG_UNCONFIRMED)
    if any(not b.valid() for b in bars[-lookback_bars:]):
        flags.append(FLAG_INVALID)
    if any(not on_grid(b.event_time, session, interval) for b in bars[-lookback_bars:]):
        flags.append(FLAG_OFF_GRID)
    dis = None
    if cross:
        ref = {b.event_time: b.close for b in cross}
        diffs = [abs(b.close / ref[b.event_time] - 1) * 1e4 for b in bars[-lookback_bars:] if b.event_time in ref and ref[b.event_time] > 0]
        if diffs:
            diffs.sort()
            dis = diffs[len(diffs) // 2]
            if dis > tolerance_bps or diffs[-1] > tolerance_bps * 10:
                flags.append(FLAG_DISAGREE)
    return Quality(inst, interval, now, last_end, age, gaps, tuple(flags), dis)
