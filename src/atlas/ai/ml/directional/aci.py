"""Adaptive conformal inference (Gibbs & Candes 2021, arXiv:2106.00170) for a binary label.

Online, causal, no exchangeability needed. At step t with miscoverage target alpha:
  * score of a candidate label c is s_t(c) = 1 - p_t(c); the set is C_t = {c : s_t(c) <= qhat_t}
  * qhat_t = the ceil((n+1)(1 - alpha_t)) / n empirical quantile of the last ``window`` RESOLVED scores
  * err_t = 1[y_t not in C_t]; alpha_{t+1} = alpha_t + gamma * (alpha - err_t)
Finite-sample guarantee: |mean(err_t) - alpha| <= (max(alpha_1, 1 - alpha_1) + gamma) / (gamma T).
Only labels already resolved before the prediction time enter the score buffer (``resolved_at <= t``).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ACIState:
    alpha: float = 0.2
    gamma: float = 0.01
    window: int = 500
    alpha_t: float = field(default=None)       # type: ignore[assignment]

    def __post_init__(self):
        if self.alpha_t is None:
            self.alpha_t = self.alpha


def empirical_qhat(scores: np.ndarray, alpha_t: float) -> float:
    """Same quantile as one ACI step: ceil((m+1)(1-alpha_t))/m of the resolved scores. Empty buffer → 1.0 (uninformative full set)."""
    recent = np.sort(np.asarray(scores, float))
    if len(recent) == 0:
        return 1.0
    level = 1.0 - float(np.clip(alpha_t, 0.0, 1.0))
    m = len(recent)
    kk = math.ceil((m + 1) * level)
    if kk > m:
        return float("inf")
    return float(recent[max(kk, 1) - 1])


def aci_binary(t: np.ndarray, resolved_at: np.ndarray, p: np.ndarray, y: np.ndarray, init_scores: np.ndarray | None = None,
               alpha: float = 0.2, gamma: float = 0.01, window: int = 500) -> dict:
    """Run ACI over an OOS stream sorted by t. Returns per-step sets, errors, alpha_t and the bound.

    ``init_scores`` seeds the buffer (e.g. a purged conformal block that ended before the stream starts).
    """
    t, resolved_at = np.asarray(t, np.int64), np.asarray(resolved_at, np.int64)
    p, y = np.asarray(p, float), np.asarray(y, int)
    n = len(t)
    buf: list[float] = list(np.asarray(init_scores, float)) if init_scores is not None and len(init_scores) else []
    pending: list[tuple[int, int, float]] = []          # (resolved_at, order, score) waiting to become known
    st = ACIState(alpha, gamma, window)
    sets, errs, alphas, qs = [], np.zeros(n), np.zeros(n), np.zeros(n)
    for k in range(n):
        while pending and pending[0][0] <= t[k]:
            buf.append(heapq.heappop(pending)[2])
        recent = np.sort(np.asarray(buf[-window:], float)) if buf else np.array([])
        a = float(np.clip(st.alpha_t, 0.0, 1.0))
        if len(recent) == 0:
            q = 1.0                                     # no history: full set (honest, uninformative)
        else:
            level = 1.0 - a
            m = len(recent)
            kk = math.ceil((m + 1) * level)
            q = float("inf") if kk > m else float(recent[max(kk, 1) - 1])
        s1, s0 = 1 - p[k], p[k]                         # score of label 1 is 1-p, of label 0 is 1-(1-p)=p
        cset = frozenset(c for c, s in ((1, s1), (0, s0)) if s <= q)
        err = 0.0 if int(y[k]) in cset else 1.0
        sets.append(cset)
        errs[k], alphas[k], qs[k] = err, a, q
        st.alpha_t = st.alpha_t + gamma * (alpha - err)
        heapq.heappush(pending, (int(resolved_at[k]), k, float(s1 if y[k] == 1 else s0)))
    cov = float(1 - errs.mean()) if n else float("nan")
    bound = (max(alpha, 1 - alpha) + gamma) / (gamma * n) if n else float("nan")
    return {"sets": sets, "err": errs, "alpha_t": alphas, "qhat": qs, "coverage": cov, "target_coverage": 1 - alpha,
            "gap": float(abs(errs.mean() - alpha)) if n else float("nan"), "gap_bound": float(bound),
            "singleton_rate": float(np.mean([len(s) == 1 for s in sets])) if n else 0.0,
            "take_up": np.array([s == frozenset({1}) for s in sets], bool), "take_down": np.array([s == frozenset({0}) for s in sets], bool)}
