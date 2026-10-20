"""Subsystem A: Allocation & Portfolio Construction (`src/atlas/portfolio/`).

Implements:
1. Fractional Kelly Criterion sizing (`f* = k_frac * (mu - r_f) / sigma^2`)
2. Inverse-Volatility Risk Parity weights (`w_i = (1 / sigma_i) / sum_j (1 / sigma_j)`)
3. Mean-Variance Diagonal Tangency allocation (`w_i propto mu_i / sigma_i^2`)
All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Probability, Record, Text


class PortfolioAllocationReport(Record):
    """Multi-asset portfolio construction report across Kelly, Risk Parity, and Mean-Variance."""

    symbols: tuple[Text, ...]
    risk_parity_weights: tuple[Probability, ...]
    mean_variance_weights: tuple[Probability, ...]
    fractional_kelly_leverages: tuple[FiniteFloat, ...]
    kelly_fraction_multiplier: Probability = 0.25
    expected_portfolio_return: FiniteFloat
    expected_portfolio_volatility: FiniteFloat = Field(ge=0)
    execution_permission: Literal["none"] = "none"


def compute_portfolio_allocation(
    symbols: tuple[str, ...] | list[str],
    expected_returns: tuple[float, ...] | list[float],
    volatilities: tuple[float, ...] | list[float],
    *,
    kelly_fraction: float = 0.25,
    max_asset_leverage: float = 1.50,
) -> PortfolioAllocationReport:
    """Compute Risk Parity, Mean-Variance, and Fractional Kelly allocations across assets."""
    if not symbols or len(symbols) != len(expected_returns) or len(symbols) != len(volatilities):
        raise ValueError("symbols, expected_returns, and volatilities must be non-empty and of equal length")
    if any(v <= 0 for v in volatilities):
        raise ValueError("All asset volatilities must be strictly positive")

    n = len(symbols)
    inv_vols = [1.0 / float(v) for v in volatilities]
    inv_vol_sum = sum(inv_vols)
    rp_weights = [round(iv / inv_vol_sum, 6) for iv in inv_vols]

    # Normalize RP weights so sum == 1.0 within rounding
    rp_diff = round(1.0 - sum(rp_weights), 6)
    rp_weights[0] = round(max(0.0, min(1.0, rp_weights[0] + rp_diff)), 6)

    raw_mv = [max(0.0, float(expected_returns[i])) / (float(volatilities[i]) ** 2) for i in range(n)]
    mv_sum = sum(raw_mv)
    if mv_sum > 1e-12:
        mv_weights = [round(x / mv_sum, 6) for x in raw_mv]
        mv_diff = round(1.0 - sum(mv_weights), 6)
        mv_weights[0] = round(max(0.0, min(1.0, mv_weights[0] + mv_diff)), 6)
    else:
        mv_weights = list(rp_weights)

    kelly_levs = [
        round(
            max(-max_asset_leverage, min(max_asset_leverage, float(kelly_fraction) * (float(expected_returns[i]) / (float(volatilities[i]) ** 2)))),
            6,
        )
        for i in range(n)
    ]

    port_ret = sum(rp_weights[i] * float(expected_returns[i]) for i in range(n))
    port_vol = (sum((rp_weights[i] * float(volatilities[i])) ** 2 for i in range(n))) ** 0.5

    return PortfolioAllocationReport(
        symbols=tuple(str(s) for s in symbols),
        risk_parity_weights=tuple(rp_weights),
        mean_variance_weights=tuple(mv_weights),
        fractional_kelly_leverages=tuple(kelly_levs),
        kelly_fraction_multiplier=kelly_fraction,
        expected_portfolio_return=round(port_ret, 6),
        expected_portfolio_volatility=round(port_vol, 6),
    )


__all__ = ["PortfolioAllocationReport", "compute_portfolio_allocation"]

