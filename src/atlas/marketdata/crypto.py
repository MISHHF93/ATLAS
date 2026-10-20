"""Global Multi-Domain Architecture — 24/7 Crypto Spot & Perpetuals (`src/atlas/marketdata/crypto.py`).

Covers Binance / Coinbase / Hyperliquid continuous 24/7/365 sessions, L2 10-level Depth,
8h/1h perpetual funding rate cycles, funding liquidation risk, and dynamic perpetual
delta hedging (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class CryptoPerpDomainProfile(Record):
    """Domain specification and funding-rate delta-hedge advisory for 24/7 Crypto Perps."""

    instrument_id: Text
    venue: Literal["coinbase_advanced", "binance_futures", "hyperliquid"] = "coinbase_advanced"
    session_window: Text = "Continuous 24/7/365"
    data_granularity: Text = "L2 10-level Depth, Funding rate 8h/1h"
    funding_rate_8h_bps: FiniteFloat
    annualized_funding_yield_pct: FiniteFloat
    delta_hedge_notional_usd: FiniteFloat = Field(ge=0)
    dealing_desk_routing: Literal["dynamic_perp_delta_hedge"] = "dynamic_perp_delta_hedge"
    execution_permission: Literal["none"] = "none"


def evaluate_crypto_perp_domain(
    instrument_id: str,
    *,
    funding_rate_8h_bps: float = 1.25,
    net_long_short_delta_usd: float = 45_000.0,
) -> CryptoPerpDomainProfile:
    """Compute annualized perpetual funding carry and required dynamic delta-hedge notional."""
    ann_yield_pct = round((funding_rate_8h_bps / 10_000.0) * 3.0 * 365.0 * 100.0, 4)
    return CryptoPerpDomainProfile(
        instrument_id=instrument_id,
        funding_rate_8h_bps=round(funding_rate_8h_bps, 4),
        annualized_funding_yield_pct=ann_yield_pct,
        delta_hedge_notional_usd=round(abs(net_long_short_delta_usd), 2),
    )

