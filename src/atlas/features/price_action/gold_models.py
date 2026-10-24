"""Gold session models (mandate §11). Gold-only: callers must pass ``is_gold(instrument)``.

Windows are America/New_York, configurable; default opening box 08:20–08:50 (transcript), premarket 08:00–08:05.
Every function takes only bars whose end <= ``now`` (causal) and returns ``None``/INSUFFICIENT_DATA when the
window is not fully covered by bars of a duration that tiles it exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from atlas.features.price_action.bars import EPS, Bar
from atlas.features.price_action.library import midpoint, overlap_ratio, range_overlap
from atlas.features.price_action.suite import is_gold

NY = ZoneInfo("America/New_York")


@dataclass
class GoldSessionConfig:
    asian: tuple[str, str] = ("18:00", "03:00")
    early: tuple[str, str] = ("04:00", "07:00")
    premarket_orb: tuple[str, str] = ("08:00", "08:05")
    opening_orb: tuple[str, str] = ("08:20", "08:50")
    pre_open_consolidation: tuple[str, str] = ("07:30", "08:20")
    tight_range_atr: float = 1.0


def _ts(day: datetime, hhmm: str, prev_day: bool = False) -> int:
    h, m = map(int, hhmm.split(":"))
    d = day.date() - timedelta(days=1) if prev_day else day.date()
    return int(datetime.combine(d, time(h, m), NY).timestamp())


def window_range(bars: Sequence[Bar], start: int, end: int, now: int) -> dict | None:
    if now < end:
        return None
    w = [b for b in bars if b.start >= start and b.end <= end and b.end <= now]
    if not w or (end - start) % w[0].duration or len(w) != (end - start) // w[0].duration:
        return None  # INSUFFICIENT_DATA: window not exactly tiled
    hi, lo = max(b.high for b in w), min(b.low for b in w)
    return {"high": hi, "low": lo, "mid": midpoint(hi, lo), "height": hi - lo, "open": w[0].open,
            "close": w[-1].close, "volume": sum(b.volume for b in w), "start": start, "end": end, "n": len(w)}


def session_day_ranges(instrument: str, bars: Sequence[Bar], day_ny: datetime, now: int,
                       cfg: GoldSessionConfig | None = None, atr: float | None = None) -> dict:
    if not is_gold(instrument):
        return {"status": "NOT_APPLICABLE", "reason": "gold-only model"}
    cfg = cfg or GoldSessionConfig()
    a0, a1 = cfg.asian
    asian = window_range(bars, _ts(day_ny, a0, prev_day=True), _ts(day_ny, a1), now)
    early = window_range(bars, _ts(day_ny, cfg.early[0]), _ts(day_ny, cfg.early[1]), now)
    pre = window_range(bars, _ts(day_ny, cfg.premarket_orb[0]), _ts(day_ny, cfg.premarket_orb[1]), now)
    opn = window_range(bars, _ts(day_ny, cfg.opening_orb[0]), _ts(day_ny, cfg.opening_orb[1]), now)
    cons = window_range(bars, _ts(day_ny, cfg.pre_open_consolidation[0]), _ts(day_ny, cfg.pre_open_consolidation[1]), now)
    out: dict = {"status": "OK", "asian": asian, "early": early, "premarket_orb": pre, "opening_orb": opn}
    if asian and atr:
        out["asian_context"] = {"range_atr": asian["height"] / max(atr, EPS),
                                "return": asian["close"] / asian["open"] - 1.0,
                                "travel_atr": abs(asian["close"] - asian["open"]) / max(atr, EPS)}
    if early and atr:
        mv = early["close"] - early["open"]
        out["early_bird"] = {"direction": "bullish" if mv > 0 else "bearish" if mv < 0 else "flat",
                             "move_atr": mv / max(atr, EPS), "extended": abs(mv) / max(atr, EPS) > 2.0,
                             "volume": early["volume"]}
    if cons and atr:
        out["range_bound_to_open"] = {"height_atr": cons["height"] / max(atr, EPS),
                                      "tight": cons["height"] / max(atr, EPS) <= cfg.tight_range_atr,
                                      "high": cons["high"], "low": cons["low"]}
    if pre and opn:
        out["orb_alignment"] = orb_alignment(pre, opn)
    missing = [k for k in ("asian", "early", "premarket_orb", "opening_orb") if out[k] is None]
    if missing:
        out["insufficient"] = missing
    return out


def orb_alignment(a: dict, b: dict) -> dict:
    ov = range_overlap(a["high"], a["low"], b["high"], b["low"])
    return {"overlap": ov, "overlap_ratio": overlap_ratio(a["high"], a["low"], b["high"], b["low"]),
            "midpoint_distance": b["mid"] - a["mid"],
            "relative_width": b["height"] / max(a["height"], EPS),
            "shared_resistance": abs(a["high"] - b["high"]) <= 0.1 * max(a["height"], b["height"], EPS),
            "shared_support": abs(a["low"] - b["low"]) <= 0.1 * max(a["height"], b["height"], EPS)}
