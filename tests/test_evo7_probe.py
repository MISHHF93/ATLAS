"""evo7: PDR probe simulator (entries, exits, costs), 15m->1h derivation, context causality."""
import numpy as np

from atlas.features.price_action.bars import Bar
from atlas.ml.dataset import SeriesData, resample_buckets
from atlas.research import reversal_probe as P


def _bars(rows, dur=3600):
    return [Bar(i * dur, dur, o, h, l, c, 10.0) for i, (o, h, l, c) in enumerate(rows)]


FLAT = (100, 100.2, 99.8, 100)


def _sim(rows, entry="stop", exit_="rr2", cost="taker", hold=10):
    return P.simulate(_bars(rows), 0, "long", 100.0, 1.0, P.ProbeConfig(entry, exit_, "none", cost), hold, "crypto")


def test_latency_one_bar_and_stop_entry_target():
    # bar 1 crosses the trigger but is inside the latency window; bar 2 fills; target ref+4 on bar 4
    s = _sim([FLAT, (100, 101, 99.9, 100.5), (100, 100.5, 99.9, 100.2), (100.2, 101, 100, 100.8), (100.8, 104.5, 100.5, 104)])
    assert s is not None and s["filled_at"] == 7200 and s["outcome"] == "target"
    assert abs(s["gross_r"] - 2.0) < 1e-9 and abs(s["cost_r"] - 100 * 24e-4 / 2) < 1e-9


def test_limit_entry_needs_strict_trade_through_and_maker_cost():
    touch = [FLAT, FLAT, (100, 100.1, 99.75, 100), (100, 100.1, 99.75, 100), (100, 100.1, 99.75, 100)]
    assert _sim(touch, entry="limit_0.25") is None              # low == limit: no fill
    s = _sim([FLAT, FLAT, (100, 100.1, 99.7, 100), (100, 104.5, 99.9, 104)], entry="limit_0.25", cost="maker_assumed")
    assert s["fill"] == 99.75 and s["outcome"] == "target"
    assert abs(s["cost_r"] - 99.75 * 4e-4 / s["risk"]) < 1e-9   # 2 bp limit entry + 2 bp limit target


def test_ambiguous_bar_counts_as_stop_and_partial_target():
    s = _sim([FLAT, FLAT, (100, 100.5, 99.9, 100.2), (100.2, 104.5, 97.5, 100)])
    assert s["outcome"] == "stop" and abs(s["gross_r"] + 1.0) < 1e-9
    p = _sim([FLAT, FLAT, (100, 100.5, 99.9, 100.2), (100.2, 102.2, 100, 102), (102, 102.1, 97.5, 98)], exit_="partial_1_2")
    assert abs(p["gross_r"] - (0.5 * 1.0 - 0.5 * 1.0)) < 1e-9


def test_time_stop_exits_at_close():
    s = _sim([FLAT, FLAT, (100, 100.5, 99.9, 100.2)] + [(100.2, 100.6, 99.9, 100.4)] * 8, exit_="rr2_tstop", hold=6)
    assert s["outcome"] == "timeout" and s["exit_at"] == (2 + 3) * 3600


def test_context_uses_completed_days_only():
    bars = _bars([(100 + i * 0.01,) * 4 for i in range(24 * 30)])
    c1 = P.context(bars)
    bars2 = bars[:24 * 25] + [Bar(b.start, b.duration, 1, 1, 1, 1, 10.0) for b in bars[24 * 25:]]
    c2 = P.context(bars2)
    assert np.array_equal(c1["htf"][:24 * 25], c2["htf"][:24 * 25])


def test_grid_counts_and_maker_only_for_crypto():
    assert len(P.grid("crypto")) == 3 * 4 * 5 * 2 and len(P.grid("equity")) == 3 * 4 * 5
    assert all(c.cost == "taker" for c in P.grid("equity"))


def test_resample_15m_to_1h_complete_buckets_only():
    sd = SeriesData("X", "15m", "crypto", [Bar(i * 900, 900, 1, 2, 0.5, 1.5, 1.0) for i in range(7)], ["t"])
    h = resample_buckets(sd, 3600, "1h")
    assert len(h.bars) == 1 and h.bars[0].volume == 4.0 and h.providers[-1] == "derived:15m->1h"
