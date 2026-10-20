"""Subsystem V: Volatility Surfaces & Dynamic ATR Sizing (`src/atlas/volatility/`).

Implements ATR dynamic stop/position sizing and implied-vs-realized volatility surface
spread diagnostics (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class VolatilitySurfaceReport(Record):
    """Implied vs realized volatility spread and ATR dynamic position sizing report."""

    instrument_id: Text
    implied_vol_annualized: FiniteFloat = Field(gt=0)
    realized_vol_annualized: FiniteFloat = Field(gt=0)
    vol_risk_premium: FiniteFloat
    atr_bps: FiniteFloat = Field(gt=0)
    recommended_stop_bps: FiniteFloat = Field(gt=0)
    recommended_notional_usd: FiniteFloat = Field(gt=0)
    execution_permission: Literal["none"] = "none"


def compute_atr_dynamic_sizing(
    instrument_id: str,
    *,
    account_equity_usd: float = 100_000.0,
    risk_fraction: float = 0.005,
    atr_bps: float = 65.0,
    atr_stop_multiplier: float = 1.5,
    implied_vol: float = 0.42,
    realized_vol: float = 0.36,
) -> VolatilitySurfaceReport:
    """Compute dynamic ATR stop distance and fixed-fractional position notional."""
    stop_bps = round(max(15.0, float(atr_bps) * float(atr_stop_multiplier)), 4)
    risk_usd = float(account_equity_usd) * float(risk_fraction)
    notional = round((risk_usd * 10_000.0) / stop_bps, 2)
    return VolatilitySurfaceReport(
        instrument_id=instrument_id,
        implied_vol_annualized=implied_vol,
        realized_vol_annualized=realized_vol,
        vol_risk_premium=round(implied_vol - realized_vol, 6),
        atr_bps=atr_bps,
        recommended_stop_bps=stop_bps,
        recommended_notional_usd=notional,
    )


__all__ = ["VolatilitySurfaceReport", "compute_atr_dynamic_sizing"]

