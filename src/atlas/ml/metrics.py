"""Evaluation metrics. Definitions in docs/ml/metrics.md."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from atlas.models.quant.metrics import deflated_sharpe
from atlas.models.quant.validation import pbo_cscv

EPS = 1e-6


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(((p - y) ** 2).mean())


def logloss(p, y) -> float:
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def ece(p, y, bins: int = 10) -> float:
    """Expected calibration error: sum_b (n_b/n) |mean(y_b) - mean(p_b)| over equal-width bins."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum((idx == b).mean() * abs(y[idx == b].mean() - p[idx == b].mean()) for b in range(bins) if (idx == b).any()))


def reliability(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return [{"bin_lo": b / bins, "bin_hi": (b + 1) / bins, "n": int((idx == b).sum()), "mean_p": float(p[idx == b].mean()),
             "hit_rate": float(y[idx == b].mean())} for b in range(bins) if (idx == b).any()]


def auc(p, y) -> float | None:
    y = np.asarray(y)
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None


def daily_series(t, r, t0: int, t1: int) -> np.ndarray:
    """Sum of per-trade R by UTC day over [t0, t1] (days without trades = 0)."""
    t, r = np.asarray(t, np.int64), np.asarray(r, float)
    d0, d1 = t0 // 86400, t1 // 86400
    out = np.zeros(int(d1 - d0 + 1))
    np.add.at(out, (t // 86400 - d0).astype(int), r)
    return out


def dsr(series: np.ndarray, trial_series: list[np.ndarray]) -> dict:
    srs = [float(s.mean() / s.std(ddof=1)) if len(s) > 2 and s.std(ddof=1) > 0 else 0.0 for s in trial_series]
    return deflated_sharpe(series, srs)


def pbo(matrix: np.ndarray, n_blocks: int = 16) -> dict | None:
    if matrix.shape[1] < 2 or matrix.shape[0] < n_blocks * 2:
        return None
    return pbo_cscv(matrix, n_blocks=n_blocks)
