"""Execution-cost model + edge gate (drop-only); Isolation Forest anomaly guard (halt/reduce only)."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from founder_conftest import intent
from atlas.governance.audit import AuditLog
from atlas.models.quant.anomaly_ml import ANOMALY_FEATURES, AnomalyGuard, AnomalyModel
from atlas.models.quant.costmodel import CostGate, CostModel, expected_edge_bps
from atlas.models.quant.multi import registry_for, retrain_anomaly, retrain_cost
from atlas.risk import KillSwitch

TRUE = (0.5, 1.0, 0.6)


def fills(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"half_spread_bps": rng.uniform(0.5, 20, n), "daily_vol_bps": rng.uniform(50, 400, n),
                       "participation": rng.uniform(0, 0.1, n)})
    df["realised_bps"] = TRUE[0] + TRUE[1] * df.half_spread_bps + TRUE[2] * df.daily_vol_bps * np.sqrt(df.participation) + rng.normal(0, 1.5, n)
    return df


def test_cost_model_recovers_coefficients_and_beats_naive():
    m = CostModel.fit(fills())
    assert np.allclose(m.coef, TRUE, atol=0.15)
    assert m.report["oos_mae_bps"] < 0.5 * m.report["naive_mae_bps"]
    assert m.predict_bps(5, 200, 0.01, commission_bps=1)[0] == pytest.approx(0.5 + 5 + 0.6 * 200 * 0.1 + 1, abs=0.6)


def test_cost_gate_drops_low_edge_only():
    g = CostGate(CostModel(list(TRUE)), audit=(a := AuditLog(":memory:")))
    recs = [{"intent": intent(symbol="A"), "edge_bps": 100, "half_spread_bps": 2, "daily_vol_bps": 100, "participation": 0.01},
            {"intent": intent(symbol="B"), "edge_bps": 10, "half_spread_bps": 10, "daily_vol_bps": 300, "participation": 0.05}]
    out = g.filter(recs)
    assert [r["intent"].symbol for r in out] == ["A"] and out[0]["intent"] is recs[0]["intent"]
    assert a.entries("cost.dropped")


def test_expected_edge():
    assert expected_edge_bps(0.5, 0.2, 5) == 0
    assert expected_edge_bps(0.6, 0.2, 5) == pytest.approx(0.2 * 0.8 * 0.2 * np.sqrt(5 / 252) * 1e4)


@settings(max_examples=100, deadline=None)
@given(edge=st.floats(-1e4, 1e4), sp=st.floats(0, 100), v=st.floats(0, 1000), part=st.floats(0, 1))
def test_property_gate_never_adds_or_modifies(edge, sp, v, part):
    i = intent()
    out = CostGate(CostModel(list(TRUE))).filter([{"intent": i, "edge_bps": edge, "half_spread_bps": sp, "daily_vol_bps": v, "participation": part}])
    assert len(out) <= 1 and all(r["intent"] is i for r in out)


def normal_ops(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"quote_age_s": rng.exponential(0.5, n), "spread_bps": rng.uniform(1, 5, n), "ret_z": rng.normal(0, 1, n),
                         "volume_z": rng.normal(0, 1, n), "slippage_bps": rng.normal(2, 1, n), "reject_rate": rng.uniform(0, 0.02, n),
                         "orders_per_min": rng.poisson(1, n), "pnl_change_z": rng.normal(0, 1, n)})


@pytest.fixture(scope="module")
def amodel():
    return AnomalyModel.fit(normal_ops())


NORMAL = dict(quote_age_s=0.4, spread_bps=3, ret_z=0.1, volume_z=0.0, slippage_bps=2, reject_rate=0.01, orders_per_min=1, pnl_change_z=0)
CRAZY = dict(quote_age_s=120, spread_bps=400, ret_z=12, volume_z=15, slippage_bps=150, reject_rate=0.9, orders_per_min=60, pnl_change_z=-9)


def test_anomaly_guard_none_reduce_halt(amodel):
    ks = KillSwitch(AuditLog(":memory:"))
    g = AnomalyGuard(amodel, ks)
    assert g.observe(NORMAL) == "none" and g.size_mult() == 1.0 and g(intent(), None) == ([], [])
    assert g.observe(CRAZY) == "halt" and ks.engaged and g.size_mult() == 0.0
    assert g(intent(), None)[0]


def test_sustained_mild_anomaly_escalates_to_halt(amodel):
    ks = KillSwitch(AuditLog(":memory:"))
    g = AnomalyGuard(amodel, ks, halt_after=3)
    mild = NORMAL | {"spread_bps": 9, "slippage_bps": 7, "quote_age_s": 4}
    s = amodel.score(pd.DataFrame([mild]))[0]
    amodel2 = AnomalyModel(amodel.forest, reduce_q=s + 1e-9, halt_q=s - 1)   # make `mild` exactly reduce-level
    g = AnomalyGuard(amodel2, ks, halt_after=3)
    assert [g.observe(mild) for _ in range(3)] == ["reduce", "reduce", "halt"] and ks.engaged


def test_guard_has_no_order_capability(amodel):
    g = AnomalyGuard(amodel, KillSwitch(AuditLog(":memory:")))
    assert not any(hasattr(g, n) for n in ("submit", "place_order", "propose_order", "execute", "reset"))


def test_registry_retrain_cost_and_anomaly(tmp_path):
    rc = retrain_cost(fills(800), tmp_path); ra = retrain_anomaly(normal_ops(500), tmp_path)
    for kind, r in (("cost", rc), ("anomaly", ra)):
        reg = registry_for(tmp_path, kind)
        assert reg.stage(r["model_id"]) == "challenger"
        m = reg.load(r["model_id"])
        assert m is not None and (reg.root / r["model_id"] / "model_card.md").exists()
    (tmp_path / "anomaly" / ra["model_id"] / "forest.joblib").write_bytes(b"tampered")
    with pytest.raises(PermissionError):
        registry_for(tmp_path, "anomaly").load(ra["model_id"])   # never unpickle tampered artefacts
