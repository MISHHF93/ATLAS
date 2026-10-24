"""Probability calibration and split-conformal abstention.

* Isotonic regression (Zadrozny & Elkan 2002) when the calibration block has >= 200 rows, else Platt scaling
  (Platt 1999). Both are fitted on a block strictly after the model-fit block (purged) and never on test rows.
* Split conformal (Vovk et al. 2005; Angelopoulos & Bates 2021): nonconformity s = 1 - p_hat(y). With n conformal
  scores, qhat = the ceil((n+1)(1-alpha))/n empirical quantile. Prediction set C(x) = {y : 1 - p_hat(y) <= qhat}.
  We act only on singleton {1} ("take"); {0}, {0,1} or {} abstain (classification with reject option,
  Linusson et al. 2018 / Hallberg Szabadvary & Lofstrom 2025).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

EPS = 1e-6


@dataclass
class Calibrator:
    kind: str
    iso: IsotonicRegression | None = None
    a: float = 1.0
    b: float = 0.0
    fitted_through: int = 0
    n: int = 0

    def __call__(self, s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, float)
        if self.kind == "isotonic":
            p = self.iso.predict(s)
        elif self.kind == "platt":
            z = np.log(np.clip(s, EPS, 1 - EPS) / (1 - np.clip(s, EPS, 1 - EPS)))
            p = 1 / (1 + np.exp(-(self.a * z + self.b)))
        else:
            p = s
        return np.clip(p, EPS, 1 - EPS)

    def apply(self, score: float, *, observation_time: int) -> float:
        """predict() calibrator protocol."""
        if observation_time <= self.fitted_through:
            raise LookupError("calibration_unsupported")
        return float(self(np.array([score]))[0])


def fit_calibrator(s: np.ndarray, y: np.ndarray, fitted_through: int, min_iso: int = 200) -> Calibrator:
    s, y = np.asarray(s, float), np.asarray(y, int)
    if len(s) >= min_iso and 0 < y.sum() < len(y):
        iso = IsotonicRegression(y_min=EPS, y_max=1 - EPS, out_of_bounds="clip").fit(s, y)
        return Calibrator("isotonic", iso=iso, fitted_through=fitted_through, n=len(s))
    if len(s) >= 20 and 0 < y.sum() < len(y):
        z = np.log(np.clip(s, EPS, 1 - EPS) / (1 - np.clip(s, EPS, 1 - EPS))).reshape(-1, 1)
        lr = LogisticRegression(C=1e6).fit(z, y)
        return Calibrator("platt", a=float(lr.coef_[0, 0]), b=float(lr.intercept_[0]), fitted_through=fitted_through, n=len(s))
    return Calibrator("identity", fitted_through=fitted_through, n=len(s))


@dataclass
class Conformal:
    qhat: float
    alpha: float
    n: int

    def sets(self, p: np.ndarray) -> list[frozenset[int]]:
        p = np.asarray(p, float)
        return [frozenset(c for c, pc in ((1, pi), (0, 1 - pi)) if 1 - pc <= self.qhat) for pi in p]

    def take_mask(self, p: np.ndarray) -> np.ndarray:
        return np.array([s == frozenset({1}) for s in self.sets(p)], bool)


def fit_conformal(p: np.ndarray, y: np.ndarray, alpha: float = 0.2) -> Conformal:
    p, y = np.asarray(p, float), np.asarray(y, int)
    n = len(p)
    if n == 0:
        return Conformal(qhat=0.0, alpha=alpha, n=0)     # empty -> every set empty -> always abstain
    s = np.sort(1 - np.where(y == 1, p, 1 - p))
    k = math.ceil((n + 1) * (1 - alpha))
    q = 1.0 if k > n else float(s[k - 1])
    return Conformal(qhat=q, alpha=alpha, n=n)
