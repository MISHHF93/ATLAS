"""Unified serving path. Registries are TEST FIXTURES (constant-score Platt maps), not fitted models."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.features.price_action.detectors import Candidate
from atlas.ml.drift import reference
from atlas.models import serving as sv
from atlas.ops.correlation import bind
from tests.price_action.test_predict import synthetic_setup_registry


def cand(direction="long", stop=99.0, target=103.0, t=1000, feats=None, cid="c1"):
    return Candidate(cid, "orb_retest", "GC", direction, t, 100.0, 99.0, stop, target, {},
                     feats if feats is not None else {"breakout_strength": 0.5})


def test_classify_covers_all_six_and_fails_closed():
    assert sv.classify([]) == "TRADE_CANDIDATE"
    assert sv.classify(["stale_data", "costs_exceed_edge"]) == "INSUFFICIENT_DATA"
    assert sv.classify(["no_validated_model"]) == "NO_TRADE"
    assert sv.classify(["htf_bias_conflict"]) == "CONFLICTING_EVIDENCE"
    assert sv.classify(["costs_exceed_edge"]) == "UNFAVORABLE_COSTS"
    assert sv.classify(["uncalibrated"]) == "LOW_CONFIDENCE"
    assert sv.classify(["something_new"]) == "NO_TRADE"
    assert set(sv.STATUSES) == {"TRADE_CANDIDATE", "LOW_CONFIDENCE", "CONFLICTING_EVIDENCE",
                                "INSUFFICIENT_DATA", "UNFAVORABLE_COSTS", "NO_TRADE"}


def test_serve_statuses_end_to_end():
    reg = synthetic_setup_registry(0.6)
    mv = "synthetic-setup-v1"
    assert sv.serve(cand(), registry=sv.ModelRegistry())[2].status == "NO_TRADE"       # empty registry
    _, _, d = sv.serve(cand(), model_version=mv, registry=reg)
    assert d.status == "TRADE_CANDIDATE" and d.execution_permission == "none" and d.probability == pytest.approx(0.6)
    assert sv.serve(cand(), model_version=mv, registry=reg, cost_per_unit=1.5)[2].status == "UNFAVORABLE_COSTS"
    assert sv.serve(cand(feats={}), model_version=mv, registry=reg)[2].status == "INSUFFICIENT_DATA"
    assert sv.serve(cand(), model_version=mv, registry=reg, htf_bias="short")[2].status == "CONFLICTING_EVIDENCE"
    a, b = cand(), cand("short", 101.0, 97.0, cid="c2")
    assert sv.serve(a, model_version=mv, registry=reg, same_bar=[a, b])[2].status == "CONFLICTING_EVIDENCE"
    assert sv.serve(cand(stop=101.0), model_version=mv, registry=reg)[2].status == "NO_TRADE"   # bad geometry
    assert sv.serve(cand(), model_version=mv, registry=synthetic_setup_registry(0.26))[2].status == "LOW_CONFIDENCE"


def test_drift_guard_moves_status():
    rng = np.random.default_rng(0)
    ref = reference(pd.DataFrame({"breakout_strength": rng.normal(0, 1, 2000)}), ["breakout_strength"])
    reg, mv = synthetic_setup_registry(0.6), "synthetic-setup-v1"
    g = sv.DriftGuard(ref, min_n=50, window=1000)
    for x in rng.normal(0, 1, 800):
        g.observe({"breakout_strength": float(x)})
    assert sv.serve(cand(), model_version=mv, registry=reg, drift=g)[2].status == "TRADE_CANDIDATE"
    g2 = sv.DriftGuard(ref, min_n=50)
    for x in rng.normal(4, 1, 60):
        g2.observe({"breakout_strength": float(x)})
    _, _, d = sv.serve(cand(feats={"breakout_strength": 4.0}), model_version=mv, registry=reg, drift=g2)
    assert d.status == "NO_TRADE" and "drift_significant" in d.reasons
    assert sv.serve(cand(), model_version=mv, registry=reg, drift=sv.DriftGuard(ref), require_drift=True)[2].status \
        == "INSUFFICIENT_DATA"


def test_correlation_id_and_catalog(tmp_path):
    reg = synthetic_setup_registry(0.6)
    with bind("cid-test-1"):
        _, _, d = sv.serve(cand(), model_version="synthetic-setup-v1", registry=reg)
    assert d.correlation_id == "cid-test-1"
    cat = sv.catalog(ml_root=tmp_path / "none", quant_root=tmp_path / "none", serving=reg)
    assert cat["n_served"] == 1 and cat["models"][0]["store"] == "serving"


def test_control_plane_records_carry_correlation_id():
    from atlas.control.engine import ActionableControlPlaneEngine
    from atlas.strategies.base import StrategySignal
    sig = StrategySignal(symbol="SPY", direction="BUY", reference_price=100, suggested_stop_loss=98,
                         suggested_take_profit=104, execution_permission="none")
    with bind("cid-cp-7"):
        rep = ActionableControlPlaneEngine().process_strategy_signal(sig, 100_000)
    assert rep.correlation_id == "cid-cp-7" and rep.decision.correlation_id == "cid-cp-7"


def test_serving_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from atlas.api.app import app
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path / "ml"))
    monkeypatch.setenv("ATLAS_MODELS_ROOT", str(tmp_path / "q"))
    r = TestClient(app).get("/api/ml/serving", headers={"x-correlation-id": "abc123"})
    assert r.status_code == 200 and r.json()["execution_permission"] == "none" and len(r.json()["statuses"]) == 6
