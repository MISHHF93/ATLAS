"""Item 2: triple-barrier labels sized by vol forecast + meta-labeling (news veto feature)."""
import numpy as np
import pandas as pd
import pytest

from atlas.models.quant.labels import causal_daily_vol, label_concurrency_weights, triple_barrier
from atlas.models.quant.meta import META_FEATURES, meta_dataset, momentum_primary, train_meta


def _close(vals):
    return pd.Series(vals, index=pd.date_range("2025-01-01", periods=len(vals), freq="D"), dtype=float)


def test_barriers_hit_order_and_t1():
    c = _close([100, 101, 103, 106, 90, 90, 90, 90])
    vol = pd.Series(0.01, index=c.index)
    lab = triple_barrier(c, pt=1, sl=1, max_hold=4, vol=vol)  # width = 0.02
    first = lab.iloc[0]
    assert first.barrier == "pt" and first.t1 == c.index[2] and first.bin == 1
    short = triple_barrier(c, side=pd.Series(-1, index=c.index), max_hold=4, vol=vol).iloc[0]
    assert short.barrier == "sl" and short.ret < 0
    assert (lab["t1"] > lab.index).all() and (lab["t1"] <= lab.index + pd.Timedelta(days=4)).all()


def test_wider_vol_means_wider_barriers_and_unresolved_tail_dropped():
    rng = np.random.default_rng(0)
    c = _close(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    lo = triple_barrier(c, max_hold=10, vol=pd.Series(0.002, index=c.index))
    hi = triple_barrier(c, max_hold=10, vol=pd.Series(0.05, index=c.index))
    assert (lo.barrier != "vertical").mean() > (hi.barrier != "vertical").mean()
    assert hi[hi.barrier == "vertical"].index.max() <= c.index[-11]   # unresolved tail dropped, not mislabelled


def test_causal_vol_has_no_lookahead():
    rng = np.random.default_rng(1)
    c = _close(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200))))
    v1 = causal_daily_vol(c)
    c2 = c.copy(); c2.iloc[150:] *= 3
    assert np.allclose(v1.iloc[:151].dropna(), causal_daily_vol(c2).iloc[:151].dropna())


def test_vol_model_drives_barriers():
    from atlas.models.quant.vol import VolModel
    rng = np.random.default_rng(2)
    c = _close(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    vm = VolModel.select(np.log(c).diff().dropna())
    lab = triple_barrier(c, max_hold=5, vol=np.sqrt(vm.var_path(np.log(c).diff().dropna())).reindex(c.index))
    assert len(lab) > 300 and lab.sigma.between(1e-4, 0.2).all()


def test_uniqueness_weights():
    t0 = pd.date_range("2025-01-01", periods=3, freq="D")
    w = label_concurrency_weights(t0, pd.Series([t0[0], t0[2], t0[2]], index=t0))
    assert w.iloc[0] == 1.0 and w.iloc[2] < 1.0


def _bars(n=900, seed=0, planted=True):
    rng = np.random.default_rng(seed)
    out = {}
    for k in range(4):
        r = rng.normal(0, 0.01, n)
        c = 100 * np.exp(np.cumsum(r))
        out[f"S{k}"] = pd.DataFrame({"close": c, "volume": rng.integers(1e5, 2e5, n).astype(float)},
                                    index=pd.date_range("2022-01-01", periods=n, freq="D"))
    return out


def test_meta_learns_veto_feature_and_only_shrinks():
    bars = _bars()
    veto = {s: pd.Series((np.arange(len(df)) % 7 == 0).astype(int), index=df.index) for s, df in bars.items()}
    ds = meta_dataset(bars, momentum_primary, max_hold=10, cost_bps=10, news_veto=veto)
    # plant: vetoed trades are losers -> meta model must learn the feature
    ds.loc[ds.news_veto > 0, "bin"] = 0; ds.loc[ds.news_veto > 0, "ret"] = -0.02
    assert set(META_FEATURES) <= set(ds.columns) and ds["side"].isin([-1, 1]).all()
    model, rep = train_meta(ds, n_splits=4)
    X = ds.iloc[-200:]
    f = model.size_factor(X)
    assert ((f >= 0) & (f <= 1)).all() and (f[X.news_veto.to_numpy() > 0] == 0).all()
    assert model.p_profit(X[X.news_veto > 0]).mean() < model.p_profit(X[X.news_veto == 0]).mean()
    assert model.apply(10, X.iloc[[0]]) <= 10
    assert rep["auc_oos"] > 0.55
