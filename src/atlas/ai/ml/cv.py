"""Purged + embargoed expanding walk-forward (Lopez de Prado 2018, ch. 7).

Rows are labelled events with start t_i (detection) and end e_i (barrier exit). For a test block whose first
event starts at T0, a training event i is kept only if e_i < T0 - embargo: its label is fully resolved before
the test period starts plus an embargo, so no training label overlaps or immediately precedes the test window.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np


def walk_forward_splits(t: np.ndarray, exit_at: np.ndarray, n_folds: int = 5, embargo: int = 86400,
                        min_train: int = 100) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    t, e = np.asarray(t, np.int64), np.asarray(exit_at, np.int64)
    if np.any(np.diff(t) < 0):
        raise ValueError("rows must be sorted by t")
    if np.any(e < t):
        raise ValueError("exit_at must be >= t")
    n = len(t)
    edges = [int(n * k / (n_folds + 1)) for k in range(1, n_folds + 2)]
    for k in range(n_folds):
        lo, hi = edges[k], edges[k + 1]
        if hi <= lo:
            continue
        t0 = t[lo]
        test = np.arange(lo, hi)
        test = test[t[test] >= t0]
        train = np.flatnonzero((t < t0) & (e < t0 - embargo))
        if len(train) < min_train:
            continue
        yield k, train, test


def inner_split(t: np.ndarray, exit_at: np.ndarray, idx: np.ndarray, frac_fit: float = 0.6, frac_cal: float = 0.2,
                embargo: int = 86400) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split a training index (time-ordered) into fit | calibration | conformal blocks, each purged against the next."""
    idx = np.asarray(idx)
    n = len(idx)
    a, b = int(n * frac_fit), int(n * (frac_fit + frac_cal))
    cal_t0 = t[idx[a]] if a < n else np.inf
    conf_t0 = t[idx[b]] if b < n else np.inf
    fit = idx[:a][exit_at[idx[:a]] < cal_t0 - embargo]
    cal = idx[a:b][exit_at[idx[a:b]] < conf_t0 - embargo]
    conf = idx[b:]
    return fit, cal, conf
