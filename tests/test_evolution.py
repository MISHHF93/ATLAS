import numpy as np
import pandas as pd

from atlas.ml import evolution as E
from atlas.ml.dataset import FEATURES


def _data(n=1200, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 3600 + 1_700_000_000
    df = pd.DataFrame({c: rng.normal(size=n) for c in FEATURES})
    df["rv_pctile_480"] = rng.uniform(size=n)
    df["t"], df["exit_at"] = t, t + 1800
    df["y"] = (rng.uniform(size=n) < 0.4).astype(int)
    df["r"] = np.where(df.y == 1, 1.5, -1.0)
    df["detector"], df["instrument"], df["candidate_id"] = "orb_retest", "X", [f"c{i}" for i in range(n)]
    hi = (df.rv_pctile_480 >= 2 / 3).astype(float)
    df["reg_hi"], df["reg_lo"] = hi, (df.rv_pctile_480 <= 1 / 3).astype(float)
    tr_w = (df.trend_sign * np.where(df.dir_long > 0, 1.0, -1.0) > 0).astype(float)
    df["reg_trend_with"], df["reg_trend_counter"] = tr_w, 1.0 - tr_w
    for s in E.SIGNED_X:
        df[f"{s}_x_hi"] = df[s] * hi
        df[f"{s}_x_trend"] = df[s] * tr_w
    for c in E.REP_FEATURES:
        df[f"renko_atr:{c}"] = rng.normal(size=n)
    return df


def test_noise_population_does_not_beat_baseline_and_records_lineage(tmp_path):
    d = _data()
    seeds = [{"model": "logit", "features": "full", "regime": "none", "bar_type": "time"},
             {"model": "hgb", "features": "bar_only", "regime": "vol_conditioned", "bar_type": "renko_atr"},
             {"model": "ridge", "features": "full", "regime": "none", "bar_type": "volume"}]   # volume cols absent -> unavailable
    res = E.evolve(d, {"data_hash": "x"}, generations=2, seeds=seeds, log=lambda s: None, top_k=1, children_per_parent=1)
    st = {v["genome_id"]: v["metrics"]["status"] for v in res["leaderboard"]}
    assert st[E.gid(seeds[2])] == "unavailable"
    ok = [v for v in res["leaderboard"] if v["metrics"]["status"] == "ok"]
    assert all(v["metrics"]["n_oos"] == ok[0]["metrics"]["n_oos"] for v in ok)      # same folds for every genome
    assert any(v["generation"] == 1 and v["parent"] for v in res["leaderboard"])
    run = E.record(res, path=tmp_path)
    assert run["promoted_to_execution"] is False and run["execution_permission"] == "none"
    assert (tmp_path / "evolution" / "lineage.jsonl").exists()


def test_mutate_stays_inside_the_bar_types_that_were_built():
    import random
    g = {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time", "context": "none"}
    space = {**E.GENES, "bar_type": ("time",)}
    rng = random.Random(0)
    for _ in range(40):
        child, mut = E.mutate(g, rng, space)
        assert child["bar_type"] == "time"
        assert not mut.startswith("bar_type")
    same, note = E.mutate(g, rng, {k: (g[k],) for k in E.GENES})
    assert note == "none" and same["model"] == "hgb"


def test_feature_list_genes():
    g = {"model": "hgb", "features": "no_setup", "regime": "vol_conditioned", "bar_type": "heikin_ashi"}
    f = E.feature_list(g)
    assert "reward_risk" not in f and "reg_hi" in f and "heikin_ashi:rep_run" in f
    gt = {"model": "hgb", "features": "full", "regime": "trend_conditioned", "bar_type": "time"}
    ft = E.feature_list(gt)
    assert "reg_trend_with" in ft and "reg_trend_counter" in ft and f"{E.SIGNED_X[0]}_x_trend" in ft
    gd = {"model": "logit", "features": "no_setup", "regime": "daily_trend", "bar_type": "time", "context": "macro"}
    fd = E.feature_list(gd)
    assert "reg_d1_with" in fd and "reg_d1_counter" in fd and f"{E.SIGNED_X[0]}_x_d1" in fd
    assert "m_vix" in fd and "reward_risk" not in fd


def test_markers_causal_anchor_and_never_ml_authorized():
    from types import SimpleNamespace as N
    from atlas.intel.markers import from_replay
    c = N(candidate_id="c1", detector="sfp_reversal", instrument="GC", direction="long", detected_at=1800, entry_reference=100.0,
          invalidation_level=99.0, proposed_stop=99.0, proposed_target=102.0, zone={}, features={"x": 1.0})
    res = N(candidates=[c], trades=[])
    m = from_replay(res, 900)[0]
    assert m["time"] == 900 and m["outcome"] == "not_filled"
    assert m["probability"] is None and m["probability_label"].startswith("uncalibrated")
    assert m["risk_status"].startswith(("rejected", "gate abstained")) and "authorized" not in m["risk_status"]


def test_marker_class_summary_marks_inapplicable_categories():
    from atlas.intel.markers import class_summary
    ms = [{"class": "rule_only", "source": "candidate_engine"}] * 3
    cs = class_summary(ms, 3, has_oos=False)
    assert cs["rule_only"] == {**cs["rule_only"], "count": 3, "applicable": True}
    assert cs["risk_rejected"]["count"] == 0 and "out of 3" in cs["risk_rejected"]["note"]
    assert not cs["ml_suggested"]["applicable"] and not cs["ml_skip"]["applicable"]
    assert not class_summary([], 0, False)["risk_rejected"]["applicable"]


def test_rule_only_risk_status_is_not_called_a_rejection():
    import inspect
    from atlas.intel import markers
    src = inspect.getsource(markers.from_replay)
    assert '"rule_only", "rejected' not in src and "not a risk rejection" in src


def test_official_book_uses_the_cost_capped_higher_timeframe():
    assert E.OFFICIAL_VARIANT == "atr2_rr2_cf15"
    assert E.UNIVERSE_OFFICIAL == [(i, "4h") for i in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    assert "daily_trend" in E.GENES["regime"]
    assert E.EVO6_DETECTORS == ("prior_day_range_reversal",)
    assert E.MIN_TRADES_PER_FOLD == 20 and E.DSR_MIN == 0.95 and E.BONFERRONI_ALPHA == 0.05
    assert any(s.get("features") == "no_signed" and s.get("context") == "macro" for s in E.LIVE_SEEDS)
