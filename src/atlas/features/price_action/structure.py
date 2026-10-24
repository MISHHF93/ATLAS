"""Universal causal market-structure engine (mandate §7).

Swing at bar i is confirmed only when ``right`` further bars have closed: confirmation_ts = end of bar i+right.
Emits event records: SWING_HIGH/LOW (labelled HH/LH/HL/LL), BOS, CHOCH, RANGE_COMPRESSION/EXPANSION,
BREAKOUT_SUCCESS/BREAKOUT_FAILED. All decisions use only bars <= the current bar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from atlas.features.price_action.bars import EPS, Bar
from atlas.features.price_action.indicators import atr_batch


@dataclass(frozen=True)
class StructureEvent:
    event_id: str
    instrument: str
    timeframe: int
    kind: str
    direction: str
    event_ts: int
    confirmation_ts: int
    reference_price: float
    quality: dict[str, float] = field(default_factory=dict)
    source_candles: tuple[int, ...] = ()
    invalidation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructureConfig:
    left: int = 2
    right: int = 2
    atr_n: int = 14
    compression_n: int = 20
    compression_ratio: float = 0.6
    expansion_ratio: float = 1.8
    breakout_hold_bars: int = 3


def analyze_structure(bars: Sequence[Bar], instrument: str, cfg: StructureConfig | None = None) -> list[StructureEvent]:
    cfg = cfg or StructureConfig()
    tf = bars[0].duration if bars else 0
    H = [b.high for b in bars]; L = [b.low for b in bars]; C = [b.close for b in bars]
    atr = atr_batch(H, L, C, cfg.atr_n)
    ev: list[StructureEvent] = []
    last_hi = last_lo = None  # (idx, price)
    trend = 0  # +1 up, -1 down
    broken_hi = broken_lo = None
    pending_break: list[tuple[int, str, float]] = []
    regime = "normal"

    def mk(kind, d, i_evt, i_conf, px, q=None, src=(), inv=""):
        ev.append(StructureEvent(f"{instrument}:{tf}:{kind}:{bars[i_evt].start}:{bars[i_conf].end}", instrument, tf,
                                 kind, d, bars[i_evt].start, bars[i_conf].end, float(px), q or {},
                                 tuple(bars[k].start for k in src), inv))

    for t in range(len(bars)):
        i = t - cfg.right  # candidate swing confirmed at t
        if i - cfg.left >= 0:
            win = range(i - cfg.left, t + 1)
            if all(H[i] > H[k] for k in win if k != i):
                lab = "HH" if last_hi and H[i] > last_hi[1] else ("LH" if last_hi else "SH")
                mk("SWING_HIGH", lab, i, t, H[i], src=tuple(win), inv=f"close>{H[i]}")
                last_hi = (i, H[i]); broken_hi = None
            if all(L[i] < L[k] for k in win if k != i):
                lab = "LL" if last_lo and L[i] < last_lo[1] else ("HL" if last_lo else "SL")
                mk("SWING_LOW", lab, i, t, L[i], src=tuple(win), inv=f"close<{L[i]}")
                last_lo = (i, L[i]); broken_lo = None
        a = atr[t]
        if last_hi and broken_hi is None and C[t] > last_hi[1] and t > last_hi[0] + cfg.right:
            kind = "BOS" if trend >= 0 else "CHOCH"
            mk(kind, "bullish", t, t, last_hi[1], {"close_beyond_atr": (C[t] - last_hi[1]) / max(a or EPS, EPS)},
               (last_hi[0], t), f"close<{last_lo[1] if last_lo else L[t]}")
            trend = 1; broken_hi = t; pending_break.append((t, "bullish", last_hi[1]))
        if last_lo and broken_lo is None and C[t] < last_lo[1] and t > last_lo[0] + cfg.right:
            kind = "BOS" if trend <= 0 else "CHOCH"
            mk(kind, "bearish", t, t, last_lo[1], {"close_beyond_atr": (last_lo[1] - C[t]) / max(a or EPS, EPS)},
               (last_lo[0], t), f"close>{last_hi[1] if last_hi else H[t]}")
            trend = -1; broken_lo = t; pending_break.append((t, "bearish", last_lo[1]))
        for pb in list(pending_break):
            j, d, lvl = pb
            failed = (C[t] < lvl) if d == "bullish" else (C[t] > lvl)
            if t > j and failed:
                mk("BREAKOUT_FAILED", d, j, t, lvl, src=(j, t)); pending_break.remove(pb)
            elif t - j >= cfg.breakout_hold_bars:
                mk("BREAKOUT_SUCCESS", d, j, t, lvl, src=(j, t)); pending_break.remove(pb)
        n = cfg.compression_n
        if t >= n and a:
            rng = max(H[t - n + 1:t + 1]) - min(L[t - n + 1:t + 1])
            per_bar = (H[t] - L[t]) / max(a, EPS)
            new = "compression" if rng / max(a * n ** 0.5, EPS) < cfg.compression_ratio else (
                "expansion" if per_bar > cfg.expansion_ratio else "normal")
            if new != regime and new != "normal":
                mk("RANGE_" + new.upper(), "neutral", t, t, C[t], {"range_atr": rng / a, "bar_range_atr": per_bar})
            regime = new
    return ev
