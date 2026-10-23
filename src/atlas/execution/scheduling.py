"""Pre-trade impact, Almgren-Chriss scheduling, crypto POV, arrival-price slippage (research item 16/17).
PAPER ONLY: these produce child-order PLANS and measurements; every child still goes through the
risk gate and the paper broker. Nothing here can enlarge a parent order (sum(children) == parent).

Impact (square-root law): cost_bps = spread/2 + Y * sigma_daily * sqrt(Q/ADV) * 1e4, with a
conservative venue haircut multiplier (paper fills understate impact; TSXV/illiquid worst)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

VENUE_HAIRCUT = {"TSX": 1.25, "TSXV": 2.0, "NYSE": 1.1, "NASDAQ": 1.1, "CRYPTO": 1.5}
POV_HARD_MAX = 0.10


def pre_trade_impact_bps(qty: float, adv: float, sigma_daily: float, spread_bps: float, Y: float = 0.8,
                         venue: str = "TSX") -> dict:
    if adv <= 0:
        return {"total_bps": float("inf"), "participation": float("inf"), "reason": "no ADV -> do not trade"}
    part = abs(qty) / adv
    impact = Y * sigma_daily * math.sqrt(part) * 1e4
    h = VENUE_HAIRCUT.get(venue.upper(), 1.5)
    return {"spread_bps": spread_bps / 2, "impact_bps": impact * h, "total_bps": spread_bps / 2 + impact * h,
            "participation": part, "haircut": h}


def almgren_chriss(X: float, T_days: float, N: int, sigma_daily: float, eta: float, gamma: float = 0.0,
                   risk_aversion: float = 1e-6, price: float = 1.0) -> dict:
    """Optimal liquidation trajectory (Almgren & Chriss 2000), linear temporary impact eta (price per
    share/day), permanent gamma. Returns holdings x_k, trade sizes n_k (sum = X), E[cost], Var[cost]."""
    tau = T_days / N
    sig = sigma_daily * price
    eta_t = eta - 0.5 * gamma * tau
    if eta_t <= 0:
        raise ValueError("eta too small relative to gamma*tau")
    k2 = risk_aversion * sig ** 2 / eta_t
    kappa = math.acosh(1 + 0.5 * k2 * tau ** 2) / tau if k2 > 0 else 0.0
    t = np.arange(N + 1) * tau
    if kappa * T_days < 1e-8:
        x = X * (1 - t / T_days)                     # TWAP limit (risk-neutral)
    else:
        x = X * np.sinh(kappa * (T_days - t)) / math.sinh(kappa * T_days)
    n = -np.diff(x)
    n[-1] += X - n.sum()                             # exact conservation
    e = 0.5 * gamma * X ** 2 + eta_t / tau * float((n ** 2).sum())
    v = sig ** 2 * tau * float((x[1:] ** 2).sum())
    return {"holdings": x, "trades": n, "expected_cost": e, "variance": v, "kappa": kappa}


@dataclass
class POVPlan:
    children: list[float]
    participation: float
    unfilled: float


def pov_schedule(parent_qty: float, interval_volumes: list[float], participation: float = 0.07, min_child: float = 0.0) -> POVPlan:
    """Crypto POV: child_i = min(remaining, rate * market volume in interval i). Rate hard-capped at
    10%. Anything not done within the horizon is left UNFILLED (never forced)."""
    rate = min(max(participation, 0.0), POV_HARD_MAX)
    rem, kids = abs(parent_qty), []
    for v in interval_volumes:
        q = min(rem, rate * max(v, 0.0))
        if q < min_child:
            q = 0.0
        kids.append(math.copysign(q, parent_qty) if q else 0.0)
        rem -= q
        if rem <= 1e-12:
            break
    return POVPlan(kids, rate, math.copysign(rem, parent_qty) if rem > 1e-12 else 0.0)


def arrival_slippage_bps(side: str, arrival_price: float, fills: list[tuple[float, float]], fees: float = 0.0,
                         intended_qty: float | None = None, close_price: float | None = None) -> dict:
    """Implementation shortfall vs arrival (decision) price. fills: [(qty, price)].
    Positive = cost. Includes opportunity cost on the unfilled part when close_price is given."""
    s = 1 if side.lower() == "buy" else -1
    q = sum(f[0] for f in fills)
    if q <= 0:
        return {"filled_qty": 0.0, "slippage_bps": 0.0, "fees_bps": 0.0, "opportunity_bps": 0.0, "shortfall_bps": 0.0}
    vwap = sum(f[0] * f[1] for f in fills) / q
    slip = s * (vwap - arrival_price) / arrival_price * 1e4
    fee_bps = fees / (q * arrival_price) * 1e4
    opp = 0.0
    if intended_qty and close_price is not None and intended_qty > q:
        opp = s * (close_price - arrival_price) / arrival_price * 1e4 * (intended_qty - q) / intended_qty
    return {"filled_qty": q, "vwap": vwap, "slippage_bps": slip, "fees_bps": fee_bps, "opportunity_bps": opp,
            "shortfall_bps": slip * q / (intended_qty or q) + fee_bps + opp}


class SlippageMonitor:
    """Rolling live(paper)-vs-model slippage for the drift / autonomy evidence."""

    def __init__(self):
        self.rows: list[dict] = []

    def record(self, symbol: str, predicted_bps: float, realised: dict) -> None:
        self.rows.append({"symbol": symbol, "pred": predicted_bps, "real": realised["shortfall_bps"]})

    def summary(self) -> dict:
        if not self.rows:
            return {"n": 0}
        p = np.array([r["pred"] for r in self.rows]); r = np.array([r["real"] for r in self.rows])
        return {"n": len(r), "mean_pred_bps": float(p.mean()), "mean_real_bps": float(r.mean()),
                "underestimate_ratio": float(r.mean() / p.mean()) if p.mean() > 0 else float("nan")}
