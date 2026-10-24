"""evo6: ATR-scaled stop / cost-filter variants, 4h derivation, research registry variants and retirement."""
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.replay import ReplayConfig, ReplayTrade, apply_variant, trade_cost
from atlas.features.price_action.strategies import BY_ID, RESEARCH_RETIRED, StrategyRegistry
from atlas.ml.dataset import SeriesData, resample_4h
from atlas.research import setup_variants as SV


def _t(entry=100.0, stop=99.0, target=102.0, d="long"):
    return ReplayTrade("c", "wick_reversal", d, 0, entry, stop, target)


def test_atr_stop_and_target_rescaled_long_short():
    cfg = ReplayConfig(stop_atr_mult=2.0, target_rr=1.5)
    t = _t()
    assert apply_variant(t, 1.0, cfg) and t.stop == 98.0 and t.target == 103.0
    s = _t(stop=101.0, target=98.0, d="short")
    assert apply_variant(s, 1.0, cfg) and s.stop == 102.0 and s.target == 97.0


def test_default_rr_keeps_detector_ratio_and_no_atr_skips():
    t = _t()
    assert apply_variant(t, 0.5, ReplayConfig(stop_atr_mult=2.0)) and abs((t.target - t.entry) / (t.entry - t.stop) - 2.0) < 1e-12
    u = _t()
    assert not apply_variant(u, None, ReplayConfig(stop_atr_mult=2.0)) and u.outcome == "no_atr"


def test_cost_filter_skips_expensive_setups_only():
    cfg = ReplayConfig(cost_bps=24.0, max_cost_r=0.15)    # cost 0.24 on entry 100
    tight = _t(stop=99.0)                                   # cost/R 0.24 -> skip
    wide = _t(stop=97.0, target=106.0)                      # cost/R 0.08 -> keep
    assert not apply_variant(tight, None, cfg) and tight.outcome == "cost_skipped"
    assert apply_variant(wide, None, cfg) and trade_cost(wide, cfg) / 3.0 < 0.15


def test_variant_defaults_leave_replay_config_unchanged():
    c = ReplayConfig()
    assert c.stop_atr_mult is None and c.target_rr is None and c.max_cost_r is None


def test_resample_4h_complete_buckets_only():
    bars = [Bar(14400 + i * 3600, 3600, 1 + i, 2 + i, 0.5 + i, 1.5 + i, 1.0) for i in range(6)]   # 1 full bucket + 2 bars
    out = resample_4h(SeriesData("X", "1h", "crypto", bars)).bars
    assert len(out) == 1 and out[0].start == 14400 and out[0].duration == 14400
    assert out[0].open == 1 and out[0].close == 4.5 and out[0].high == 5 and out[0].low == 0.5 and out[0].volume == 4


def test_research_variants_are_off_toggleable_and_not_live(tmp_path):
    r = StrategyRegistry(tmp_path / "s.json")
    sid = "prior_day_range_reversal__atr2_rr2"
    assert BY_ID[sid].status == "research" and BY_ID[sid].variant in SV.VARIANT_BY_ID and not r.enabled(sid)
    before = r.enabled_detectors()
    r.set(sid, True)
    assert StrategyRegistry(tmp_path / "s.json").enabled(sid) and r.enabled_detectors() == before
    for s in ("dual_band_breakout", "wick_reversal", "orb_retest", "prior_day_range_reversal"):
        assert BY_ID[s].default_enabled and BY_ID[s].status == "implemented"   # legacy specs unchanged


def test_orb_retest_15m_research_retired_reversible(tmp_path):
    r = StrategyRegistry(tmp_path / "s.json")
    assert ("orb_retest", "15m") in RESEARCH_RETIRED and r.retired("orb_retest", "15m") and not r.retired("orb_retest", "1h")
    assert "orb_retest" not in r.enabled_detectors("15m") and "orb_retest" in r.enabled_detectors("1h")
    assert "orb_retest" in r.enabled_detectors()           # interval-agnostic callers unchanged
    r.set_retired("orb_retest", "15m", False)
    assert not StrategyRegistry(tmp_path / "s.json").retired("orb_retest", "15m")
    assert all(x["execution_permission"] == "none" for x in r.listing())


def test_summarize_reports_gross_and_net():
    rows = [{"r": -0.5, "gross_r": -0.4, "cost_r": 0.1}] * 5 + [{"r": 1.0, "gross_r": 1.1, "cost_r": 0.1}] * 5
    s = SV.summarize(rows)
    assert s["n"] == 10 and s["net_r"] == 0.25 and s["gross_r"] == 0.35 and s["net_ci95"][0] <= 0.25 <= s["net_ci95"][1]
