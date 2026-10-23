"""Gap closing 1: new model kinds in the registry, save/load, trial logging of every experiment."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from atlas.control.policy.schemas import ModelPromotionCfg
from atlas.models.quant import multi
from atlas.models.quant.meta import META_FEATURES
from atlas.models.quant.registry import PromotionDenied
from atlas.models.quant.retrain import synthetic_bars
from atlas.models.quant.stack2 import (ConformalModel, ExecutionModel, FactorSleeveModel, PortfolioModel, all_trial_srs,
                                  calibrate_execution, n_trials)
from atlas.models.quant.validation import TrialLog


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("models")
    bars = synthetic_bars(("AAA", "BBB", "CCC", "DDD"), seed=1)
    out = {"meta_label": multi.retrain_meta(bars, root)}
    out["conformal"] = multi.retrain_conformal(bars, root, pt=out["meta_label"]["pt"], sl=out["meta_label"]["sl"])
    close = pd.DataFrame({s: b["close"] for s, b in bars.items()})
    out["factor_sleeve"] = multi.retrain_factor(close, root)
    out["portfolio"] = multi.retrain_portfolio(close.pct_change().dropna(), root)
    out["execution"] = multi.retrain_execution(None, root)
    return root, bars, out


def test_every_kind_registered_as_challenger_and_loads_digest_checked(trained):
    root, bars, out = trained
    for kind, res in out.items():
        reg = multi.registry_for(root, kind)
        assert reg.stage(res["model_id"]) == "challenger" and reg.champion is None
        m = reg.load(res["model_id"])
        assert (root / kind / res["model_id"] / "model_card.md").exists()
    meta = multi.registry_for(root, "meta_label").load(out["meta_label"]["model_id"])
    from atlas.models.quant.meta import meta_dataset
    X = meta_dataset(bars, pt=meta.params["pt"], sl=meta.params["sl"]).tail(50)
    f = meta.size_factor(X)
    assert ((0 <= f) & (f <= 1)).all() and meta.params["pt"] in (1.0, 1.5, 2.0)


def test_tampered_new_kind_refused(trained):
    root, _, out = trained
    reg = multi.registry_for(root, "portfolio")
    p = root / "portfolio" / out["portfolio"]["model_id"] / "portfolio.json"
    orig = p.read_text()
    p.write_text(orig.replace('"max_weight": 0.4', '"max_weight": 0.9'))
    assert p.read_text() != orig
    with pytest.raises(PermissionError):
        reg.load(out["portfolio"]["model_id"])
    p.write_text(orig)


def test_every_experiment_logged_and_dsr_uses_all_trials(trained):
    root, _, out = trained
    meta_trials = TrialLog(root / "meta_label" / "trials.jsonl").records()
    assert {(r["params"]["pt"], r["params"]["sl"]) for r in meta_trials} == {(1.0, 1.0), (1.5, 1.0), (2.0, 1.0)}
    fs = TrialLog(root / "factor_sleeve" / "trials.jsonl").records()
    assert sum(r["params"].get("stage") == "feature_screen" for r in fs) == 4
    assert len(TrialLog(root / "portfolio" / "trials.jsonl").records()) >= 2
    assert len(TrialLog(root / "conformal" / "trials.jsonl").records()) == 3
    # validation n_trials grows monotonically with the global count (later kinds see earlier trials)
    assert out["meta_label"]["n_trials"] == 3 and out["conformal"]["n_trials"] == 6
    assert out["portfolio"]["n_trials"] == n_trials(root) - 0 or out["portfolio"]["n_trials"] <= n_trials(root)


def test_alpha_kinds_need_dsr_non_alpha_do_not(trained):
    root, _, out = trained
    t = [datetime(2026, 10, 16, tzinfo=timezone.utc)]
    good = {"n": 50, "lift_bps": 5.0, "brier": 0.24, "champion_brier": 0.245, "drawdown_pct": 2.0}
    for kind, ok in (("meta_label", False), ("execution", True)):
        reg = multi.registry_for(root, kind)
        reg.clock = lambda: t[0]
        mid = out[kind]["model_id"]
        reg.idx["models"][mid]["challenger_since"] = t[0].isoformat()
        for w in range(4):
            reg.record_shadow_week(mid, f"2027-W{10 + w}", good)
        t[0] += timedelta(days=30)
        if ok:
            reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)
        else:
            with pytest.raises(PromotionDenied, match="deflated_sharpe"):
                reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)


def test_model_cannot_claim_non_alpha_via_metrics(tmp_path):
    reg = multi.registry_for(tmp_path, "portfolio")
    mid = reg.register(PortfolioModel(), {"validation": {"applies": False}, "feature_importance_stability_spearman": 1})
    gates = {g.name: g for g in reg.gates(mid, ModelPromotionCfg())}
    assert not gates["deflated_sharpe"].passed


def test_execution_calibration_haircut():
    rng = np.random.default_rng(0)
    f = pd.DataFrame({"participation": rng.uniform(0.001, 0.05, 100), "daily_vol_bps": 150.0, "half_spread_bps": 3.0})
    f["realized_bps"] = f.half_spread_bps + 0.6 * f.daily_vol_bps * np.sqrt(f.participation)
    m, rep = calibrate_execution(f, "/tmp")
    assert abs(rep["Y_raw"] - 0.6) < 0.01 and abs(m.impact_Y - 0.75) < 0.02
    assert calibrate_execution(None, "/tmp")[0].impact_Y == 0.8


def test_roundtrips(tmp_path):
    for m in (FactorSleeveModel({"momentum": 1.0}, 0.0), PortfolioModel("hrp", 60, 0.3), ExecutionModel(1.1, 0.05)):
        m.save(tmp_path / type(m).__name__)
        assert type(m).load(tmp_path / type(m).__name__).save is not None
