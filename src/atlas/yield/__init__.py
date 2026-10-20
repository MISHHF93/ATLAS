"""Subsystem Y: Yield & Funding Rate Arbitrage (`src/atlas/yield/`).

Implements cash-and-carry perpetual basis capture vs. overnight Treasury repo yield
(`execution_permission = "none"`). Accessible via `importlib.import_module("atlas.yield")`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import FiniteFloat

from atlas.models.schemas import Record, Text


class BasisFundingArbitrageReport(Record):
    """Cash-and-carry perpetual funding rate vs overnight repo rate spread report."""

    instrument_id: Text
    perp_funding_annualized_pct: FiniteFloat
    overnight_repo_rate_pct: FiniteFloat
    net_basis_carry_spread_pct: FiniteFloat
    arbitrage_attractive: bool
    execution_permission: Literal["none"] = "none"


def evaluate_basis_funding_arbitrage(
    instrument_id: str = "BTC-PERP",
    *,
    funding_rate_8h_bps: float = 1.45,
    overnight_repo_rate_pct: float = 4.85,
    round_trip_fee_pct: float = 0.35,
) -> BasisFundingArbitrageReport:
    """Evaluate annualized cash-and-carry basis spread net of repo financing and fees."""
    gross_ann_pct = (float(funding_rate_8h_bps) / 10_000.0) * 3.0 * 365.0 * 100.0
    net_spread = round(gross_ann_pct - float(overnight_repo_rate_pct) - float(round_trip_fee_pct), 4)
    return BasisFundingArbitrageReport(
        instrument_id=instrument_id,
        perp_funding_annualized_pct=round(gross_ann_pct, 4),
        overnight_repo_rate_pct=overnight_repo_rate_pct,
        net_basis_carry_spread_pct=net_spread,
        arbitrage_attractive=net_spread >= 3.0,
    )


__all__ = ["BasisFundingArbitrageReport", "evaluate_basis_funding_arbitrage"]

