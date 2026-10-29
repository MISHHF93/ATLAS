"""Purged + embargoed expanding walk-forward (Lopez de Prado 2018, ch. 7).

Rows are labelled events with start t_i (detection) and end e_i (barrier exit). For a test block whose first
event starts at T0, a training event i is kept only if e_i < T0 - embargo: its label is fully resolved before
the test period starts plus an embargo, so no training label overlaps or immediately precedes the test window.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np

# Same floors fit_meta uses after the embargo purge. A fold that cannot meet them is not a test.
MIN_FIT, MIN_CAL, MIN_CONF = 60, 20, 20


def _train_ready(t: np.ndarray, e: np.ndarray, lo: int, embargo: int, min_train: int,
                 min_fit: int, min_cal: int, min_conf: int) -> bool:
    t0 = int(t[lo])
    train = np.flatnonzero((t < t0) & (e < t0 - embargo))
    if len(train) < min_train:
        return False
    fit, cal, conf = inner_split(t, e, train, embargo=embargo)
    return len(fit) >= min_fit and len(cal) >= min_cal and len(conf) >= min_conf


def walk_forward_splits(t: np.ndarray, exit_at: np.ndarray, n_folds: int = 5, embargo: int = 86400,
                        min_train: int = 100, min_fit: int = MIN_FIT, min_cal: int = MIN_CAL,
                        min_conf: int = MIN_CONF) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    t, e = np.asarray(t, np.int64), np.asarray(exit_at, np.int64)
    if np.any(np.diff(t) < 0):
        raise ValueError("rows must be sorted by t")
    if np.any(e < t):
        raise ValueError("exit_at must be >= t")
    n = len(t)
    last = n - n_folds
    if last < 1 or not _train_ready(t, e, last, embargo, min_train, min_fit, min_cal, min_conf):
        return
    left, right = 1, last
    while left < right:
        mid = (left + right) // 2
        if _train_ready(t, e, mid, embargo, min_train, min_fit, min_cal, min_conf):
            right = mid
        else:
            left = mid + 1
    start = left
    while start <= last and not _train_ready(t, e, start, embargo, min_train, min_fit, min_cal, min_conf):
        start += 1
    if start > last:
        return
    span = n - start
    edges = [start + int(span * k / n_folds) for k in range(n_folds + 1)]
    for k in range(n_folds):
        lo, hi = edges[k], edges[k + 1]
        if hi <= lo:
            continue
        t0 = int(t[lo])
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
