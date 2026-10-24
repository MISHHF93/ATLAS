"""StrategyBacktester paper realism (pass 10): latency, trade-through and volume-capped partial fills."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from atlas.features.price_action.replay import ReplayConfig
from atlas.research.backtester import StrategyBacktester

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def _df(rows):
    return pd.DataFrame([{"timestamp": T0 + timedelta(minutes=5 * (i + 1)), "open": o, "high": h, "low": l,
                          "close": c, "volume": v} for i, (o, h, l, c, v) in enumerate(rows)])


def bt(realism="default"):
    return StrategyBacktester(None, None) if realism == "default" else StrategyBacktester(None, None, realism=realism)


def test_default_is_paper_realism_and_legacy_is_opt_in():
    assert bt().realism.latency_bars == 1 and bt().realism.limit_fill == "trade_through"
    assert bt(None).realism is None


def test_touch_only_target_wins_legacy_but_not_realistic():
    # long entry 100, stop 98, target 103; bar 1 trades through entry, later bar only touches 103
    df = _df([(100.2, 100.5, 99.9, 100.1, 50), (100.1, 103.0, 100.0, 102.5, 50), (102.5, 102.6, 97.5, 98, 50)])
    legacy = bt(None)._simulate_trade(df, 100.0, 98.0, 103.0, T0)
    real = bt()._simulate_realistic(df, 100.0, 98.0, 103.0, T0)
    assert legacy.outcome == "win" and real.outcome == "loss"


def test_no_trade_through_means_no_fill():
    df = _df([(100.5, 101, 100.0, 100.8, 50), (100.8, 104, 100.0, 103.5, 50)])   # low touches 100 but never < 100
    b = bt()
    assert b._simulate_realistic(df, 100.0, 98.0, 103.0, T0) is None and b.unfilled == 1


def test_zero_volume_bar_does_not_fill_and_partial_fill_scales_pnl():
    zero = _df([(100.2, 100.5, 99.5, 100, 0), (100, 100.2, 99.9, 100, 0), (100, 100.1, 99.9, 100, 0)])
    assert bt()._simulate_realistic(zero, 100.0, 98.0, 103.0, T0) is None
    rows = [(100.2, 100.5, 99.5, 100, 5), (100, 103.5, 99.9, 103, 5)]           # 10% of 5 = 0.5 of a 1-unit order
    half = bt()._simulate_realistic(_df(rows), 100.0, 98.0, 103.0, T0)
    full = StrategyBacktester(None, None, realism=ReplayConfig(latency_bars=1, limit_fill="trade_through"))\
        ._simulate_realistic(_df(rows), 100.0, 98.0, 103.0, T0)
    assert half.fill_ratio == 0.5 and full.fill_ratio == 1.0 and abs(half.pnl_bps - full.pnl_bps / 2) < 1e-9


def test_latency_skips_the_detection_bar_window_and_costs_reduce_pnl():
    rows = [(100, 100.4, 99.0, 100, 50), (100, 103.5, 100.1, 103, 50)]          # only bar 0 trades through
    assert StrategyBacktester(None, None, realism=ReplayConfig(latency_bars=2, entry_window=1,
                              limit_fill="trade_through"))._simulate_realistic(_df(rows), 100.0, 98.0, 103.0, T0) is None
    gross = StrategyBacktester(None, None, realism=ReplayConfig(latency_bars=1))._simulate_realistic(_df(rows), 100.0, 98.0, 103.0, T0)
    net = StrategyBacktester(None, None, realism=ReplayConfig(latency_bars=1, cost_bps=5))._simulate_realistic(_df(rows), 100.0, 98.0, 103.0, T0)
    assert abs((gross.pnl_bps - net.pnl_bps) - 5.0) < 1e-9


def test_snapback_setup_is_mutable_so_the_backtest_path_runs():
    from atlas.strategies.snapback import SnapbackSetup, SnapbackState
    s = SnapbackSetup(symbol="ES", setup_id="x", initial_box=None)
    s.state = SnapbackState.QUALIFIED
    assert s.state is SnapbackState.QUALIFIED and s.execution_permission == "none"


def test_contract_terms_single_source():
    from atlas.feeds.contracts import CONTRACT_TERMS
    from atlas.feeds.universe import FUTURES
    from atlas.feeds.instruments import _ES_TICK, _ES_MULT
    assert (_ES_TICK, _ES_MULT) == CONTRACT_TERMS["ES"]
    flat = repr(FUTURES)
    for tick, mult in CONTRACT_TERMS.values():
        assert repr(mult) in flat
