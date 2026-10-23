"""Recipe search: valid grid, every trial logged, DSR uses all trials, winner only becomes a CHALLENGER."""
import json

import numpy as np
import pytest

from atlas.models.quant.recipes import (DIMENSIONS, Recipe, grid, register_winner, render_md, search, simulate, synthetic_world,
                                   walk_forward_folds, fold_predictions)
from atlas.models.quant.registry import ModelRegistry


@pytest.fixture(scope="module")
def world():
    return synthetic_world(n_days=520, seed=3)


def test_grid_valid_only():
    g = grid()
    assert all(r.valid() for r in g) and len(set(g)) == len(g)
    assert not any(r.model == "momentum" and r.data != "price" for r in g)
    assert not any(r.text_veto == "on" and "news" not in r.data and r.data != "all" for r in g)
    assert set(DIMENSIONS["model"]) >= {"lgbm", "lgbm_stack", "tsfm"}


def test_world_point_in_time(world):
    # fundamentals and macro are published with a lag: the first row is unknown
    assert world.fund.iloc[0].isna().all() and world.macro.iloc[0].isna().all()


def test_predictions_are_out_of_sample(world):
    folds = walk_forward_folds(world.close.index, n_folds=2)
    p = fold_predictions(world, "lgbm", {"price"}, folds)
    assert len(p) and p.index.get_level_values("date").min() >= folds[0][0]
    assert ((p["meta_p"] >= 0) & (p["meta_p"] <= 1)).all()


def test_simulation_long_only_exposure_capped(world):
    folds = walk_forward_folds(world.close.index, n_folds=2)
    p = fold_predictions(world, "momentum", {"price"}, folds)
    sim = simulate(world, Recipe(), p, None, None)
    r = sim["returns"]
    assert len(r) > 50 and np.isfinite(r).all()
    assert r.max() < 0.2      # exposure <= 1 and vol-targeted: no absurd daily moves


def test_search_logs_every_trial_and_registers_challenger(world, tmp_path):
    res = search(world, n_trials=5, seed=1, out_dir=tmp_path / "r", tsfm_provider="patch-linear")
    assert res["evaluated"] == 5 and res["trial_log_total"] == 5 and res["synthetic"] is True
    lines = (tmp_path / "r" / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 5 and all(json.loads(l)["family"] == "recipe" for l in lines)
    res2 = search(world, n_trials=3, seed=2, out_dir=tmp_path / "r", tsfm_provider="patch-linear")
    assert res2["trial_log_total"] == 8            # multiple-testing penalty accumulates across runs
    md = render_md(res2)
    assert "SYNTHETIC" in md and "does **not** prove" in md
    mid = register_winner(res2, tmp_path / "models")
    reg = ModelRegistry(tmp_path / "models" / "recipe", kind="recipe")
    assert reg.stage(mid) == "challenger" and reg.champion is None      # no auto-promotion
    assert (tmp_path / "models" / "recipe" / mid / "model_card.md").exists()


def test_tsfm_recipe_runs_with_fallback(world, tmp_path):
    res = search(world, n_trials=1, seed=0, out_dir=tmp_path / "t", tsfm_provider="patch-linear",
                 must_include=(Recipe(model="tsfm"),))
    assert any(t["model"] == "tsfm" for t in res["table"])
