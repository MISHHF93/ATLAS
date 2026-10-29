"""Probability calibration and split-conformal abstention.

* Isotonic regression (Zadrozny & Elkan 2002) when the calibration block has >= 200 rows, else Platt scaling
  (Platt 1999) with the soft 0/1 targets and a shrink toward the raw score. Both are fitted on a block
  strictly after the model-fit block (purged) and never on test rows.
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

EPS = 1e-6
# Platt (1999) on a short calibration block overfits hard 0/1 targets.
# The mapped probability is shrunk toward the raw score with this many prior observations.
PLATT_PRIOR_N = 40


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
            p_hat = 1 / (1 + np.exp(-(self.a * z + self.b)))
            p = (self.n * p_hat + PLATT_PRIOR_N * s) / (self.n + PLATT_PRIOR_N)
        else:
            p = s
        return np.clip(p, EPS, 1 - EPS)

    def apply(self, score: float, *, observation_time: int) -> float:
        """predict() calibrator protocol."""
        if observation_time <= self.fitted_through:
            raise LookupError("calibration_unsupported")
        return float(self(np.array([score]))[0])


def _fit_platt(s: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Platt scaling with the 1999 soft targets and a pull back toward the raw score."""
    s = np.clip(np.asarray(s, float), EPS, 1 - EPS)
    y = np.asarray(y, int)
    pos = y == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return 1.0, 0.0
    target = np.where(pos, (n_pos + 1) / (n_pos + 2), 1.0 / (n_neg + 2))
    z = np.log(s / (1 - s))
    a, b, l2 = 1.0, 0.0, 1.0
    for _ in range(30):
        p = 1 / (1 + np.exp(-np.clip(a * z + b, -20, 20)))
        p = np.clip(p, EPS, 1 - EPS)
        weight = p * (1 - p)
        err = target - p
        g_a = float(np.dot(err, z) - l2 * (a - 1))
        g_b = float(err.sum() - l2 * b)
        h_aa = float(np.dot(weight, z * z) + l2)
        h_bb = float(weight.sum() + l2)
        h_ab = float(np.dot(weight, z))
        det = h_aa * h_bb - h_ab * h_ab
        if det <= 1e-12:
            break
        a += float(np.clip((h_bb * g_a - h_ab * g_b) / det, -2, 2))
        b += float(np.clip((h_aa * g_b - h_ab * g_a) / det, -2, 2))
    return float(a), float(b)


def fit_calibrator(s: np.ndarray, y: np.ndarray, fitted_through: int, min_iso: int = 200) -> Calibrator:
    s, y = np.asarray(s, float), np.asarray(y, int)
    if len(s) >= min_iso and 0 < y.sum() < len(y):
        iso = IsotonicRegression(y_min=EPS, y_max=1 - EPS, out_of_bounds="clip").fit(s, y)
        return Calibrator("isotonic", iso=iso, fitted_through=fitted_through, n=len(s))
    if len(s) >= 20 and 0 < y.sum() < len(y):
        a, b = _fit_platt(s, y)
        return Calibrator("platt", a=a, b=b, fitted_through=fitted_through, n=len(s))
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
