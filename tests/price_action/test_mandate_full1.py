import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from atlas.features.price_action import library as L
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.gold_models import orb_alignment, session_day_ranges
from atlas.features.price_action.structure import StructureConfig, analyze_structure


def test_sma_ema_warmup_and_values():
    x = [1, 2, 3, 4, 5.0]
    assert L.sma_batch(x, 3) == [None, None, 2.0, 3.0, 4.0]


def test_macd_constant_series_is_zero():
    m, s, h = L.macd_batch([10.0] * 60)
    assert abs(m[-1]) < 1e-12 and abs(s[-1]) < 1e-12 and abs(h[-1]) < 1e-12


def test_adx_strong_uptrend_plus_di_dominates():
    n = 60
    h = [i + 1.0 for i in range(n)]; l = [i + 0.0 for i in range(n)]; c = [i + 0.9 for i in range(n)]
    p, m, a = L.adx_batch(h, l, c, 14)
    assert p[-1] > m[-1] and a[-1] > 50 and a[26] is None and a[27] is not None


def test_roc_logret_realized_vol():
    x = [100 * math.exp(0.01 * i) for i in range(30)]
    assert L.log_returns(x)[5] == pytest.approx(0.01)
    assert L.realized_vol_batch(x, 20)[-1] == pytest.approx(0.0, abs=1e-12)
    assert L.roc_batch([100, 110], 1)[1] == pytest.approx(10.0)


def test_rvol_excludes_current_bar_and_donchian():
    v = [10.0] * 20 + [30.0]
    assert L.rvol_batch(v, 20)[-1] == pytest.approx(3.0)
    assert L.donchian_batch([1, 3, 2], [0, 1, 1], 2)[2] == (3, 1, 2.0)


def test_avwap_and_anatomy():
    out = L.anchored_vwap_batch([2, 4], [0, 2], [1, 3], [1, 3], 0)
    assert out[1] == pytest.approx((1 * 1 + 3 * 3) / 4)
    a = L.candle_anatomy(10, 12, 9, 11)
    assert a["upper_wick"] == 1 and a["lower_wick"] == 1 and a["body"] == 1
    assert L.engulfing((10, 10.5, 9, 9.5), (9.4, 11, 9.3, 10.6)) == "bullish"


def test_overlap_and_distance():
    assert L.range_overlap(10, 5, 8, 6) == 2
    assert L.overlap_ratio(10, 5, 8, 6) == pytest.approx(1.0)
    assert L.overlap_ratio(1, 0, 3, 2) == 0
    assert L.normalized_distance(105, 100, 2.5) == 2.0 and L.normalized_distance(1, 1, None) is None


def test_ev_breakeven_sizing_consistency():
    g, l_, c = 2.0, 1.0, 0.1
    pbe = L.breakeven_probability(g, l_, c)
    assert L.expected_value(pbe, g, l_, c) == pytest.approx(0.0, abs=1e-12)
    assert L.position_quantity(1000, 5, 100) == 2 and L.position_quantity(1000, 0, 100) == 0


def test_microstructure_gating_and_kyle():
    assert L.trade_imbalance(None, 1, 2) is None
    assert L.order_book_imbalance(3, 1) == pytest.approx(0.5)
    rng = np.random.default_rng(0); q = rng.normal(size=500)
    dp = 0.3 * q + rng.normal(scale=0.01, size=500)
    assert L.kyle_lambda(dp, q)["lambda"] == pytest.approx(0.3, abs=0.01)
    assert L.kyle_lambda([1] * 5, [1] * 5) is None
    assert L.hawkes_intensity(1.0, [0.0, 2.0], 0.5, 1.0, 1.0) == pytest.approx(0.5 + math.exp(-1))
    assert L.vpin([1] * 50, [1] * 50) == 0


def test_risk_metrics():
    r = np.linspace(-0.05, 0.05, 101)
    v = L.historical_var_es(r, 0.95)
    assert v["var"] > 0 and v["cvar"] >= v["var"]
    mu, var = L.portfolio_mean_var([0.5, 0.5], [0.1, 0.2], [[0.04, 0], [0, 0.09]])
    assert mu == pytest.approx(0.15) and var == pytest.approx(0.0325)
    assert L.brier([1, 0], [1, 0]) == 0 and L.log_loss([0.5], [1]) == pytest.approx(math.log(2))
    s = L.implementation_shortfall(1, 100, [(5, 101)], 10, 102)
    assert s["execution"] == 5 and s["opportunity"] == 10


def test_htf_mapping_no_leakage():
    # HTF bars end at 300, 600; LTF ends at 100..700
    out = L.htf_context_for_ltf([100, 300, 400, 600, 700], [300, 600], ["a", "b"])
    assert out == [None, "a", "a", "b", "b"]


def _bars(prices, dur=60):
    return [Bar(i * dur, dur, p, p + 0.5, p - 0.5, p) for i, p in enumerate(prices)]


def test_structure_swings_are_causal_and_bos():
    px = [1, 2, 3, 5, 3, 2, 1, 2, 3, 4, 6, 7, 6, 5]
    bars = _bars(px)
    ev = analyze_structure(bars, "GC", StructureConfig(left=2, right=2, atr_n=3, compression_n=50))
    sh = [e for e in ev if e.kind == "SWING_HIGH"][0]
    assert sh.event_ts == 3 * 60 and sh.confirmation_ts == bars[5].end  # not known until 2 bars later
    assert any(e.kind in ("BOS", "CHOCH") and e.direction == "bullish" for e in ev)
    # truncating the future must not change past events
    ev2 = analyze_structure(bars[:8], "GC", StructureConfig(left=2, right=2, atr_n=3, compression_n=50))
    past = [e for e in ev if e.confirmation_ts <= bars[7].end]
    assert [e.event_id for e in ev2] == [e.event_id for e in past]


NY = ZoneInfo("America/New_York")


def test_gold_models_gold_only_and_alignment():
    day = datetime(2026, 10, 20, tzinfo=NY)
    assert session_day_ranges("ES", [], day, 0)["status"] == "NOT_APPLICABLE"
    t0 = int(datetime(2026, 10, 20, 8, 0, tzinfo=NY).timestamp())
    bars = [Bar(t0 + 60 * i, 60, 100 + 0.01 * i, 100.5 + 0.01 * i, 99.5 + 0.01 * i, 100 + 0.01 * i) for i in range(60)]
    early = session_day_ranges("GC", bars, day, t0 + 60 * 30)
    assert early["opening_orb"] is None  # 08:50 not yet reached -> not available
    r = session_day_ranges("GC", bars, day, t0 + 3600)
    assert r["premarket_orb"]["n"] == 5 and r["opening_orb"]["n"] == 30
    assert "orb_alignment" in r and r["orb_alignment"]["overlap"] > 0
    a = orb_alignment({"high": 2, "low": 0, "mid": 1, "height": 2}, {"high": 3, "low": 1, "mid": 2, "height": 2})
    assert a["overlap_ratio"] == 0.5


def test_gold_15m_bars_cannot_build_0820_box():
    day = datetime(2026, 10, 20, tzinfo=NY)
    t0 = int(datetime(2026, 10, 20, 8, 0, tzinfo=NY).timestamp())
    bars = [Bar(t0 + 900 * i, 900, 100, 101, 99, 100) for i in range(8)]
    r = session_day_ranges("GC", bars, day, t0 + 7200)
    assert r["opening_orb"] is None and "opening_orb" in r["insufficient"]


def test_window_gap_tolerance_reports_coverage():
    from atlas.features.price_action.gold_models import window_range
    bars = [Bar(60 * i, 60, 1, 2, 0.5, 1) for i in range(100) if i not in (10, 20, 30)]
    assert window_range(bars, 0, 6000, 6000) is None
    r = window_range(bars, 0, 6000, 6000, max_missing_frac=0.05)
    assert r["n"] == 97 and r["coverage"] == pytest.approx(0.97)
