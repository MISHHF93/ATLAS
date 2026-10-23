"""Synthetic data with a PLANTED, learnable signal (time-series momentum) for model tests."""
import numpy as np
import pandas as pd


def planted_bars(n=1500, seed=0, strength=0.004, vol=0.01, start="2019-01-01", freq="B", regime_switch=False):
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    sig = np.full(n, vol)
    if regime_switch:  # calm / turbulent blocks
        for i in range(n):
            sig[i] = vol if (i // 250) % 2 == 0 else vol * 3
    for t in range(n):
        mom = np.sign(r[max(0, t - 5):t].sum()) if t > 5 else 0.0
        r[t] = strength * mom + sig[t] * rng.standard_normal()
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC") + pd.Timedelta(hours=21)
    close = 100 * np.exp(np.cumsum(r))
    vol_ = 1e6 * np.exp(rng.normal(0, 0.2, n))
    return pd.DataFrame({"close": close, "volume": vol_}, index=idx)
