"""Causal event sampling and labels (ATLAS_MODEL_SPEC.md section 2).

All arrays are indexed by bar. ``close[i]`` is known at ``end[i]``; an event at bar i enters at close[i].
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SIGMA = 1e-6


def ewma_sigma(close: np.ndarray, span: int = 100) -> np.ndarray:
    """sigma_i = sqrt(EWMA of squared log returns up to and including bar i). Backward-looking only."""
    r = np.diff(np.log(np.asarray(close, float)), prepend=np.nan)
    s2 = pd.Series(r ** 2).ewm(span=span, min_periods=max(10, span // 5), adjust=False).mean().to_numpy()
    return np.sqrt(np.maximum(s2, 0.0))


def cusum_events(close: np.ndarray, sigma: np.ndarray, h_mult: float = 2.0, min_gap: int = 1) -> np.ndarray:
    """Symmetric CUSUM filter (AFML 2.5.2.1) on log returns with threshold h_i = h_mult * sigma_{i-1}.

    S+_i = max(0, S+_{i-1} + r_i), S-_i = min(0, S-_{i-1} + r_i); an event fires when S+ > h or S- < -h, then both reset.
    The threshold uses sigma of the previous bar so the decision at i never uses anything after i.
    """
    close = np.asarray(close, float)
    r = np.diff(np.log(close), prepend=np.nan)
    sp = sm = 0.0
    last = -10**9
    out = []
    for i in range(1, len(close)):
        h = h_mult * sigma[i - 1]
        if not (np.isfinite(h) and np.isfinite(r[i])) or h < MIN_SIGMA:
            continue
        sp, sm = max(0.0, sp + r[i]), min(0.0, sm + r[i])
        if sp > h or sm < -h:
            sp = sm = 0.0
            if i - last >= min_gap:
                out.append(i)
                last = i
    return np.asarray(out, int)


def triple_barrier(df: pd.DataFrame, events: np.ndarray, sigma: np.ndarray, horizon: int, k: float = 1.0) -> pd.DataFrame:
    """Vol-scaled triple barrier from the long side.

    entry = close_i; width w_i = k * sigma_i * sqrt(horizon) (log units); upper/lower = entry * exp(+-w_i);
    vertical barrier at bar i + horizon. Scan bars j = i+1..i+horizon on high/low:
      high_j >= upper only  -> label +1, exit return +w_i
      low_j  <= lower only  -> label -1, exit return -w_i
      both in the same bar  -> label 0 (ambiguous, order unknown), exit return log(close_j / entry)
      none by the vertical  -> label 0, exit return log(close_{i+h} / entry)
    ``exit_at`` = end of bar i+horizon (the latest bar the label could have used; conservative for purging).
    ``fwd_ret`` = log(close_{i+h}/close_i) / (sigma_i sqrt(h)) is the vol-normalised forward return target.
    Events whose horizon runs past the data are dropped (unresolved).
    """
    hi, lo, cl = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    end = df["end"].to_numpy(np.int64)
    rows = []
    n = len(df)
    for i in events:
        if i + horizon >= n or not np.isfinite(sigma[i]) or sigma[i] < MIN_SIGMA:
            continue
        w = k * sigma[i] * np.sqrt(horizon)
        up, dn = cl[i] * np.exp(w), cl[i] * np.exp(-w)
        label, ret, j_exit, amb = 0, float(np.log(cl[i + horizon] / cl[i])), i + horizon, False
        for j in range(i + 1, i + horizon + 1):
            hit_up, hit_dn = hi[j] >= up, lo[j] <= dn
            if hit_up and hit_dn:
                label, ret, j_exit, amb = 0, float(np.log(cl[j] / cl[i])), j, True
                break
            if hit_up:
                label, ret, j_exit = 1, float(w), j
                break
            if hit_dn:
                label, ret, j_exit = -1, float(-w), j
                break
        rows.append({"i": int(i), "t": int(end[i]), "t_barrier_exit": int(end[j_exit]), "exit_at": int(end[i + horizon]),
                     "sigma": float(sigma[i]), "width": float(w), "label": label, "ret": ret, "ambiguous": amb,
                     "fwd_ret": float(np.log(cl[i + horizon] / cl[i]) / (sigma[i] * np.sqrt(horizon))),
                     "y_up": int(ret > 0)})
    return pd.DataFrame(rows)
