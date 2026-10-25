"""Fixed-width-window fractional differentiation (FFD, AFML ch.5). d is chosen as the minimum value
whose FFD series passes ADF at the given p-value, fitted on the TRAINING fold only and then applied
unchanged to the test fold (the red-flag list forbids fitting d on the full sample)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ffd_weights(d: float, thresh: float = 1e-4, max_len: int = 500) -> np.ndarray:
    w = [1.0]
    k = 1
    while k < max_len:
        nxt = -w[-1] * (d - k + 1) / k
        if abs(nxt) < thresh:
            break
        w.append(nxt); k += 1
    return np.array(w[::-1])


def ffd(series: pd.Series, d: float, thresh: float = 1e-4) -> pd.Series:
    w = ffd_weights(d, thresh)
    x = series.astype(float).to_numpy()
    out = np.full(len(x), np.nan)
    n = len(w)
    for i in range(n - 1, len(x)):
        out[i] = float(np.dot(w, x[i - n + 1:i + 1]))
    return pd.Series(out, index=series.index)


class FracDiffFold:
    def __init__(self, d_grid=np.round(np.arange(0.0, 1.01, 0.1), 2), pvalue: float = 0.05, thresh: float = 1e-3):
        self.d_grid, self.pvalue, self.thresh = d_grid, pvalue, thresh
        self.d: float | None = None
        self.report: list = []

    def fit(self, train: pd.Series) -> "FracDiffFold":
        try:
            from statsmodels.tsa.stattools import adfuller
            adf_p = lambda s: float(adfuller(s, maxlag=1, regression="c", autolag=None)[1])
        except ImportError:
            from scipy.stats import norm
            def adf_p(s: pd.Series) -> float:
                y = s.to_numpy(dtype=float)
                dy = np.diff(y)
                y_lag, dy_lag, target = y[1:-1], dy[:-1], dy[1:]
                X = np.column_stack([y_lag, dy_lag, np.ones_like(y_lag)])
                beta, *_ = np.linalg.lstsq(X, target, rcond=None)
                resid = target - X @ beta
                s2 = float(resid @ resid) / max(len(target) - 3, 1)
                cov = s2 * np.linalg.pinv(X.T @ X)
                se = float(np.sqrt(max(cov[0, 0], 1e-18)))
                tau = float(beta[0] / se)
                return float(norm.cdf(tau + 1.22))
        x = np.log(train.astype(float))
        for d in self.d_grid:
            s = ffd(x, float(d), self.thresh).dropna()
            if len(s) < 30:
                continue
            p = adf_p(s)
            self.report.append((float(d), p))
            if p < self.pvalue:
                self.d = float(d)
                return self
        self.d = 1.0
        return self

    def transform(self, series: pd.Series) -> pd.Series:
        if self.d is None:
            raise RuntimeError("fit on the training fold first")
        return ffd(np.log(series.astype(float)), self.d, self.thresh)
