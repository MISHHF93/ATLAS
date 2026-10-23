"""Item 5: HRP/HERC vs inverse-vol, conformal sizing (MAPIE + ACI)."""
import numpy as np
import pandas as pd
import pytest

from atlas.models.quant.conformal import AdaptiveConformal, SplitConformalSizer, mapie_available, size_from_width
from atlas.portfolio.construction import (_hrp_inhouse, cap_weights, herc, hrp, inverse_vol, skfolio_available,
                                               walk_forward_benchmark)


def _rets(n=800, seed=0):
    rng = np.random.default_rng(seed)
    f = rng.normal(0, 0.01, (n, 2))
    cols = {}
    for i in range(4):
        cols[f"E{i}"] = f[:, 0] + rng.normal(0, 0.005, n)       # correlated cluster
    for i in range(2):
        cols[f"B{i}"] = 0.3 * f[:, 1] + rng.normal(0, 0.002, n)  # low-vol cluster
    cols["C"] = rng.normal(0, 0.04, n)                          # crypto-like
    return pd.DataFrame(cols, index=pd.date_range("2022-01-01", periods=n, freq="D"))


def test_weights_valid_and_hrp_diversifies_clusters():
    r = _rets()
    for w in (inverse_vol(r), hrp(r), _hrp_inhouse(r)) + ((herc(r),) if skfolio_available() else ()):
        assert np.isclose(w.sum(), 1) and (w >= -1e-12).all()
    w = _hrp_inhouse(r)
    assert w["C"] < w[["B0", "B1"]].min() and w[["E0", "E1", "E2", "E3"]].sum() < 0.6


def test_cap_weights():
    w = cap_weights(pd.Series([0.7, 0.2, 0.1], index=list("abc")), 0.4)
    assert np.isclose(w.sum(), 1) and w.max() <= 0.4 + 1e-9


def test_walk_forward_benchmark_reports_all_methods_oos():
    res = walk_forward_benchmark(_rets(), lookback=252, rebalance=21, max_weight=0.4)
    assert {"inverse_vol", "hrp"} <= set(res) and all(v["n_oos_days"] == 800 - 252 for v in res.values())
    if skfolio_available():
        assert "herc" in res


def test_size_from_width_only_reduces():
    f = size_from_width([0.5, 1, 2, 4], ref_width=1.0)
    assert list(f) == [1.0, 1.0, 0.5, 0.0]


@pytest.mark.parametrize("use_mapie", [True, False])
def test_split_conformal_coverage_and_size_bounds(use_mapie):
    if use_mapie and not mapie_available():
        pytest.skip("mapie not installed")
    rng = np.random.default_rng(0)
    n = 3000
    X = rng.normal(size=(n, 3)); noisy = (X[:, 2] > 0.8)
    y = 0.5 * X[:, 0] + rng.normal(0, 1, n) * np.where(noisy, 3.0, 0.3)
    from sklearn.linear_model import LinearRegression
    s = SplitConformalSizer(LinearRegression(), 0.8, use_mapie=use_mapie).fit(X[:1500], y[:1500], X[1500:2200], y[1500:2200])
    lo, hi = s.interval(X[2200:])
    cov = ((y[2200:] >= lo) & (y[2200:] <= hi)).mean()
    assert 0.74 <= cov <= 0.88
    f = s.size_factor(X[2200:])
    assert ((f >= 0) & (f <= 1)).all()


def test_aci_adapts_to_vol_shift():
    rng = np.random.default_rng(1)
    aci = AdaptiveConformal(alpha=0.2, gamma=0.02)
    assert aci.half_width() == float("inf")
    for t in range(1500):
        sd = 0.01 if t < 750 else 0.04
        aci.update(0.0, rng.normal(0, sd))
    assert 0.72 <= aci.coverage() <= 0.88 and aci.half_width() > 0.03
