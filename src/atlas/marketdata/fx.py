"""Global Multi-Domain Architecture — Global FX & CFDs (`src/atlas/marketdata/fx.py`).

Covers LMAX / Currenex / cTrader / EBS gateways, Sunday 17:00 – Friday 17:00 ET sessions,
L1 BBO & Multi-LP L2 Depth, weekend holding bans, and B-Book internalization with
VPIN-triggered A-Book exhaust (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import FiniteFloat

from atlas.models.schemas import Probability, Record, Text


class GlobalFxDomainProfile(Record):
    """Domain specification and B-Book/A-Book routing decision for Global FX & CFDs."""

    pair: Text
    gateway: Literal["lmax", "currenex", "ctrader", "ebs"] = "lmax"
    session_window: Text = "Sunday 17:00 - Friday 17:00 ET"
    weekend_holding_permitted: bool = False
    vpin_toxicity: Probability
    spread_pips: FiniteFloat
    dealing_desk_routing: Literal["b_book_internalization", "a_book_lp_exhaust"]
    execution_permission: Literal["none"] = "none"


def evaluate_fx_cfd_domain(
    pair: str = "EUR/USD",
    *,
    vpin_toxicity: float = 0.28,
    spread_pips: float = 0.4,
    vpin_exhaust_threshold: float = 0.45,
) -> GlobalFxDomainProfile:
    """Evaluate FX/CFD dealing-desk routing between B-Book internalization and A-Book exhaust."""
    clean_vpin = max(0.0, min(1.0, float(vpin_toxicity)))
    routing: Literal["b_book_internalization", "a_book_lp_exhaust"] = (
        "a_book_lp_exhaust" if clean_vpin >= vpin_exhaust_threshold else "b_book_internalization"
    )
    return GlobalFxDomainProfile(
        pair=pair.upper(),
        vpin_toxicity=round(clean_vpin, 6),
        spread_pips=round(float(spread_pips), 4),
        dealing_desk_routing=routing,
    )

