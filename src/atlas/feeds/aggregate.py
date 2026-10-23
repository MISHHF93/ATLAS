"""Aggregate confirmed lower-timeframe bars (e.g. Alpaca 1m stream) into 15m/1h. A higher bar is confirmed only when
its bar_end has passed and all constituent minutes are confirmed."""
from __future__ import annotations

from .core import INTERVALS, FeedBar


def aggregate(bars: list[FeedBar], target: str, now: int, anchor: int = 0, require_complete: bool = False) -> list[FeedBar]:
    step = INTERVALS[target]
    groups: dict[int, list[FeedBar]] = {}
    for b in sorted(bars, key=lambda x: x.event_time):
        groups.setdefault((b.event_time - anchor) // step * step + anchor, []).append(b)
    out = []
    src = INTERVALS[bars[0].interval] if bars else 60
    for t, g in sorted(groups.items()):
        complete = len(g) == step // src
        conf = t + step <= now and all(x.confirmed for x in g) and (complete or not require_complete)
        out.append(FeedBar(g[0].instrument, target, t, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close,
                           sum(x.volume for x in g), g[0].provider, max(x.receipt_time for x in g), conf, g[0].provider_symbol))
    return out
