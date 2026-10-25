"""evo8 strict champion gate: min trades/fold, majority of folds, DSR + Bonferroni over trials; demotion via regate."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from atlas.ml import evolution as E
from atlas.research import champion_robustness as R


def _m(fold_taken, fold_ev, beats=True):
    return {"beats_baseline": beats, "folds": [{"fold": i, "n_taken": n, "ev": e, "n_test": 300} for i, (n, e) in enumerate(zip(fold_taken, fold_ev))]}


def test_gate_rejects_432dba_like_profile():
    # evo7 champion shape: 127/2/11/4/275 trades, edge almost all in the last fold, 36 trials
    rng = np.random.default_rng(0)
    taken = rng.normal(0.07, 1.3, 419)
    srs = list(rng.normal(0, 0.08, 36))
    g = E.strict_gate(_m([127, 2, 11, 4, 275], [-0.035, 0.007, 0.008, 0.005, 0.108]), taken, srs)
    assert not g["passed"] and "min_trades_per_fold" in g["failed"]
    assert g["values"]["n_trials"] == 36


def test_gate_requires_strict_majority_and_all_folds():
    taken = np.full(500, 0.5) + np.random.default_rng(1).normal(0, 0.1, 500)
    srs = [0.0, 0.01, -0.01]
    assert not E.strict_gate(_m([100] * 5, [0.1, 0.1, -0.1, -0.1, -0.1]), taken, srs)["checks"]["majority_folds_positive"]
    assert not E.strict_gate(_m([100] * 4, [0.1] * 4), taken, srs)["checks"]["all_folds_evaluated"]
    ok = E.strict_gate(_m([100] * 5, [0.1, 0.1, 0.1, -0.1, 0.1]), taken, srs)
    assert ok["passed"], ok


def test_more_trials_is_stricter():
    rng = np.random.default_rng(2)
    taken = rng.normal(0.12, 1.0, 400)
    few = E.strict_gate(_m([80] * 5, [0.1] * 5), taken, [0.0, 0.01])
    many = E.strict_gate(_m([80] * 5, [0.1] * 5), taken, list(rng.normal(0, 0.1, 200)))
    assert many["values"]["bonferroni_p"] >= few["values"]["bonferroni_p"]
    assert many["values"]["dsr"] <= few["values"]["dsr"]


def test_record_never_crowns_without_strict_pass(tmp_path):
    chal = {"genome_id": "x", "genome": {}, "generation": 0, "parent": None, "mutation": "seed", "metrics": {"fitness": 1.0, "beats_baseline": True,
                                                       "strict_gate": {"passed": False, "failed": ["dsr"]}}}
    res = {"leaderboard": [chal], "best_beating_baseline": chal, "best_passing_strict_gate": None, "data": {"data_hash": "h"},
           "seed": 1, "generations": 1, "no_model_beats_baseline": False, "by_bar_type": {}}
    run = E.record(res, path=tmp_path, now=1)
    assert run["decision"] == "no_challenger_passes_strict_gate" and E.champion(tmp_path) is None
    assert run["promoted_to_execution"] is False and run["execution_permission"] == "none"


def test_regate_demotes_failing_champion(tmp_path, monkeypatch):
    d = E.evo_dir(tmp_path); d.mkdir(parents=True)
    g = {"model": "logit", "features": "full", "regime": "none", "bar_type": "time", "context": "none"}
    gid = E.gid(g)
    run = {"run_id": "r1", "data": {"data_hash": None}, "folds": [{}] * 5,
           "best_beating_baseline": {"genome_id": gid}, "leaderboard": [{"genome_id": gid, "genome": g, "metrics": {"status": "ok", "fitness": 0.1}}]}
    (d / "champion.json").write_text(json.dumps({"genome_id": gid, "run_id": "r1", "metrics": {}}))
    monkeypatch.setattr(E, "folds", lambda data, n=5: [])
    monkeypatch.setattr(E, "evaluate_genome", lambda data, gg, fs: {**_m([2, 50, 50, 50, 50], [0.1] * 5), "status": "ok",
                                                                    "fitness": 0.1, "_taken_r": np.full(10, 0.1)})
    out = E.regate(run, pd.DataFrame(), path=tmp_path, now=5)
    assert out["decision"] == "champion_demoted_to_research_only" and "min_trades_per_fold" in out["reason"]
    assert E.champion(tmp_path) is None and (d / "demoted_r1.json").exists()


def test_block_bootstrap_and_stability():
    x = np.r_[np.full(50, 1.0), np.full(50, -1.0)]
    ci = R.block_bootstrap_ci(x, block=10, n_boot=500)
    assert ci["lo"] <= 0 <= ci["hi"] and ci["spans_zero"]
    assert R.block_bootstrap_ci([1.0], n_boot=10)["status"] == "insufficient"
    oos = pd.DataFrame({"t": np.arange(8) * 86400 * 20, "instrument": ["BTCUSDT", "SOLUSDT"] * 4, "r": [1, -1, 1, 2, -1, 1, 1, 1.0],
                        "p": 0.5, "take": [True, True, False, True, True, True, False, True], "fold": [0, 0, 1, 1, 2, 2, 3, 3]})
    st = R.stability(oos)
    assert {g["key"] for g in st["by_group"]} == {"btc_eth", "alts"} and st["symbols_with_trades"] == 2
