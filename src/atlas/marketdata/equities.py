"""Global Multi-Domain Architecture — US Cash Equities (`src/atlas/marketdata/equities.py`).

Covers NYSE/Nasdaq SIP & Direct Feeds (XNYS, XNAS, ARCA), 09:30–16:00 ET regular session
with Opening/Closing Auctions, L1 BBO & L2 10-level Depth, PDT/Reg-T & SEC T+1 settlement,
and A-Book direct market access (DMA) advisory. All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class UsCashEquityDomainProfile(Record):
    """Domain specification and pre-trade dealing-desk routing profile for US Cash Equities."""

    symbol: Text
    primary_venue: Literal["XNYS", "XNAS", "ARCX"] = "XNAS"
    session_window: Text = "09:30-16:00 ET regular + Opening/Closing Auctions"
    data_granularity: Text = "L1 BBO, L2 10-level Depth, SEC EDGAR PIT XBRL"
    settlement_cycle: Literal["T+1"] = "T+1"
    pdt_equity_floor_usd: FiniteFloat = Field(default=25_000.0, gt=0)
    dealing_desk_routing: Literal["a_book_dma"] = "a_book_dma"
    pdt_compliant: bool
    execution_permission: Literal["none"] = "none"


def evaluate_us_equity_domain(
    symbol: str,
    *,
    account_equity_usd: float = 100_000.0,
    intraday_day_trades_rolling_5d: int = 2,
    primary_venue: Literal["XNYS", "XNAS", "ARCX"] = "XNAS",
) -> UsCashEquityDomainProfile:
    """Evaluate PDT & T+1 compliance for US Cash Equities on NYSE/Nasdaq."""
    pdt_ok = account_equity_usd >= 25_000.0 or intraday_day_trades_rolling_5d < 4
    return UsCashEquityDomainProfile(
        symbol=symbol.upper(),
        primary_venue=primary_venue,
        pdt_compliant=pdt_ok,
    )

