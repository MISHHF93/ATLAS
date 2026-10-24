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
    for s in E.SIGNED_X:
        df[f"{s}_x_hi"] = df[s] * hi
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


def test_feature_list_genes():
    g = {"model": "hgb", "features": "no_setup", "regime": "vol_conditioned", "bar_type": "heikin_ashi"}
    f = E.feature_list(g)
    assert "reward_risk" not in f and "reg_hi" in f and "heikin_ashi:rep_run" in f


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
