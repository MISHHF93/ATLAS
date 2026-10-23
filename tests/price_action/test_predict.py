"""Unified predict() contract, calibration wiring, abstention, EV/Kelly math. All inputs are hand-built or
seeded SYNTHETIC samples; no market data, no performance claims."""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from atlas.models import opportunity as op
from atlas.models import predict as pr
from atlas.models.quant.conformal import AdaptiveConformal


def synthetic_setup_registry(p: float = 0.6, n: int = 50, **kw) -> pr.ModelRegistry:
    """Constant-score model whose Platt map returns exactly p. TEST FIXTURE ONLY (not a fitted model)."""
    reg = pr.ModelRegistry()
    cal = pr.PlattCalibrator(0.0, math.log(1 / p - 1), fitted_through=0, n_samples=n, brier_holdout=float("nan"))
    reg.register(pr.RegisteredModel("synthetic-setup-v1", "synthetic_fixture", "setup_resolution", "setup_success",
                                    ("breakout_strength",), lambda v: 0.0, cal, frozenset({"probability_positive"}), **kw))
    return reg


SNAP = pr.FeatureSnapshot({"breakout_strength": 0.5}, {"breakout_strength": 1000})


def test_unknown_and_missing_model_abstain():
    assert pr.predict("X", 2000, "h", SNAP, None).abstention_reason == ["no_validated_model"]
    assert pr.predict("X", 2000, "h", SNAP, "nope").abstention_reason == ["unknown_model"]


def test_calibrated_prediction_only_validated_fields():
    p = pr.predict("X", 2000, "setup_resolution", SNAP, "synthetic-setup-v1", synthetic_setup_registry(0.6))
    assert not p.abstained and p.calibration_status == "calibrated" and p.feature_quality == 1.0
    assert p.probability_positive == pytest.approx(0.6, abs=1e-6)
    assert p.probability_up is p.probability_down is p.probability_neutral is p.expected_return is p.uncertainty is None
    assert p.execution_permission == "none"


@pytest.mark.parametrize("snap,reason", [
    (pr.FeatureSnapshot({}, {}), "missing_features"),
    (pr.FeatureSnapshot({"breakout_strength": float("nan")}, {"breakout_strength": 1000}), "missing_features"),
    (pr.FeatureSnapshot({"breakout_strength": 0.5}, {"breakout_strength": 2001}), "feature_from_future"),
    (pr.FeatureSnapshot({"breakout_strength": 0.5}, {"breakout_strength": 2000 - 3601}), "stale_data"),
])
def test_feature_abstentions(snap, reason):
    p = pr.predict("X", 2000, "setup_resolution", snap, "synthetic-setup-v1", synthetic_setup_registry())
    assert reason in p.abstention_reason and p.probability_positive is None


def test_horizon_scope_and_calibration_abstentions():
    reg = synthetic_setup_registry(instruments=frozenset({"SPY"}))
    p = pr.predict("QQQ", 2000, "other", SNAP, "synthetic-setup-v1", reg)
    assert {"horizon_mismatch", "instrument_out_of_scope"} <= set(p.abstention_reason)
    # too few held-out calibration samples -> uncalibrated
    p = pr.predict("X", 2000, "setup_resolution", SNAP, "synthetic-setup-v1", synthetic_setup_registry(n=10))
    assert p.abstention_reason == ["uncalibrated"] and p.probability_positive is None
    # observation inside the calibration period -> leakage -> unsupported
    reg = pr.ModelRegistry()
    reg.register(pr.RegisteredModel("m", "d", "h", "setup_success", ("breakout_strength",), lambda v: 0.0,
                                    pr.PlattCalibrator(0, 0, fitted_through=5000, n_samples=99, brier_holdout=0.2),
                                    frozenset({"probability_positive"})))
    assert pr.predict("X", 2000, "h", SNAP, "m", reg).abstention_reason == ["calibration_unsupported"]
    # model with no calibrator but claiming probabilities
    reg2 = pr.ModelRegistry()
    reg2.register(pr.RegisteredModel("m", "d", "h", "setup_success", (), lambda v: 0.0, None, frozenset({"probability_positive"})))
    assert pr.predict("X", 2000, "h", SNAP, "m", reg2).abstention_reason == ["uncalibrated"]


def test_registry_rejects_unvalidatable_contracts():
    with pytest.raises(ValueError):
        pr.RegisteredModel("m", "d", "h", "t", (), lambda v: 0, None, frozenset({"probability_neutral"}))
    with pytest.raises(ValueError):
        pr.RegisteredModel("m", "d", "h", "t", (), lambda v: 0, None, frozenset({"made_up"}))
    reg = synthetic_setup_registry()
    with pytest.raises(ValueError):
        reg.register(reg.get("synthetic-setup-v1"))


def test_conformal_uncertainty_wiring():
    aci = AdaptiveConformal(alpha=0.2)
    base = dict(model_version="m", data_version="d", horizon="h", target="setup_success", required_features=(),
                score_fn=lambda v: 0.0, calibrator=pr.PlattCalibrator(0, 0, 0, 99, 0.25),
                validated_outputs=frozenset({"probability_positive", "uncertainty"}), conformal=aci, max_uncertainty=0.3)
    reg = pr.ModelRegistry(); reg.register(pr.RegisteredModel(**base))
    assert pr.predict("X", 10, "h", SNAP, "m", reg).abstention_reason == ["uncertainty_unavailable"]  # <20 residuals
    for i in range(40):
        aci.update(0.0, 0.1 if i % 2 else -0.1)
    p = pr.predict("X", 10, "h", SNAP, "m", reg)
    assert not p.abstained and p.uncertainty == pytest.approx(0.1)
    for _ in range(200):
        aci.update(0.0, 1.0)
    p = pr.predict("X", 10, "h", SNAP, "m", reg)
    assert p.abstention_reason == ["uncertainty_too_wide"] and p.probability_positive is None


def test_bin_calibrator_adapter_wires_existing_calibrator():
    from atlas.models.evaluation import ProbabilityCalibrator
    scope = dict(instrument_id="X", horizon_id="h", model_revision="m", target="setup_success", unit="prob")
    rng = random.Random(3)
    probs = [rng.random() for _ in range(200)]
    outs = [int(rng.random() < q) for q in probs]
    cal = ProbabilityCalibrator.fit(probabilities=probs, outcomes=outs, bins=5, calibration_id="c",
                                    fitted_through=datetime(2020, 1, 1, tzinfo=timezone.utc), **scope)
    reg = pr.ModelRegistry()
    reg.register(pr.RegisteredModel("m", "d", "h", "setup_success", (), lambda v: 0.55,
                                    pr.BinCalibratorAdapter(cal, scope), frozenset({"probability_positive"})))
    t = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp())
    assert pr.predict("X", t, "h", SNAP, "m", reg).probability_positive == pytest.approx(cal.bin_rates[2])
    assert pr.predict("X", 0, "h", SNAP, "m", reg).abstention_reason == ["calibration_unsupported"]


def test_fit_platt_recovers_known_logistic():
    rng = random.Random(7)
    s = [rng.uniform(-3, 3) for _ in range(4000)]
    y = [int(rng.random() < 1 / (1 + math.exp(-(1.5 * x - 0.5)))) for x in s]
    cal = pr.fit_platt(s, y, fitted_through=1)
    assert cal.slope_a == pytest.approx(-1.5, abs=0.15) and cal.intercept_b == pytest.approx(0.5, abs=0.15)
    assert 0 < cal.brier_holdout < 0.25
    with pytest.raises(ValueError):
        pr.fit_platt([1.0], [2], fitted_through=0)


# ---------- EV / break-even / Kelly (hand-computed) ----------

def test_ev_math():
    assert op.expected_value(0.6, 4, 2, 0) == pytest.approx(1.6)
    assert op.break_even_probability(4, 2, 0) == pytest.approx(1 / 3)
    assert op.break_even_probability(4, 2, 1) == pytest.approx(0.5)
    assert op.kelly_fraction(0.6, 2) == pytest.approx(0.4)
    assert op.risk_units(100_000, 0.006, 2.5, multiplier=1, lot=1) == 240
    assert op.risk_units(100_000, 0.006, 2.5, multiplier=50, lot=1) == 4
    assert op.risk_units(1000, 0.01, 0) == 0


class _C:
    candidate_id, entry_reference, proposed_stop, proposed_target = "c1", 103.0, 101.0, 107.0


def _pred(p):
    return pr.predict("X", 2000, "setup_resolution", SNAP, "synthetic-setup-v1", synthetic_setup_registry(p))


def test_evaluate_candidate_paths():
    ev = op.evaluate_candidate(_C, _pred(0.6), cost_per_unit=0.0, equity=100_000)
    assert not ev.abstained
    assert ev.expected_value == pytest.approx(1.6, abs=1e-5) and ev.expected_value_r == pytest.approx(0.8, abs=1e-5)
    assert ev.break_even_probability == pytest.approx(1 / 3) and ev.kelly_full == pytest.approx(0.4, abs=1e-5)
    assert ev.kelly_fractional == pytest.approx(0.1, abs=1e-5) and ev.research_units == 300
    assert ev.sizing_authority == "ActionableControlPlaneEngine"
    assert op.evaluate_candidate(_C, _pred(0.34), cost_per_unit=0.0).abstention_reason == ["insufficient_edge"]
    assert op.evaluate_candidate(_C, _pred(0.6), cost_per_unit=1.5).abstention_reason == ["costs_exceed_edge"]
    assert "costs_exceed_edge" in op.evaluate_candidate(_C, _pred(0.9), cost_per_unit=5).abstention_reason
    abst = op.evaluate_candidate(_C, pr.predict("X", 2000, "setup_resolution", SNAP, None), cost_per_unit=0)
    assert abst.abstention_reason == ["no_validated_model"] and abst.probability is None


def test_direction_model_cannot_be_used_as_setup_probability():
    reg = pr.ModelRegistry()
    reg.register(pr.RegisteredModel("d", "x", "setup_resolution", "direction_up", (), lambda v: 0.0,
                                    pr.PlattCalibrator(0, 0, 0, 99, 0.25), frozenset({"probability_up", "probability_down"})))
    p = pr.predict("X", 2000, "setup_resolution", SNAP, "d", reg)
    assert p.probability_up == pytest.approx(0.5) and p.probability_down == pytest.approx(0.5)
    assert op.evaluate_candidate(_C, p, cost_per_unit=0).abstention_reason == ["probability_semantics_mismatch"]
