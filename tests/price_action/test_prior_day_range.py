"""prior_day_range_reversal detector. All bars are hand-built SYNTHETIC fixtures (tests only)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.features.price_action import (Bar, Candidate, EngineConfig, PriceActionEngine, PriorDayRangeConfig,
                                         PriorDayRangeReversalDetector)
from atlas.features.price_action.replay import ReplayConfig, replay
from atlas.features.price_action.sessions import US_EQUITY_RTH

M15 = 900
NY = ZoneInfo("America/New_York")


def day_open(d: str) -> int:
    return int(datetime.fromisoformat(f"{d}T09:30").replace(tzinfo=NY).timestamp())


def flat_day(d: str, lo: float, hi: float, n: int = 26) -> list[Bar]:
    """n 15m bars oscillating inside [lo, hi], touching both bounds once."""
    o, mid = day_open(d), (lo + hi) / 2
    out = []
    for i in range(n):
        h, l_ = (hi if i == 3 else mid + 0.3), (lo if i == 10 else mid - 0.3)
        out.append(Bar(o + i * M15, M15, mid, h, l_, mid + (0.1 if i % 2 else -0.1)))
    return out


def long_setup_day(d: str) -> list[Bar]:
    """Session 3: C1 touches range_low (100), C2 green holding C1 low, C3 crosses C2 high, then rallies to 102."""
    o = day_open(d)
    p = [(101.0, 101.2, 100.6, 100.7), (100.7, 100.8, 99.98, 100.2),      # bar 2 = C1 (touches 100)
         (100.2, 100.3, 100.05, 100.1),                                  # red, not C2
         (100.1, 100.6, 100.02, 100.5),                                  # C2: green, low >= C1 low
         (100.5, 100.9, 100.4, 100.8),                                   # C3: crosses C2 high 100.6 (+1 tick)
         (100.8, 101.5, 100.7, 101.4), (101.4, 102.2, 101.3, 102.1)]     # target 102 reached
    p += [(102.1, 102.3, 101.9, 102.0)] * 19
    return [Bar(o + i * M15, M15, *x) for i, x in enumerate(p)]


CFG = PriorDayRangeConfig(touch_atr=0.0, touch_ticks=3, invalidation_atr=0.0, stop_buffer_atr=0.0,
                          opening_extreme_frac=None)
BARS = flat_day("2026-03-02", 97.0, 104.0) + flat_day("2026-03-03", 100.0, 102.0) + long_setup_day("2026-03-04")


def run(bars, cfg=CFG):
    d = PriorDayRangeReversalDetector("X", M15, US_EQUITY_RTH, cfg)
    for b in bars:
        d.step(b, {"atr": 0.5})
    return d


def test_levels_and_long_three_candle_setup():
    d = run(BARS)
    (c,) = d.candidates
    assert c.direction == "long" and c.entry_type == "stop" and c.execution_permission == "none"
    assert c.entry_reference == pytest.approx(100.61)      # C2 high + 1 tick
    assert c.proposed_stop == pytest.approx(99.98)         # min(level 100, C1 low 99.98)
    assert c.proposed_target == 102.0                      # opposite range level
    assert c.features["second_target"] == 104.0            # swing high from the older session
    assert c.features["bars_c1_to_c2"] == 2 and c.features["level_rank"] == 0
    zones = {z.zone_type: z for z in d.zones if z.source_event.endswith("2026-03-04")}
    assert zones["pdr_range_high"].feature_snapshot["level"] == 102.0 and zones["pdr_swing_low"].feature_snapshot["level"] == 97.0
    states = [t.to_state for t in d.transitions if t.setup_id.endswith("pdr1") and "2026-03-04" in t.setup_id]
    assert states == ["WATCHING_LEVELS", "C1_AT_LEVEL", "C2_CONFIRMED", "AWAITING_TRIGGER", "C3_TRIGGERED", "COMPLETED"]


def test_no_trades_without_prior_session_and_shorts_only_at_upper_levels():
    assert run(flat_day("2026-03-03", 100.0, 102.0)).candidates == []
    mirror = [Bar(b.start, b.duration, 200 - b.open, 200 - b.low, 200 - b.high, 200 - b.close) for b in BARS]
    (c,) = run(mirror).candidates
    assert c.direction == "short" and c.proposed_target == pytest.approx(98.0) and c.entry_reference == pytest.approx(99.39)


def test_close_through_level_invalidates():
    bad = BARS[:-26] + [Bar(b.start, b.duration, b.open, b.high, min(b.low, 99.0), min(b.close, 99.2) if i == 2 else b.close)
                        if i == 2 else b for i, b in enumerate(BARS[-26:])]
    d = run(bad)
    assert any(t.reason == "close_through_level" for t in d.transitions)


def test_opening_extreme_variant_uses_first_candle_levels():
    o = day_open("2026-03-04")
    big = [Bar(o, M15, 101.0, 103.0, 99.5, 100.0)] + [Bar(o + i * M15, M15, 100.0, 100.3, 99.7, 100.1) for i in range(1, 26)]
    d = run(BARS[:-26] + big, PriorDayRangeConfig(opening_extreme_frac=0.5, touch_atr=0.0, touch_ticks=3))
    z = [z for z in d.zones if z.source_event.endswith("2026-03-04") and z.zone_type == "pdr_range_high"][0]
    assert z.feature_snapshot == {"level": 103.0, "source": "opening_candle_extreme"}


def test_batch_stream_parity_prefix_invariance_snapshot():
    cfg = EngineConfig(session=US_EQUITY_RTH, pdr=CFG)
    a, b = PriceActionEngine("X", M15, cfg), PriceActionEngine("X", M15, cfg)
    for bar in BARS:
        a.update(bar)
    b.run_batch(BARS)
    key = lambda e: [c.to_dict() for c in e.candidates if c.detector == "prior_day_range_reversal"]
    assert key(a) == key(b) and key(a)
    pre = PriceActionEngine("X", M15, cfg)
    for bar in BARS[:-20]:
        pre.update(bar)
    full = [t for t in a.transitions if t.at <= BARS[-21].end]
    assert [t for t in pre.transitions if t.at <= BARS[-21].end] == full      # no retroactive events
    d1 = run(BARS[:-24]); snap = d1.snapshot()
    d2 = PriorDayRangeReversalDetector("X", M15, US_EQUITY_RTH, CFG); d2.restore(snap)
    for bar in BARS[-24:]:
        d1.step(bar, {"atr": 0.5}); d2.step(bar, {"atr": 0.5})
    assert [c.to_dict() for c in d1.candidates][-1] == [c.to_dict() for c in d2.candidates][-1]


def test_replay_stop_entry_fills_on_cross_and_hits_target():
    res = replay("X", M15, BARS, engine_cfg=EngineConfig(session=US_EQUITY_RTH, pdr=CFG), cfg=ReplayConfig(max_hold_bars=20),
                 data_label="synthetic:test")
    (t,) = [t for t in res.trades if t.detector == "prior_day_range_reversal"]
    assert t.entry_type == "stop" and t.entry == pytest.approx(100.61) and t.outcome == "target"
    assert t.r_multiple == pytest.approx((102.0 - 100.61) / (100.61 - 99.98))
