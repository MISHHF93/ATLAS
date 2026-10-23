"""Sleeve allocation helpers (60/30/10). Rebalancing is M4."""
from __future__ import annotations

from atlas.control.policy.schemas import RiskPolicy
from atlas.risk.models import PortfolioState


def sleeve_targets(policy: RiskPolicy, bot_capital: float) -> dict[str, float]:
    return {k: s.target_pct / 100 * bot_capital for k, s in policy.sleeves.items()}


def sleeve_drift_pp(policy: RiskPolicy, state: PortfolioState, bot_capital: float) -> dict[str, float]:
    if bot_capital <= 0:
        return {k: 0.0 for k in policy.sleeves}
    return {k: state.sleeve_exposure(k) / bot_capital * 100 - s.target_pct for k, s in policy.sleeves.items()}
