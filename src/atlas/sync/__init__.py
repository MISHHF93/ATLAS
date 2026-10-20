"""Subsystem X: Cross-Asset Synchronization & Delta Hedging (`src/atlas/sync/`).

Implements cross-asset beta-adjusted delta hedging between U.S. Equities (`SPY`, `QQQ`, `NVDA`)
and 24/7 Crypto Perpetuals (`BTC-USD`, `ETH-USD`) (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class CrossAssetDeltaHedgeReport(Record):
    """Cross-asset beta-adjusted hedge calculation between equity and crypto books."""

    primary_asset: Text
    hedge_instrument: Text
    primary_notional_usd: FiniteFloat
    cross_asset_beta: FiniteFloat
    realized_correlation: FiniteFloat
    required_hedge_notional_usd: FiniteFloat
    correlation_gate_passed: bool
    execution_permission: Literal["none"] = "none"


def compute_cross_asset_delta_hedge(
    primary_asset: str = "NVDA",
    hedge_instrument: str = "BTC-USD",
    *,
    primary_notional_usd: float = 50_000.0,
    cross_asset_beta: float = 0.62,
    realized_correlation: float = 0.58,
    max_correlation_cap: float = 0.80,
) -> CrossAssetDeltaHedgeReport:
    """Compute required beta-adjusted cross-asset hedge notional and correlation gate compliance."""
    hedge_notional = round(-float(primary_notional_usd) * float(cross_asset_beta), 2)
    return CrossAssetDeltaHedgeReport(
        primary_asset=primary_asset,
        hedge_instrument=hedge_instrument,
        primary_notional_usd=primary_notional_usd,
        cross_asset_beta=cross_asset_beta,
        realized_correlation=realized_correlation,
        required_hedge_notional_usd=hedge_notional,
        correlation_gate_passed=abs(realized_correlation) <= max_correlation_cap,
    )


__all__ = ["CrossAssetDeltaHedgeReport", "compute_cross_asset_delta_hedge"]

