from atlas.features.price_action.bars import Bar
from atlas.features.price_action.replay import ReplayConfig, ReplayTrade, _step_trade, try_fill, weighted_r


def _t():
    return ReplayTrade("c", "sfp_reversal", "long", 0, 100.0, 99.0, 102.0)


def test_latency_blocks_early_fill():
    b = Bar(900, 900, 100.5, 100.6, 99.9, 100.2, 10)
    cfg = ReplayConfig(latency_bars=1)
    assert not try_fill(_t(), b, cfg, age=0)
    assert try_fill(_t(), b, cfg, age=1)


def test_trade_through_requires_strict_cross():
    touch = Bar(900, 900, 100.5, 100.6, 100.0, 100.2, 10)
    assert try_fill(_t(), touch)                                     # default: touch fills
    assert not try_fill(_t(), touch, ReplayConfig(limit_fill="trade_through"))
    assert try_fill(_t(), Bar(900, 900, 100.5, 100.6, 99.9, 100.2, 10), ReplayConfig(limit_fill="trade_through"))


def test_participation_partial_fill_and_zero_volume():
    cfg = ReplayConfig(order_qty=10, max_participation=0.1)
    t = _t()
    assert try_fill(t, Bar(900, 900, 100.5, 100.6, 99.9, 100.2, 40), cfg) and t.fill_ratio == 0.4
    assert not try_fill(_t(), Bar(900, 900, 100.5, 100.6, 99.9, 100.2, 0), cfg)   # unknown volume: no fill
    _step_trade(t, Bar(1800, 900, 100.5, 102.5, 100.4, 102.2, 40), cfg, 1)
    assert t.outcome == "target" and abs(weighted_r(t) - 0.4 * t.r_multiple) < 1e-12


def test_ambiguous_bar_resolves_to_stop():
    t = _t()
    assert try_fill(t, Bar(900, 900, 100.5, 100.6, 99.9, 100.2, 10))
    _step_trade(t, Bar(1800, 900, 100.5, 102.5, 98.5, 101.0, 10), ReplayConfig(), 1)
    assert t.outcome == "stop" and t.ambiguous
