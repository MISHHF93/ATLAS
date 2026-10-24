"""Value-at-Risk: parametric (variance-covariance, normal), historical simulation and CVaR/ES.

All results are positive loss numbers in the units of the input (returns or $ P&L). Historical figures reuse
library.historical_var_es so there is one implementation. Read-only analytics; never sizes or approves an order."""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Mapping, Sequence

import numpy as np

from atlas.features.price_action.library import historical_var_es

MIN_OBS = 20


def parametric_var(values: Sequence[float], alpha: float = 0.95, horizon_days: float = 1.0) -> dict[str, float] | None:
    """Normal VaR/ES on a P&L or return series: VaR = -(mu*h) + z*sigma*sqrt(h); ES = -(mu*h) + sigma*sqrt(h)*phi(z)/(1-a)."""
    x = np.asarray(values, float)
    x = x[np.isfinite(x)]
    if len(x) < MIN_OBS or not 0.5 < alpha < 1:
        return None
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    z = NormalDist().inv_cdf(alpha)
    h = math.sqrt(horizon_days)
    var = -mu * horizon_days + z * sd * h
    es = -mu * horizon_days + sd * h * NormalDist().pdf(z) / (1 - alpha)
    return {"var": var, "cvar": es, "es": es, "mu": mu, "sigma": sd, "z": z, "n": int(len(x)), "method": "parametric_normal"}


def portfolio_parametric_var(exposures_usd: Mapping[str, float], returns: Mapping[str, Sequence[float]],
                             alpha: float = 0.95) -> dict[str, object] | None:
    """Variance-covariance VaR of a $ exposure vector from aligned daily return series (same length per symbol)."""
    syms = [s for s in exposures_usd if s in returns and len(returns[s]) >= MIN_OBS]
    if not syms:
        return None
    n = min(len(returns[s]) for s in syms)
    R = np.array([np.asarray(returns[s][-n:], float) for s in syms])
    w = np.array([float(exposures_usd[s]) for s in syms])
    cov = np.atleast_2d(np.cov(R, ddof=1))
    mu = R.mean(axis=1)
    sd = float(math.sqrt(max(0.0, w @ cov @ w)))
    z = NormalDist().inv_cdf(alpha)
    m = float(w @ mu)
    marginal = (cov @ w) / sd if sd > 0 else np.zeros(len(syms))
    return {"var_usd": -m + z * sd, "es_usd": -m + sd * NormalDist().pdf(z) / (1 - alpha), "sigma_usd": sd, "n": n,
            "component_var_usd": {s: float(w[i] * marginal[i] * z) for i, s in enumerate(syms)}, "method": "variance_covariance_normal"}


def var_report(values: Sequence[float], alphas: Sequence[float] = (0.95, 0.99)) -> dict[str, object]:
    out: dict[str, object] = {"n": len(values)}
    for a in alphas:
        k = f"{int(round(a * 100))}"
        out[f"parametric_{k}"] = parametric_var(values, a)
        out[f"historical_{k}"] = historical_var_es(values, a)
    return out
