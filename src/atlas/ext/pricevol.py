"""Session / anchored VWAP and volume profile (POC + value area), high-touch S/R zones and a watchlist breach scan.

Inputs are closed ATLAS bars (atlas.features.price_action.bars.Bar). VWAP math reuses indicators.vwap_batch and
library.anchored_vwap_batch. S/R zones are emitted as the shared ``Zone`` contract so they sit in the same registry
format as every other zone (zone_type "sr_high_touch"). Counts are observed touches, not predictions."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Sequence

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.indicators import atr_batch, vwap_batch
from atlas.features.price_action.library import anchored_vwap_batch, fib_retracements
from atlas.features.price_action.zones import Zone


def _cols(bars: Sequence[Bar]):
    return [b.high for b in bars], [b.low for b in bars], [b.close for b in bars], [b.volume for b in bars]


def utc_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def session_vwap(bars: Sequence[Bar], session_key=None) -> list[float | None]:
    h, l, c, v = _cols(bars)
    keys = [(session_key or (lambda b: utc_day(b.start)))(b) for b in bars]
    return vwap_batch(h, l, c, v, keys)


def anchored_vwap(bars: Sequence[Bar], anchor_ts: int) -> list[float | None]:
    idx = next((i for i, b in enumerate(bars) if b.start >= anchor_ts), None)
    if idx is None:
        return [None] * len(bars)
    h, l, c, v = _cols(bars)
    return anchored_vwap_batch(h, l, c, v, idx)


def volume_profile(bars: Sequence[Bar], bins: int = 40, value_area: float = 0.70) -> dict[str, Any] | None:
    """Spread each bar's volume evenly across the price bins its [low, high] covers. POC = max-volume bin centre;
    value area grows outward from the POC (larger neighbour first) until it holds ``value_area`` of the volume."""
    bars = [b for b in bars if b.volume and b.volume > 0]
    if not bars or bins < 2:
        return None
    lo, hi = min(b.low for b in bars), max(b.high for b in bars)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    vol = [0.0] * bins
    for b in bars:
        a = min(bins - 1, int((b.low - lo) / step)); z = min(bins - 1, int((b.high - lo) / step))
        share = b.volume / (z - a + 1)
        for i in range(a, z + 1):
            vol[i] += share
    total = sum(vol)
    poc = max(range(bins), key=lambda i: vol[i])
    i = j = poc
    acc = vol[poc]
    while acc < value_area * total and (i > 0 or j < bins - 1):
        left = vol[i - 1] if i > 0 else -1.0
        right = vol[j + 1] if j < bins - 1 else -1.0
        if right >= left:
            j += 1; acc += vol[j]
        else:
            i -= 1; acc += vol[i]
    centre = lambda k: lo + (k + 0.5) * step  # noqa: E731
    return {"poc": centre(poc), "vah": lo + (j + 1) * step, "val": lo + i * step, "value_area_pct": acc / total,
            "bins": [{"price": centre(k), "volume": vol[k]} for k in range(bins)], "low": lo, "high": hi, "bars": len(bars),
            "total_volume": total}


def swing_pivots(bars: Sequence[Bar], k: int = 3) -> list[tuple[int, str, float]]:
    """(bar_start, 'high'|'low', price) for k-bar fractal pivots. A pivot at i is only known k bars later."""
    out = []
    for i in range(k, len(bars) - k):
        win = bars[i - k:i + k + 1]
        if bars[i].high == max(b.high for b in win) and sum(1 for b in win if b.high == bars[i].high) == 1:
            out.append((bars[i + k].end, "high", bars[i].high))
        if bars[i].low == min(b.low for b in win) and sum(1 for b in win if b.low == bars[i].low) == 1:
            out.append((bars[i + k].end, "low", bars[i].low))
    return out


def sr_zones(bars: Sequence[Bar], instrument: str, k: int = 3, min_touches: int = 3, atr_mult: float = 0.5,
             max_zones: int = 12) -> list[Zone]:
    """Cluster swing pivots whose prices are within atr_mult * ATR(14). Clusters with >= min_touches become zones."""
    if len(bars) < 2 * k + 15:
        return []
    h, l, c, _ = _cols(bars)
    atrs = [a for a in atr_batch(h, l, c, 14) if a is not None and math.isfinite(a)]
    if not atrs:
        return []
    tol = atr_mult * atrs[-1]
    piv = sorted(swing_pivots(bars, k), key=lambda p: p[2])
    clusters: list[list[tuple[int, str, float]]] = []
    for p in piv:
        if clusters and p[2] - clusters[-1][0][2] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = bars[-1].close
    zones = []
    for cl in clusters:
        if len(cl) < min_touches:
            continue
        times = sorted(t for t, _, _ in cl)
        lo_p, hi_p = min(p for _, _, p in cl), max(p for _, _, p in cl)
        z = Zone(instrument, bars[-1].duration, "sr_high_touch", "bullish" if hi_p < last else "bearish" if lo_p > last else "neutral",
                 lo_p, hi_p, formed_at=times[0], confirmed_at=times[min_touches - 1], touch_count=len(cl),
                 source_event="swing_pivot_cluster",
                 feature_snapshot={"touches": len(cl), "highs": sum(1 for _, s, _ in cl if s == "high"),
                                   "lows": sum(1 for _, s, _ in cl if s == "low"), "tolerance": tol, "last_touch": times[-1],
                                   "role": "support" if hi_p < last else "resistance" if lo_p > last else "inside"})
        zones.append(z)
    zones.sort(key=lambda z: (-z.touch_count, abs(z.midpoint - last)))
    return zones[:max_zones]


def classic_pivots(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3
    return {"P": p, "R1": 2 * p - low, "S1": 2 * p - high, "R2": p + (high - low), "S2": p - (high - low)}


def _cross(prev: float, cur: float, level: float) -> str | None:
    if prev < level <= cur:
        return "up"
    if prev > level >= cur:
        return "down"
    return None


def scan_symbol(symbol: str, bars: Sequence[Bar], daily: Sequence[Bar], swing_lookback: int = 60) -> dict[str, Any]:
    """Breaches on the last closed bar: prior-day classic pivots, Fibonacci retracements of the recent swing and
    high-touch S/R zones. A breach = previous close on one side of the level, last close on the other."""
    if len(bars) < 2:
        return {"symbol": symbol, "status": "no_data", "events": []}
    prev, cur = bars[-2].close, bars[-1].close
    events: list[dict[str, Any]] = []
    levels: dict[str, float] = {}
    done = [d for d in daily if d.end <= bars[-1].start] if daily else []
    if done:
        d = done[-1]
        levels.update({f"pivot_{k}": v for k, v in classic_pivots(d.high, d.low, d.close).items()})
    win = bars[-swing_lookback:]
    sh, sl = max(b.high for b in win), min(b.low for b in win)
    if sh > sl:
        levels.update({f"fib_{f:g}": v for f, v in fib_retracements(sl, sh).items()})
    for name, lv in levels.items():
        d = _cross(prev, cur, lv)
        if d:
            events.append({"type": "pivot" if name.startswith("pivot") else "fib", "level": name, "price": lv, "direction": d})
    zones = sr_zones(bars, symbol)
    for z in zones:
        if prev <= z.upper_bound < cur:
            events.append({"type": "sr_zone", "level": z.zone_id, "price": z.upper_bound, "direction": "up", "touches": z.touch_count})
        elif prev >= z.lower_bound > cur:
            events.append({"type": "sr_zone", "level": z.zone_id, "price": z.lower_bound, "direction": "down", "touches": z.touch_count})
    return {"symbol": symbol, "status": "ok", "last_close": cur, "prev_close": prev, "bar_end": bars[-1].end,
            "levels": levels, "zones": [z.to_dict() for z in zones], "events": events}
