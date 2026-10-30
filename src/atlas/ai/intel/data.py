"""Shared bar loading + freshness for intel modules (reuses the feed store and quant freshness labels)."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from atlas.features.price_action.bars import Bar

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}

# instrument: (calendar, tick, cost_per_unit, cost_bps, hold_bars).
# Futures rows are DERIVED from atlas.feeds.contracts (the single contract-spec source); only non-futures
# research assumptions live here.
_NON_FUTURES = {"BTCUSDT": ("crypto", 0.01, 0.0, 124.0, 96), "ETHUSDT": ("crypto", 0.01, 0.0, 124.0, 96),
                "SPY": ("XNYS", 0.01, 0.01, 4.0, 26)}


def _build_spec() -> dict[str, tuple]:
    from atlas.feeds.contracts import default_contracts
    fut = {k: (c.suite_calendar, c.tick_size, c.cost_price_units, 0.0, c.hold_bars) for k, c in default_contracts().items()}
    return {**fut, **_NON_FUTURES}


SPEC = _build_spec()


def load_bars(feed, inst: str, iv: str = "15m", max_bars: int = 3500) -> list[Bar]:
    dur = TF_SECONDS[iv]
    out, last = [], None
    if feed is None:
        return out
    raw = list(feed.bars(inst, iv))
    if max_bars and len(raw) > max_bars:
        raw = raw[-max_bars:]
    for b in raw:
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
