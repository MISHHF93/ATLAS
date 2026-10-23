"""Item 6: square-root pre-trade impact, Almgren-Chriss, crypto POV, arrival-price slippage."""
import numpy as np
import pytest

from atlas.execution.scheduling import (POV_HARD_MAX, SlippageMonitor, almgren_chriss, arrival_slippage_bps,
                                             pov_schedule, pre_trade_impact_bps)


def test_square_root_impact_and_haircuts():
    a = pre_trade_impact_bps(1000, 100000, 0.02, 10, venue="TSX")
    b = pre_trade_impact_bps(4000, 100000, 0.02, 10, venue="TSX")
    assert np.isclose(b["impact_bps"], 2 * a["impact_bps"])           # 4x size -> 2x impact
    assert pre_trade_impact_bps(1000, 100000, 0.02, 10, venue="TSXV")["impact_bps"] > a["impact_bps"]
    assert pre_trade_impact_bps(10, 0, 0.02, 10)["total_bps"] == float("inf")


def test_almgren_chriss_conserves_and_front_loads_with_risk_aversion():
    twap = almgren_chriss(10000, 5, 10, 0.02, eta=1e-3, risk_aversion=0.0, price=50)
    urgent = almgren_chriss(10000, 5, 10, 0.02, eta=1e-3, risk_aversion=1e-4, price=50)
    for s in (twap, urgent):
        assert np.isclose(s["trades"].sum(), 10000) and (s["trades"] >= -1e-9).all()
    assert np.allclose(twap["trades"], 1000)
    assert urgent["trades"][0] > urgent["trades"][-1] and urgent["variance"] < twap["variance"]
    assert urgent["expected_cost"] > twap["expected_cost"]


def test_pov_caps_participation_and_never_forces():
    plan = pov_schedule(1000, [2000] * 3, participation=0.5)
    assert plan.participation == POV_HARD_MAX and all(c <= 200 + 1e-9 for c in plan.children)
    assert np.isclose(sum(plan.children) + plan.unfilled, 1000) and plan.unfilled == 400
    sell = pov_schedule(-50, [10000] * 5, 0.05)
    assert sum(sell.children) == -50 and sell.unfilled == 0


def test_arrival_slippage_and_monitor():
    r = arrival_slippage_bps("buy", 100.0, [(50, 100.10), (50, 100.30)], fees=1.0)
    assert np.isclose(r["slippage_bps"], 20) and np.isclose(r["fees_bps"], 1.0)
    s = arrival_slippage_bps("sell", 100.0, [(100, 99.9)])
    assert np.isclose(s["slippage_bps"], 10)
    part = arrival_slippage_bps("buy", 100.0, [(50, 100.0)], intended_qty=100, close_price=102.0)
    assert np.isclose(part["opportunity_bps"], 100)
    m = SlippageMonitor(); m.record("X", 10, r)
    assert m.summary()["underestimate_ratio"] > 2
