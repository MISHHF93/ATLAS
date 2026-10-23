"""Per-sleeve stacked scorers: learn a planted signal OOS, calibrated, leakage-safe, registry + routing."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from founder_conftest import intent
from mm_helpers import planted_bars
from atlas.control.policy.schemas import MlFilterCfg
from atlas.models.quant.features import FEATURES, make_features
from atlas.models.quant.multi import MultiSleeveStage, registry_for, retrain_scorers
from atlas.models.quant.sleeves import StackedScorer, train_sleeve


@pytest.fixture(scope="module")
def trained():
    bars = {f"S{i}": planted_bars(1400, seed=i, strength=0.006) for i in range(3)}
    return train_sleeve("active_equity", bars, n_splits=3)


def test_stacker_learns_planted_signal_out_of_sample(trained):
    _, rep, _ = trained
    o = rep["oos"]
    assert o["auc_stacked"] > 0.56 and o["brier"] < o["brier_base_rate"]
    assert o["lift_bps_per_day"] > 0 and 0 <= rep["deflated_sharpe"]["dsr"] <= 1


def test_no_edge_on_pure_noise():
    bars = {f"N{i}": planted_bars(1400, seed=10 + i, strength=0.0) for i in range(2)}
    _, rep, _ = train_sleeve("active_equity", bars, n_splits=3)
    assert rep["oos"]["auc_stacked"] < 0.58   # no fake skill from leakage


def test_calibration_reliability(trained):
    sc, _, X = trained
    p = sc.p_hit(X)
    assert np.all((p >= 0) & (p <= 1)) and 0.3 < p.mean() < 0.7


def test_features_are_point_in_time():
    df = planted_bars(300, seed=3)
    f1 = make_features(df)
    df2 = df.copy(); df2.iloc[200:, 0] *= 1.5   # change the future
    f2 = make_features(df2)
    pd.testing.assert_frame_equal(f1.iloc[:200], f2.iloc[:200])


def test_save_load_roundtrip(trained, tmp_path):
    sc, _, X = trained
    sc.save(tmp_path / "m"); sc2 = StackedScorer.load(tmp_path / "m")
    assert np.allclose(sc.p_hit(X.iloc[:50]), sc2.p_hit(X.iloc[:50]))


def test_retrain_all_registers_challengers_with_cards(tmp_path):
    bars = {"core_etf": {"SPY": planted_bars(1200, seed=1)}, "crypto": {"BTC": planted_bars(1200, seed=2, freq="D", vol=0.03)}}
    out = retrain_scorers(bars, tmp_path, n_splits=3)
    for s, r in out.items():
        reg = registry_for(tmp_path, f"scorer_{s}")
        assert reg.stage(r["model_id"]) == "challenger" and reg.champion is None
        assert (reg.root / r["model_id"] / "model_card.md").exists() and reg.reference(r["model_id"])


def test_multi_stage_routes_by_sleeve_and_falls_back(trained):
    sc, _, X = trained
    st = MultiSleeveStage(None, MlFilterCfg(min_p_hit=0.5), scorers={"active_equity": sc})
    c_active = [(intent(sleeve="active", qty=10, symbol=f"A{i}"), X.iloc[[i]]) for i in range(-40, 0)]
    c_crypto = [(intent(sleeve="high_risk", qty=10, symbol="BTC"), X.iloc[[0]])]
    out = st.apply(c_active + c_crypto)
    crypto = [r for r in out if r["intent"].symbol == "BTC"]
    assert crypto and crypto[0]["fallback"] == "rules_only_half_size" and crypto[0]["intent"].qty == 5
    assert all(r["intent"].qty <= 10 for r in out) and len(out) <= len(c_active) + 1
    assert all(r["p_hit"] >= 0.55 for r in out if r["scorer"] == "active_equity")
