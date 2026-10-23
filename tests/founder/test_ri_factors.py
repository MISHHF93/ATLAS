"""Item 4: Alpha158, factor sleeves w/ sector neutralization, TSMOM, IC/turnover/decay, FFD in folds."""
import numpy as np
import pandas as pd
import pytest

from atlas.models.quant import factor_eval as fe
from atlas.models.quant import factors as F
from atlas.models.quant.alpha158 import ALPHA158, alpha158
from atlas.models.quant.fracdiff import FracDiffFold, ffd, ffd_weights


def _ohlcv(n=300, seed=0):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = c * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.005, "low": np.minimum(o, c) * 0.995, "close": c,
                         "volume": rng.integers(1e5, 3e5, n).astype(float)}, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def test_alpha158_has_158_causal_features():
    df = _ohlcv()
    a = alpha158(df)
    assert len(ALPHA158) == 158 and list(a.columns) == ALPHA158 and a.iloc[70:].notna().all().all()
    df2 = df.copy(); df2.iloc[200:, :] *= 2
    pd.testing.assert_frame_equal(a.iloc[:200], alpha158(df2).iloc[:200])   # no look-ahead


def _panel(n=400, k=30, seed=0, planted=0.0):
    rng = np.random.default_rng(seed)
    sig = pd.DataFrame(rng.normal(size=(n, k)), index=pd.date_range("2023-01-01", periods=n, freq="D"),
                       columns=[f"S{i}" for i in range(k)])
    r = rng.normal(0, 0.01, (n, k)) + planted * sig.shift(1).fillna(0).to_numpy() * 0.01
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, 0)), index=sig.index, columns=sig.columns)
    return sig, close


def test_ic_detects_planted_signal_and_decays():
    sig, close = _panel(planted=0.5)
    ts = fe.tear_sheet(sig, close, horizons=(1, 5, 20))
    assert ts["ic_by_horizon"][1]["ic_mean"] > 0.2 and ts["ic_by_horizon"][1]["t_stat"] > 5
    assert ts["ic_by_horizon"][20]["ic_mean"] < ts["ic_by_horizon"][1]["ic_mean"]
    assert ts["top_minus_bottom"] > 0 and 0.6 < ts["top_quantile_turnover"] <= 1
    noise, nclose = _panel(seed=5)
    scr = fe.screen({"sig": sig, "noise": noise}, close, horizon=1)
    assert scr.loc["sig", "keep"] and not scr.loc["noise", "keep"]


def test_sector_neutralization_removes_sector_bets():
    sig, close = _panel()
    sectors = {c: ("Energy" if i < 15 else "Financials") for i, c in enumerate(sig.columns)}
    biased = sig.copy(); biased[[c for c in sig if sectors[c] == "Energy"]] += 3
    neu = F.sector_neutralize(biased, sectors)
    en = neu[[c for c in sig if sectors[c] == "Energy"]].mean(1)
    assert en.abs().max() < 1e-9


def test_factor_sleeves_and_composite():
    sig, close = _panel(n=1400, k=20)
    mom, lv, val = F.momentum(close), F.low_vol(close), F.value(close=close)
    q = F.quality(roe=sig, leverage=sig.shift(1))
    comp = F.composite({"mom": mom, "val": val, "q": q, "lv": lv}, {c: "A" if i % 2 else "B" for i, c in enumerate(close)})
    last = comp.iloc[-1]
    assert abs(last.mean()) < 1e-9 and np.isclose(last.std(), 1, atol=0.05)
    assert mom.iloc[:252].isna().all().all()   # warm-up: no look-ahead


def test_ts_momentum_long_only_vol_targeted():
    t = pd.Series(100 * np.exp(np.linspace(0, 1, 600) + np.random.default_rng(0).normal(0, 0.01, 600)),
                  index=pd.date_range("2022-01-01", periods=600, freq="D"))
    pos = F.ts_momentum(t)
    assert pos.dropna().between(0, 1).all() and pos.iloc[-1] > 0
    down = F.ts_momentum(t.iloc[::-1].reset_index(drop=True).set_axis(t.index))
    assert (down.dropna().iloc[-50:] == 0).all()


def test_ffd_and_d_fitted_inside_fold_only():
    assert np.isclose(ffd_weights(1.0)[-2:], [-1, 1]).all()
    rng = np.random.default_rng(0)
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800))), index=pd.date_range("2020-01-01", periods=800))
    train, test = p.iloc[:500], p.iloc[500:]
    fd = FracDiffFold().fit(train)
    assert 0 < fd.d <= 1 and fd.report
    out = fd.transform(p)
    # transform is causal: test-period values don't change train-period output
    assert np.allclose(out.iloc[:500].dropna(), fd.transform(train).dropna())
    with pytest.raises(RuntimeError):
        FracDiffFold().transform(test)
