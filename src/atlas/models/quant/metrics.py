"""Sharpe, Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado 2014), Brier."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

N = NormalDist()
EULER = 0.5772156649015329


def sharpe(returns, periods: int = 252) -> float:
    r = np.asarray(returns, float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def _moments(r):
    r = np.asarray(r, float)
    m, s = r.mean(), r.std(ddof=0)
    if s == 0:
        return 0.0, 3.0
    z = (r - m) / s
    return float((z ** 3).mean()), float((z ** 4).mean())


def probabilistic_sharpe(returns, sr_benchmark: float = 0.0) -> float:
    """PSR on PER-PERIOD Sharpe. Probability the true SR exceeds sr_benchmark."""
    r = np.asarray(returns, float)
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = _moments(r)
    denom = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom))


def expected_max_sharpe(trial_srs) -> float:
    """E[max SR] under the null across N trials with variance V of trial Sharpes (per-period)."""
    s = np.asarray(trial_srs, float)
    n = len(s)
    if n < 2:
        return 0.0
    v = s.var(ddof=1)
    return float(math.sqrt(v) * ((1 - EULER) * N.inv_cdf(1 - 1 / n) + EULER * N.inv_cdf(1 - 1 / (n * math.e))))


def deflated_sharpe(returns, trial_srs) -> dict:
    """DSR = PSR with the benchmark set to the expected max Sharpe of all trials tried."""
    sr0 = expected_max_sharpe(trial_srs)
    r = np.asarray(returns, float)
    sr = float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0
    return {"sr_per_period": sr, "sr_annual": sr * math.sqrt(252), "n_trials": len(trial_srs),
            "sr0_expected_max_per_period": sr0, "dsr": probabilistic_sharpe(r, sr0), "psr_vs_0": probabilistic_sharpe(r, 0.0)}


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(((p - y) ** 2).mean()) if len(p) else float("nan")


def max_drawdown_pct(returns) -> float:
    eq = np.exp(np.cumsum(np.asarray(returns, float)))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float(((peak - eq) / peak).max() * 100) if len(eq) else 0.0
