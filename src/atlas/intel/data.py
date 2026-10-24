"""Shared bar loading + freshness for intel modules (reuses the feed store and quant freshness labels)."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from atlas.features.price_action.bars import Bar

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}

# instrument: (calendar, tick, cost_per_unit, cost_bps, hold_bars)  -- same research assumptions as run_level_research
SPEC = {"GC": ("COMEX", 0.1, 0.25, 0.0, 96), "MGC": ("COMEX", 0.1, 0.35, 0.0, 96), "SI": ("COMEX", 0.005, 0.015, 0.0, 96),
        "ES": ("CMES", 0.25, 0.6, 0.0, 96), "BTCUSDT": ("crypto", 0.01, 0.0, 24.0, 96), "ETHUSDT": ("crypto", 0.01, 0.0, 24.0, 96),
        "SPY": ("XNYS", 0.01, 0.01, 4.0, 26)}


def load_bars(feed, inst: str, iv: str = "15m") -> list[Bar]:
    dur = TF_SECONDS[iv]
    out, last = [], None
    if feed is None:
        return out
    for b in feed.bars(inst, iv):
        if last is not None and b.event_time <= last:
            continue
        try:
            out.append(Bar(int(b.event_time), dur, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = b.event_time
    return out


def bars_hash(bars: list[Bar]) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b.start},{b.open},{b.high},{b.low},{b.close},{b.volume};".encode())
    return h.hexdigest()


def freshness_for(bars: list[Bar], origin: Any = "atlas_feed") -> dict[str, Any]:
    from atlas.api.quant import freshness
    last_end = (bars[-1].start + bars[-1].duration) if bars else None
    return freshness(last_end, int(time.time()), bars[-1].duration if bars else 60, origin)


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
