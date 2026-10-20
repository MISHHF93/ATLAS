"""Global Multi-Domain Architecture — Synthetic Indices (`src/atlas/marketdata/synthetics.py`).

Covers Proprietary Cryptographically Auditable Feeds / B2Broker continuous 24/7/365
tick-by-tick synthetic generation, high-frequency gap rules, and 100% B-Book
internalization with Sybil/latency-arbitrage guards (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Probability, Record, Text


class SyntheticIndicesDomainProfile(Record):
    """Domain specification and anti-latency-arbitrage verification for Synthetic Indices."""

    index_symbol: Text
    session_window: Text = "Continuous 24/7/365"
    data_granularity: Text = "Tick-by-Tick synthetic generation"
    target_annualized_volatility: FiniteFloat = Field(gt=0)
    sybil_latency_arb_score: Probability
    gap_rule_compliant: bool
    dealing_desk_routing: Literal["b_book_100pct_internalized"] = "b_book_100pct_internalized"
    execution_permission: Literal["none"] = "none"


def evaluate_synthetic_index_domain(
    index_symbol: str = "VOL-75-INDEX",
    *,
    target_annualized_volatility: float = 0.75,
    sybil_latency_arb_score: float = 0.02,
    max_tick_gap_bps: float = 18.0,
) -> SyntheticIndicesDomainProfile:
    """Evaluate synthetic index tick-gap rules and Sybil/latency-arbitrage cleanliness."""
    clean_score = max(0.0, min(1.0, float(sybil_latency_arb_score)))
    gap_ok = max_tick_gap_bps <= 50.0 and clean_score < 0.25
    return SyntheticIndicesDomainProfile(
        index_symbol=index_symbol.upper(),
        target_annualized_volatility=target_annualized_volatility,
        sybil_latency_arb_score=round(clean_score, 6),
        gap_rule_compliant=gap_ok,
    )

