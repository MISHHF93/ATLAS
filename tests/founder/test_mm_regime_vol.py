"""Regime detector (scale-down only, causal), volatility forecaster (HAR/GARCH, walk-forward QLIKE), sizing caps."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from mm_helpers import planted_bars
from atlas.models.quant.regime import RegimeModel, regime_card, regime_features
from atlas.models.quant.vol import VolModel, qlike, vol_card
from atlas.risk.sizing import vol_target_qty


@pytest.fixture(scope="module")
def switching():
    return planted_bars(2000, seed=5, strength=0.0, vol=0.006, regime_switch=True)


@pytest.fixture(scope="module")
def regime(switching):
    F = regime_features(switching["close"])
    return RegimeModel.fit(F), F


def test_regime_identifies_turbulent_blocks_and_only_scales_down(regime, switching):
    m, F = regime
    mult = m.risk_multiplier(F)
    assert mult.max() <= 1.0 and mult.min() >= m.floor
    i = np.arange(len(switching))
    calm_idx = switching.index[((i // 250) % 2 == 0) & (i % 250 > 60)]
    turb_idx = switching.index[((i // 250) % 2 == 1) & (i % 250 > 60)]
    assert mult.reindex(calm_idx).mean() > mult.reindex(turb_idx).mean() + 0.2


def test_regime_filter_is_causal(regime):
    m, F = regime
    full = m.filtered_proba(F)
    part = m.filtered_proba(F.iloc[:900])
    pd.testing.assert_frame_equal(full.iloc[:900], part)   # future data cannot change past states


def test_regime_mult_config_cannot_exceed_one(regime, tmp_path):
    m, F = regime
    m.mult = {"calm": 5.0, "normal": 2.0, "stressed": 1.5}
    assert m.risk_multiplier(F).max() <= 1.0
    m.mult = {"calm": 1.0, "normal": 0.75, "stressed": 0.4}
    m.save(tmp_path / "r"); m2 = RegimeModel.load(tmp_path / "r")
    assert np.allclose(m.risk_multiplier(F), m2.risk_multiplier(F))
    regime_card().validate()


def test_vol_forecaster_tracks_volatility_and_beats_naive(switching):
    r = np.log(switching["close"]).diff().dropna()
    m = VolModel.select(r)
    assert m.kind in ("har", "garch") and set(m.report["qlike"]) == {"har", "garch"}
    v = m.var_path(r).shift(1)
    i = np.arange(len(r))
    hi = v[((i // 250) % 2 == 1) & (i % 250 > 30)].mean(); lo = v[((i // 250) % 2 == 0) & (i % 250 > 30)].mean()
    assert hi > 3 * lo
    naive = pd.Series(r.var(), index=r.index)
    ok = v.notna() & (r ** 2 > 0)
    assert qlike((r ** 2)[ok], v[ok]) < qlike((r ** 2)[ok], naive[ok])
    vol_card().validate()


def test_vol_forecast_causal_floor_cap_and_roundtrip(switching, tmp_path):
    r = np.log(switching["close"]).diff().dropna()
    for kind, params in (("har", VolModel.fit_har(r)), ("garch", VolModel.fit_garch(r))):
        m = VolModel(kind, params)
        a = m.var_path(r); b = m.var_path(r.iloc[:1000])
        assert np.allclose(a.iloc[:1000].dropna(), b.dropna())
        assert 0.05 <= m.forecast_ann(r) <= 2.0
        m.save(tmp_path / kind); assert VolModel.load(tmp_path / kind).forecast_ann(r) == m.forecast_ann(r)
    assert VolModel("har", VolModel.fit_har(r)).forecast_ann(r.iloc[:3]) == 2.0  # unknown => cap (smaller size)


def test_sizing_example():
    s = vol_target_qty(10_000, 0.10, 0.20, 50, 1.0, 20_000, 10, 5_000)
    assert s["caps"]["vol_target"] == 5_000 and s["qty"] == pytest.approx(40)   # min(5000, 2000 pos cap, 5000) / 50
    assert s["binding"] == "position_pct"


@settings(max_examples=200, deadline=None)
@given(budget=st.floats(1, 1e6), tv=st.floats(0.01, 0.5), fv=st.floats(0, 3), px=st.floats(0.01, 1e4),
       rm=st.floats(-5, 5), sm=st.floats(-5, 5), p=st.one_of(st.none(), st.floats(0, 1)))
def test_property_models_never_exceed_policy_caps(budget, tv, fv, px, rm, sm, p):
    s = vol_target_qty(budget, tv, fv, px, 1.0, 50_000, 10, 5_000, regime_mult=rm, screener_mult=sm, p_hit=p)
    assert s["notional_base"] <= min(5_000, 5_000, budget) + 1e-6
    base = vol_target_qty(budget, tv, fv, px, 1.0, 50_000, 10, 5_000)
    assert s["qty"] <= base["qty"] + 1e-9   # regime / screener / Kelly can only reduce
