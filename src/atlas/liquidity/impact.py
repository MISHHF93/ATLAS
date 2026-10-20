"""WF-01 & Subsystem L: Kyle's Lambda Price Impact & L2/L3 Liquidity Depth Reconstruction (`src/atlas/liquidity/impact.py`).

Implements:
- WF-01: Kyle's Lambda (Delta P_t = lambda * Q_t + eta_t) via rolling OLS (`estimate_kyles_lambda`)
- L2/L3 Order Book Depth Reconstruction & Market Impact Cost Estimator (`estimate_l2_market_impact`)
All outputs preserve `execution_permission = "none"`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.marketdata.microstructure import (
    BookLevelSnapshot,
    KylesLambdaResult,
    estimate_kyles_lambda,
)
from atlas.models.schemas import Record


class L2MarketImpactReport(Record):
    """L2/L3 depth sweep and temporary/permanent market impact estimate."""

    order_quantity: FiniteFloat = Field(gt=0)
    side: Literal["buy", "sell"]
    mid_price: FiniteFloat = Field(gt=0)
    vwap_fill_price: FiniteFloat = Field(gt=0)
    slippage_bps: FiniteFloat = Field(ge=0)
    levels_swept: int = Field(ge=1)
    unfilled_quantity: FiniteFloat = Field(ge=0)
    execution_permission: Literal["none"] = "none"


def estimate_l2_market_impact(
    book_levels: tuple[BookLevelSnapshot, ...] | list[BookLevelSnapshot],
    *,
    order_quantity: float,
    side: Literal["buy", "sell"] = "buy",
) -> L2MarketImpactReport:
    """Reconstruct L2/L3 depth sweep to compute exact VWAP fill price and slippage in bps."""
    if not book_levels:
        raise ValueError("book_levels must be non-empty")
    if order_quantity <= 0:
        raise ValueError("order_quantity must be strictly positive")

    mid_px = 0.5 * (float(book_levels[0].bid_price) + float(book_levels[0].ask_price))
    remaining = float(order_quantity)
    notional_accum = 0.0
    filled_accum = 0.0
    levels_used = 0

    for lvl in book_levels:
        px = float(lvl.ask_price) if side == "buy" else float(lvl.bid_price)
        avail = float(lvl.ask_size) if side == "buy" else float(lvl.bid_size)
        if avail <= 0:
            continue
        take = min(remaining, avail)
        notional_accum += take * px
        filled_accum += take
        remaining -= take
        levels_used += 1
        if remaining <= 1e-9:
            break

    vwap_px = (notional_accum / filled_accum) if filled_accum > 0 else mid_px
    raw_slip_bps = ((vwap_px - mid_px) / mid_px) * 10_000.0 if side == "buy" else ((mid_px - vwap_px) / mid_px) * 10_000.0

    return L2MarketImpactReport(
        order_quantity=round(float(order_quantity), 6),
        side=side,
        mid_price=round(mid_px, 6),
        vwap_fill_price=round(vwap_px, 6),
        slippage_bps=round(max(0.0, raw_slip_bps), 4),
        levels_swept=max(1, levels_used),
        unfilled_quantity=round(max(0.0, remaining), 6),
    )


__all__ = [
    "BookLevelSnapshot",
    "KylesLambdaResult",
    "L2MarketImpactReport",
    "estimate_kyles_lambda",
    "estimate_l2_market_impact",
]

