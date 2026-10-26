"""Purged / embargoed cross-validation for overlapping labels (López de Prado).

Sample i's label spans times [t_i, t_i + horizon]. A training sample is PURGED if its
label window overlaps the test window; an EMBARGO of `embargo` unique time steps further
separates training label ends from the start of the walk-forward test window (and removes
post-test samples in k-fold). Walk-forward never trains on the future. Never shuffled."""
from __future__ import annotations

from typing import Iterator

import numpy as np


def _label_end(t: np.ndarray, horizon: int) -> np.ndarray:
    """Label end time = time of the sample `horizon` unique timestamps later (by unique-time rank)."""
    uniq = np.unique(t)
    rank = np.searchsorted(uniq, t)
    return uniq[np.minimum(rank + horizon, len(uniq) - 1)]


def purged_walk_forward_splits_by_time(times, n_splits: int = 5, horizon: int = 5, embargo: int = 0,
                        min_train_frac: float = 0.3) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    t = np.asarray(times)
    uniq = np.unique(t)
    start = int(len(uniq) * min_train_frac)
    edges = np.linspace(start, len(uniq), n_splits + 1).astype(int)
    end = _label_end(t, horizon)
    emb = max(0, int(embargo))
    for k in range(n_splits):
        lo, hi = uniq[edges[k]], uniq[min(edges[k + 1], len(uniq)) - 1]
        emb_lo = uniq[max(0, edges[k] - emb)]
        test = np.where((t >= lo) & (t <= hi))[0]
        train = np.where((t < emb_lo) & (end < emb_lo))[0]   # purge labels reaching into test + pre-test embargo
        if len(train) and len(test):
            yield train, test


# Deprecated name; use ``purged_walk_forward_splits_by_time`` (index splitter). Not the same as atlas.research.vertical_slice.purged_walk_forward.
purged_walk_forward = purged_walk_forward_splits_by_time


def purged_kfold(times, n_splits: int = 5, horizon: int = 5, embargo: int = 5) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    t = np.asarray(times)
    uniq = np.unique(t)
    edges = np.linspace(0, len(uniq), n_splits + 1).astype(int)
    end = _label_end(t, horizon)
    for k in range(n_splits):
        lo, hi = uniq[edges[k]], uniq[edges[k + 1] - 1]
        emb_hi = uniq[min(edges[k + 1] - 1 + embargo, len(uniq) - 1)]
        test = np.where((t >= lo) & (t <= hi))[0]
        overlap = (t <= hi) & (end >= lo)                 # label window intersects test window
        embargoed = (t > hi) & (t <= emb_hi)
        train = np.where(~overlap & ~embargoed & ~((t >= lo) & (t <= hi)))[0]
        yield train, test
