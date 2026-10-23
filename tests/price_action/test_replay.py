"""Replay harness: live path + conservative OHLC fill model. Hand-built bars only (synthetic)."""
from __future__ import annotations

import random

import pytest

from atlas.features.price_action import Bar, EngineConfig, PriceActionEngine
from atlas.features.price_action.replay import ReplayConfig, ReplayTrade, _step_trade, outcome_labels, replay
from atlas.features.price_action.sessions import US_EQUITY_RTH
from tests.price_action.test_price_action import O, _orb_long_bars


def B(t, o, h, l, c):
    return Bar(t, 3600, o, h, l, c, 1.0)


def _t(direction="long"):
    return ReplayTrade("c", "x", direction, 0, 100.0, 98.0, 104.0, filled_at=0, outcome="open")


def test_both_touched_counts_as_stop():
    t = _t(); _step_trade(t, B(3600, 100, 105, 97, 101), ReplayConfig(), 1)
    assert t.outcome == "stop" and t.ambiguous and t.r_multiple == pytest.approx(-1.0)


def test_gap_through_stop_takes_open_and_gap_through_target_capped():
    t = _t(); _step_trade(t, B(3600, 96, 97, 95, 96), ReplayConfig(), 1)
    assert t.outcome == "stop" and t.exit_price == 96 and t.r_multiple == pytest.approx(-2.0)
    t = _t(); _step_trade(t, B(3600, 110, 111, 109, 110), ReplayConfig(), 1)
    assert t.outcome == "target" and t.exit_price == 104 and t.r_multiple == pytest.approx(2.0)


def test_fill_bar_ignores_target_but_honours_stop():
    t = _t(); _step_trade(t, B(0, 101, 106, 99, 105), ReplayConfig(), 0)
    assert t.outcome == "open"
    t = _t(); _step_trade(t, B(0, 101, 106, 97, 105), ReplayConfig(), 0)
    assert t.outcome == "stop" and t.ambiguous


def test_short_mirror_timeout_and_costs():
    t = ReplayTrade("c", "x", "short", 0, 100.0, 102.0, 96.0, filled_at=0, outcome="open")
    _step_trade(t, B(3600, 100, 101, 95, 99), ReplayConfig(cost_per_unit=0.5), 1)
    assert t.outcome == "target" and t.r_multiple == pytest.approx((4 - 0.5) / 2)
    t = _t(); _step_trade(t, B(3600, 100, 101, 99, 100.5), ReplayConfig(max_hold_bars=1), 1)
    assert t.outcome == "timeout" and t.r_multiple == pytest.approx(0.25)


def test_replay_uses_live_path_and_matches_batch_candidates():
    rng = random.Random(11)
    bars, px, t0 = [], 100.0, O
    for i in range(400):
        o = px; c = o + rng.gauss(0, 1); h = max(o, c) + rng.random(); l = min(o, c) - rng.random()
        bars.append(B(t0 + i * 3600, o, h, l, c)); px = c
    cfg = EngineConfig(session=US_EQUITY_RTH)
    res = replay("SYN", 3600, bars, engine_cfg=cfg, data_label="synthetic_fixture")
    ref = PriceActionEngine("SYN", 3600, cfg); ref.run_batch(bars)
    assert [c.candidate_id for c in res.candidates] == [c.candidate_id for c in ref.candidates]
    assert res.summary["candidates"] == len(ref.candidates) and res.data_label == "synthetic_fixture"
    for tr in res.trades:   # no fill on the detection bar; fills happen strictly later
        assert tr.filled_at is None or tr.filled_at >= tr.detected_at  # detected_at = bar_end of the signal bar
    assert all(lbl in (0, 1) for _, lbl in outcome_labels(res))
    assert res.to_dict()["execution_permission"] == "none"


def test_replay_orb_fixture_end_to_end():
    bars = _orb_long_bars() + [B(O + 3 * 3600, 103.2, 103.5, 102.5, 103.1), B(O + 4 * 3600, 103.1, 107.5, 103.0, 107.2)]
    res = replay("SPY", 3600, bars, engine_cfg=EngineConfig(session=US_EQUITY_RTH), data_label="synthetic_fixture")
    orb = [t for t in res.trades if t.detector.startswith("orb")]
    assert orb and orb[0].outcome == "target" and orb[0].r_multiple == pytest.approx(2.0)
