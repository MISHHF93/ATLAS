"""Conformal prediction for position sizing. Distribution-free intervals around a return forecast;
WIDE interval (model not confident) => smaller size or abstain. Output is a factor in [0,1] that
multiplies an already-approved qty, so it can only reduce.

* ``SplitConformalSizer``: MAPIE (BSD-3) SplitConformalRegressor when installed, else an equivalent
  in-house split-conformal quantile (same guarantee under exchangeability).
* ``AdaptiveConformal``: online ACI (Gibbs & Candès 2021) which adjusts alpha_t after each realised
  miss, since market data is not exchangeable."""
from __future__ import annotations

import numpy as np


def mapie_available() -> bool:
    try:
        import mapie  # noqa: F401
        return True
    except Exception:
        return False


def size_from_width(width, ref_width: float, abstain_mult: float = 3.0) -> np.ndarray:
    w = np.asarray(width, float)
    f = np.clip(ref_width / np.maximum(w, 1e-12), 0, 1)
    return np.where(w > abstain_mult * ref_width, 0.0, f)


class SplitConformalSizer:
    def __init__(self, estimator=None, confidence: float = 0.8, use_mapie: bool = True, abstain_mult: float = 3.0):
        from sklearn.ensemble import HistGradientBoostingRegressor
        self.est = estimator or HistGradientBoostingRegressor(max_iter=150, random_state=0)
        self.confidence, self.abstain_mult = confidence, abstain_mult
        self.use_mapie = use_mapie and mapie_available()
        self.ref_width: float | None = None

    def fit(self, X_train, y_train, X_cal, y_cal) -> "SplitConformalSizer":
        if self.use_mapie:
            from mapie.regression import SplitConformalRegressor
            self._m = SplitConformalRegressor(self.est, confidence_level=self.confidence, prefit=False)
            self._m.fit(X_train, y_train).conformalize(X_cal, y_cal)
        else:
            self.est.fit(X_train, y_train)
            res = np.abs(np.asarray(y_cal) - self.est.predict(X_cal))
            n = len(res)
            self._q = float(np.quantile(res, min(1.0, np.ceil((n + 1) * self.confidence) / n), method="higher"))
        lo, hi = self.interval(X_cal)
        self.ref_width = float(np.median(hi - lo))
        return self

    def interval(self, X):
        if self.use_mapie:
            _, iv = self._m.predict_interval(X)
            return iv[:, 0, 0], iv[:, 1, 0]
        p = self.est.predict(X)
        return p - self._q, p + self._q

    def size_factor(self, X) -> np.ndarray:
        lo, hi = self.interval(X)
        return size_from_width(hi - lo, self.ref_width, self.abstain_mult)


class AdaptiveConformal:
    """ACI on absolute residual scores: alpha_{t+1} = alpha_t + gamma * (alpha - err_t)."""

    def __init__(self, alpha: float = 0.2, gamma: float = 0.01, window: int = 250):
        self.alpha, self.gamma, self.window = alpha, gamma, window
        self.alpha_t = alpha
        self.scores: list[float] = []
        self.misses: list[int] = []

    def half_width(self) -> float:
        if len(self.scores) < 20:
            return float("inf")       # not enough evidence -> abstain
        a = float(np.clip(self.alpha_t, 1e-3, 0.999))
        return float(np.quantile(self.scores[-self.window:], 1 - a))

    def update(self, y_pred: float, y_true: float) -> None:
        hw = self.half_width()
        err = int(abs(y_true - y_pred) > hw)
        self.misses.append(err)
        self.alpha_t += self.gamma * (self.alpha - err)
        self.scores.append(abs(y_true - y_pred))

    def coverage(self) -> float:
        m = self.misses[20:]
        return 1 - float(np.mean(m)) if m else float("nan")
