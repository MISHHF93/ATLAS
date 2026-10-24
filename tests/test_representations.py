import math
import random

from atlas.features.price_action.bars import Bar
from atlas.features.representations import availability, build, heikin_ashi, renko, rep_features, threshold_bars


def _bars(n=3000, seed=1, vol=True):
    rnd = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        o = p
        c = max(1.0, o + rnd.gauss(0, 0.3))
        h, l = max(o, c) + abs(rnd.gauss(0, 0.1)), min(o, c) - abs(rnd.gauss(0, 0.1))
        out.append(Bar(1_700_000_000 + i * 900, 900, o, h, l, c, rnd.uniform(10, 100) if vol else 0.0))
        p = c
    return out


def test_heikin_ashi_formula():
    b = _bars(5)
    ha = heikin_ashi(b)
    assert math.isclose(ha[0].close, (b[0].open + b[0].high + b[0].low + b[0].close) / 4)
    assert math.isclose(ha[1].open, (ha[0].open + ha[0].close) / 2)
    assert all(h.high >= max(h.open, h.close) and h.low <= min(h.open, h.close) for h in ha)


def test_renko_fixed_brick_sizes_and_reversal():
    closes = [100, 100.4, 101.1, 102.05, 101.5, 100.9, 99.9]
    b = [Bar(i * 60, 60, c, c, c, c, 1) for i, c in enumerate(closes)]
    r = renko(b, 1.0)
    assert [x.direction for x in r] == [1, 1, -1]
    assert all(math.isclose(abs(x.close - x.open), 1.0) for x in r)


def test_no_lookahead_prefix_invariance():
    """Every builder: alt bars completed by time T are identical whether or not later data exists."""
    full = _bars(3000)
    cut = full[:2000]
    T = cut[-1].end
    for kind in ("heikin_ashi", "renko_atr", "range_atr", "volume", "dollar"):
        a = [x for x in build(kind, full) if x.completed_at <= T]
        b = build(kind, cut)
        assert a == b, kind
        assert all(x.completed_at <= T for x in b)
        f_full, f_cut = rep_features(full, kind), rep_features(cut, kind)
        assert f_full.loc[f_cut.index].equals(f_cut), kind


def test_threshold_bars_gated_without_volume_and_tick_unavailable():
    b = _bars(3000, vol=False)
    assert threshold_bars(b, "volume") == []
    av = availability(b)
    assert not av["volume"]["available"] and not av["tick"]["available"]
    assert build("tick", b) == []


def test_volume_bars_warmup_then_bars():
    b = _bars(3000)
    v = build("volume", b)
    assert v and v[0].start >= (b[0].start // 86400 + 20) * 86400


def test_lab_gold_alignment_flags_15m():
    from atlas.intel.lab import gold_alignment
    assert not gold_alignment(900)["aligned"]
    assert gold_alignment(60)["aligned"]
    assert gold_alignment(300)["aligned"]


def test_daily_bar_not_live_on_weekend():
    from atlas.api.quant import freshness
    fri_close = 1792872000            # a daily bar end; read ~28h later
    assert freshness(fri_close, fri_close + 28 * 3600, 86400, "atlas_feed")["label"] == "historical"
    assert freshness(fri_close, fri_close + 2 * 3600, 86400, "atlas_feed")["label"] == "delayed"
    assert freshness(fri_close, fri_close + 60, 60, "atlas_feed")["label"] == "live"
