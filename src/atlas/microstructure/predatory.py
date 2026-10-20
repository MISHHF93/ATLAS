"""WF-06: Cross-Impact & Predatory Liquidation Trigger (`src/atlas/microstructure/predatory.py`).

Implements the non-linear square-root cross-impact & whale liquidation model:
    Delta P_predatory = gamma * sqrt(Volume_whale / ADV) * sgn(Side)
When Volume_whale / ADV >= 0.05 (5% ADV threshold), flags a predatory liquidation cascade.
All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record


class PredatoryLiquidationReport(Record):
    """Square-root impact model report for large whale block/liquidation flow."""

    whale_volume: FiniteFloat = Field(gt=0)
    average_daily_volume: FiniteFloat = Field(gt=0)
    participation_ratio: FiniteFloat = Field(gt=0)
    cross_impact_gamma: FiniteFloat = Field(gt=0)
    side: Literal["buy", "sell"]
    predicted_impact_bps: FiniteFloat
    predatory_liquidation_alert: bool
    recommended_defense: Literal["hedge_momentum_and_widen_stop", "normal_passive_quoting"]
    execution_permission: Literal["none"] = "none"


def evaluate_predatory_liquidation(
    whale_volume: float,
    average_daily_volume: float,
    *,
    cross_impact_gamma: float = 0.35,
    side: Literal["buy", "sell"] = "sell",
    adv_alert_threshold: float = 0.05,
) -> PredatoryLiquidationReport:
    """Compute Delta P_predatory = gamma * sqrt(V_whale / ADV) * sgn(Side)."""
    if whale_volume <= 0 or average_daily_volume <= 0 or cross_impact_gamma <= 0:
        raise ValueError("whale_volume, average_daily_volume, and cross_impact_gamma must be strictly positive")

    participation = float(whale_volume) / float(average_daily_volume)
    sign = 1.0 if side == "buy" else -1.0
    impact_frac = cross_impact_gamma * math.sqrt(participation) * sign
    impact_bps = round(impact_frac * 10_000.0, 4)
    alert = participation >= adv_alert_threshold

    return PredatoryLiquidationReport(
        whale_volume=round(float(whale_volume), 4),
        average_daily_volume=round(float(average_daily_volume), 4),
        participation_ratio=round(participation, 6),
        cross_impact_gamma=cross_impact_gamma,
        side=side,
        predicted_impact_bps=impact_bps,
        predatory_liquidation_alert=alert,
        recommended_defense="hedge_momentum_and_widen_stop" if alert else "normal_passive_quoting",
    )

