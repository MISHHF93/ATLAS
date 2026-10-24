"""Black-Scholes(-Merton) pricing, greeks and implied volatility for European options.

Conventions: tte in years, vol and rates annualised decimals, continuous dividend yield q. Theta is per calendar
day, vega per 1 vol point (0.01), rho per 1 rate point (0.01). Pure math; no market data is fetched here."""
from __future__ import annotations

import math
from typing import Literal

Right = Literal["call", "put"]
SQRT2PI = math.sqrt(2 * math.pi)


def _n(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _check(spot: float, strike: float, tte: float, vol: float) -> None:
    for name, v in (("spot", spot), ("strike", strike), ("tte", tte), ("vol", vol)):
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            raise ValueError(f"{name} must be a positive finite number")


def _d1d2(spot, strike, tte, vol, r, q):
    d1 = (math.log(spot / strike) + (r - q + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    return d1, d1 - vol * math.sqrt(tte)


def price(spot: float, strike: float, tte: float, vol: float, r: float = 0.0, right: Right = "call", q: float = 0.0) -> float:
    _check(spot, strike, tte, vol)
    d1, d2 = _d1d2(spot, strike, tte, vol, r, q)
    dq, dr = math.exp(-q * tte), math.exp(-r * tte)
    if right == "call":
        return spot * dq * _N(d1) - strike * dr * _N(d2)
    if right == "put":
        return strike * dr * _N(-d2) - spot * dq * _N(-d1)
    raise ValueError("right must be call or put")


def greeks(spot: float, strike: float, tte: float, vol: float, r: float = 0.0, right: Right = "call", q: float = 0.0) -> dict[str, float]:
    _check(spot, strike, tte, vol)
    d1, d2 = _d1d2(spot, strike, tte, vol, r, q)
    dq, dr, st = math.exp(-q * tte), math.exp(-r * tte), math.sqrt(tte)
    gamma = dq * _n(d1) / (spot * vol * st)
    vega = spot * dq * _n(d1) * st / 100.0
    common = -spot * dq * _n(d1) * vol / (2 * st)
    if right == "call":
        delta = dq * _N(d1)
        theta = (common - r * strike * dr * _N(d2) + q * spot * dq * _N(d1)) / 365.0
        rho = strike * tte * dr * _N(d2) / 100.0
    else:
        delta = dq * (_N(d1) - 1.0)
        theta = (common + r * strike * dr * _N(-d2) - q * spot * dq * _N(-d1)) / 365.0
        rho = -strike * tte * dr * _N(-d2) / 100.0
    return {"price": price(spot, strike, tte, vol, r, right, q), "delta": delta, "gamma": gamma, "vega": vega,
            "theta": theta, "rho": rho, "d1": d1, "d2": d2}


def implied_vol(target_price: float, spot: float, strike: float, tte: float, r: float = 0.0, right: Right = "call",
                q: float = 0.0, lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-8, max_iter: int = 200) -> float | None:
    """Bisection on [lo, hi] (monotone in vol). Returns None when the price is outside no-arbitrage bounds."""
    _check(spot, strike, tte, 0.2)
    dq, dr = math.exp(-q * tte), math.exp(-r * tte)
    intrinsic = max(0.0, spot * dq - strike * dr) if right == "call" else max(0.0, strike * dr - spot * dq)
    upper = spot * dq if right == "call" else strike * dr
    if not math.isfinite(target_price) or target_price <= intrinsic + 1e-12 or target_price >= upper:
        return None
    f = lambda v: price(spot, strike, tte, v, r, right, q) - target_price  # noqa: E731
    flo, fhi = f(lo), f(hi)
    if flo > 0 or fhi < 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol or hi - lo < tol:
            return mid
        lo, hi = (mid, hi) if fm < 0 else (lo, mid)
    return 0.5 * (lo + hi)


# Options chains (OI / IV / strikes) need a licensed or keyed data source. None is configured in ATLAS and yfinance is
# not a dependency (Yahoo's terms do not permit this use), so the chain provider reports "unavailable" instead of
# inventing strikes. The greeks/IV math above works on any chain row the owner supplies.
def options_chain(symbol: str) -> dict:
    return {"symbol": symbol.upper(), "status": "unavailable", "rows": [],
            "reason": "no options-chain data source configured (yfinance not a dependency; licensed/keyed provider required)",
            "execution_permission": "none"}
