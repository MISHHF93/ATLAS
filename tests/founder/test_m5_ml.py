"""M5: purged CV, deflated Sharpe, LightGBM filter, registry gates, shadow mode, retrain job."""
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from founder_conftest import intent
from atlas.control.policy.schemas import MlFilterCfg, ModelPromotionCfg
from atlas.models.quant.cv import _label_end, purged_kfold, purged_walk_forward
from atlas.models.quant.features import FEATURES, dataset
from atlas.models.quant.metrics import deflated_sharpe, expected_max_sharpe, probabilistic_sharpe, sharpe
from atlas.models.quant.model import TradeFilterModel
from atlas.models.quant.registry import ModelRegistry, PromotionDenied
from atlas.models.quant.retrain import synthetic_bars, weekly_retrain
from atlas.models.quant.shadow import ShadowRunner
from atlas.models.quant.stage import MLFilterStage


@pytest.fixture(scope="module")
def bars():
    return synthetic_bars(("SPY", "QQQ"), date(2019, 1, 1), date(2022, 12, 31))


@pytest.fixture(scope="module")
def ds(bars):
    return dataset(bars, horizon=5, cost_bps=10)


@pytest.fixture(scope="module")
def model(ds):
    return TradeFilterModel.train(ds[FEATURES], ds["y"].values)


# ---------------------------------------------------------------- CV
def test_walk_forward_is_purged_and_never_uses_future():
    t = np.repeat(np.arange(200), 2)  # 2 symbols per timestamp
    end = _label_end(t, 5)
    n = 0
    for tr, te in purged_walk_forward(t, n_splits=4, horizon=5):
        n += 1
        assert t[tr].max() < t[te].min()
        assert end[tr].max() < t[te].min()  # no label overlap
        assert t[te].min() - t[tr].max() >= 6
    assert n == 4


def test_purged_kfold_purges_and_embargoes():
    t = np.arange(100)
    for tr, te in purged_kfold(t, n_splits=5, horizon=3, embargo=4):
        lo, hi = t[te].min(), t[te].max()
        assert not np.any((t[tr] >= lo - 3) & (t[tr] <= hi))     # purged before & inside
        assert not np.any((t[tr] > hi) & (t[tr] <= hi + 4))      # embargo after
        assert set(tr).isdisjoint(te)


# ---------------------------------------------------------------- metrics
def test_sharpe_and_psr_basic():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 1000)
    assert 0.5 < sharpe(r) < 2.5
    assert probabilistic_sharpe(r, 0.0) > 0.95
    assert probabilistic_sharpe(-r, 0.0) < 0.05


def test_expected_max_sharpe_known_value():
    # Bailey & Lopez de Prado: N=100 trials, std of SR=1 -> E[max] ~= 2.53
    srs = np.array([-1.0, 1.0] * 50) * (1 / np.std([-1.0, 1.0] * 50, ddof=1))
    assert expected_max_sharpe(srs) == pytest.approx(2.5306, abs=1e-3)


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0008, 0.01, 750)
    few = deflated_sharpe(r, [0.01, 0.02])
    many = deflated_sharpe(r, list(rng.normal(0, 0.03, 500)))
    assert many["dsr"] < few["dsr"] and many["sr0_expected_max_per_period"] > few["sr0_expected_max_per_period"]


# ---------------------------------------------------------------- model
def test_model_calibrated_probabilities_and_shap(model, ds):
    X = ds[FEATURES].iloc[-50:]
    p = model.p_hit(X)
    assert p.shape == (50,) and np.all((p >= 0) & (p <= 1))
    ex = model.explain(X.iloc[:3], top=5)
    assert len(ex) == 3 and len(ex[0]) == 5 and all(f in FEATURES for f, _ in ex[0])
    # TreeSHAP additivity on raw margin: contributions + bias == raw log-odds
    contrib = model.booster.predict(X.iloc[:3], pred_contrib=True, num_iteration=model.meta["best_iteration"])
    raw = model.booster.predict(X.iloc[:3], raw_score=True, num_iteration=model.meta["best_iteration"])
    assert np.allclose(contrib.sum(axis=1), raw, atol=1e-6)


def test_model_save_load_roundtrip_is_deterministic(model, ds, tmp_path):
    model.save(tmp_path / "m")
    m2 = TradeFilterModel.load(tmp_path / "m")
    X = ds[FEATURES].iloc[-20:]
    assert np.allclose(model.p_hit(X), m2.p_hit(X))
    again = TradeFilterModel.train(ds[FEATURES], ds["y"].values)
    assert np.allclose(again.p_hit(X), model.p_hit(X))  # deterministic training


# ---------------------------------------------------------------- ML stage
def test_ml_stage_only_filters_never_adds_or_upsizes(model, ds):
    cands = [(intent(symbol="SPY", qty=10), ds[FEATURES].iloc[[i]]) for i in range(-30, 0)]
    out = MLFilterStage(model, MlFilterCfg(min_p_hit=0.5)).apply(cands)
    ids = {c[0].intent_id for c in cands}
    assert len(out) <= len(cands) and all(r["intent"].intent_id in ids and r["intent"].qty <= 10 for r in out)
    assert all(r["p_hit"] >= 0.5 for r in out) and [r["p_hit"] for r in out] == sorted([r["p_hit"] for r in out], reverse=True)


def test_ml_stage_fallbacks(ds):
    cands = [(intent(qty=10), ds[FEATURES].iloc[[0]])]
    half = MLFilterStage(None, MlFilterCfg()).apply(cands)
    assert half[0]["intent"].qty == 5 and half[0]["fallback"] == "rules_only_half_size"
    assert MLFilterStage(None, MlFilterCfg(fallback="halt")).apply(cands) == []


# ---------------------------------------------------------------- registry
class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 16, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def _reg(tmp_path, model, clock):
    reg = ModelRegistry(tmp_path / "reg", clock=clock)
    mid = reg.register(model, {"feature_importance_stability_spearman": 0.8, "validation": VAL})
    reg.make_challenger(mid)
    return reg, mid


VAL = {"dsr": 0.97, "pbo": 0.2, "n_trials": 10}
GOOD = {"n": 50, "lift_bps": 5.0, "brier": 0.24, "champion_brier": 0.245, "drawdown_pct": 2.0}


def test_promotion_requires_four_shadow_weeks(tmp_path, model):
    clk = Clock(); reg, mid = _reg(tmp_path, model, clk)
    cfg = ModelPromotionCfg()
    for w in range(3):
        reg.record_shadow_week(mid, f"2026-W{43 + w}", GOOD)
    clk.t += timedelta(days=28)
    with pytest.raises(PromotionDenied, match="shadow_weeks"):
        reg.promote(mid, cfg, "learning_loop", autonomy_level=1)
    reg.record_shadow_week(mid, "2026-W46", GOOD)
    reg.promote(mid, cfg, "learning_loop", autonomy_level=1)
    assert reg.champion == mid


def test_weeks_recorded_but_not_enough_calendar_time(tmp_path, model):
    clk = Clock(); reg, mid = _reg(tmp_path, model, clk)
    for w in range(4):
        reg.record_shadow_week(mid, f"2026-W{43 + w}", GOOD)
    clk.t += timedelta(days=10)
    with pytest.raises(PromotionDenied, match="shadow_days_elapsed"):
        reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)


@pytest.mark.parametrize("bad,gate", [({"lift_bps": -1.0}, "after_cost_lift_bps"), ({"brier": 0.30}, "brier_not_worse"),
                                      ({"drawdown_pct": 25.0}, "shadow_drawdown_pct")])
def test_gates_fail(tmp_path, model, bad, gate):
    clk = Clock(); reg, mid = _reg(tmp_path, model, clk)
    for w in range(4):
        reg.record_shadow_week(mid, f"2026-W{43 + w}", GOOD | bad)
    clk.t += timedelta(days=30)
    with pytest.raises(PromotionDenied, match=gate):
        reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)


def test_model_cannot_promote_itself_and_signoff_at_level3(tmp_path, model):
    clk = Clock(); reg, mid = _reg(tmp_path, model, clk)
    for w in range(4):
        reg.record_shadow_week(mid, f"2026-W{43 + w}", GOOD)
    clk.t += timedelta(days=30)
    for actor in ("model", "ai", mid):
        with pytest.raises(PromotionDenied):
            reg.promote(mid, ModelPromotionCfg(), actor, 1)
    with pytest.raises(PromotionDenied, match="sign-off"):
        reg.promote(mid, ModelPromotionCfg(), "learning_loop", 3)
    with pytest.raises(PromotionDenied, match="sign-off"):
        reg.promote(mid, ModelPromotionCfg(), "owner", 3, step_up_verified=False)
    reg.promote(mid, ModelPromotionCfg(), "owner", 3, step_up_verified=True)
    assert reg.champion == mid


def test_min_shadow_weeks_cannot_be_configured_below_4():
    with pytest.raises(Exception):
        ModelPromotionCfg(min_shadow_weeks=2)


def test_rollback_and_persistence(tmp_path, model):
    clk = Clock(); reg, m1 = _reg(tmp_path, model, clk)
    for w in range(4):
        reg.record_shadow_week(m1, f"2026-W{43 + w}", GOOD)
    clk.t += timedelta(days=30)
    reg.promote(m1, ModelPromotionCfg(), "learning_loop", 1)
    m2 = reg.register(model, {"feature_importance_stability_spearman": 0.8, "validation": VAL}); reg.make_challenger(m2)
    for w in range(4):
        reg.record_shadow_week(m2, f"2026-W{47 + w}", GOOD)
    clk.t += timedelta(days=30)
    reg.promote(m2, ModelPromotionCfg(), "learning_loop", 1)
    with pytest.raises(PromotionDenied):
        reg.rollback("learning_loop", True)
    assert reg.rollback("owner", True) == m1
    again = ModelRegistry(tmp_path / "reg")
    assert again.champion == m1 and again.stage(m2) == "archived"
    assert any(h["event"] == "rollback" for h in again.idx["history"])


# ---------------------------------------------------------------- shadow
def test_shadow_runner_rollup(model, ds):
    sr = ShadowRunner(champion=None, challenger=model, min_p_hit=0.5)
    sub = ds.iloc[-60:]
    for k, (ts, row) in enumerate(sub.iterrows()):
        sr.score(ts.date(), f"k{k}", sub[FEATURES].iloc[[k]])
        sr.record_outcome(f"k{k}", float(row["fwd"]))
    roll = sr.weekly_rollup()
    assert roll and all({"n", "lift_bps", "brier", "champion_brier", "drawdown_pct"} <= set(v) for v in roll.values())
    assert all(r["champion_take"] for r in sr.log)  # no champion => rules-only baseline takes all


# ---------------------------------------------------------------- weekly retrain job
def test_weekly_retrain_registers_challenger_with_report(tmp_path, bars):
    reg = ModelRegistry(tmp_path / "reg")
    rep = weekly_retrain(bars, reg, n_splits=3)
    mid = rep["model_id"]
    assert reg.stage(mid) == "challenger" and reg.champion is None
    assert len(rep["folds"]) == 3 and 0 <= rep["deflated_sharpe"]["dsr"] <= 1
    assert set(rep["shap_global_mean_abs"]) == set(FEATURES)
    assert (tmp_path / "reg" / "reports" / f"{mid}.md").read_text().startswith("# Weekly retrain report")
    rep2 = weekly_retrain(bars, reg, n_splits=3)
    assert rep2["deflated_sharpe"]["n_trials"] > rep["deflated_sharpe"]["n_trials"]  # trials accumulate
    assert reg.stage(mid) == "archived" and reg.challenger == rep2["model_id"]
