"""Global Multi-Domain Architecture — CME Index & Commodity Futures (`src/atlas/marketdata/futures.py`).

Covers CME Aurora / Globex MDP3, Rithmic & CQG gateways, Sunday–Friday 17:00–16:00 CT
sessions, L3 MBO / Tick-by-Tick depth reconstruction, intraday trailing drawdown during
open trades, and Hybrid B-Book with internal cross-trader netting (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class CmeFuturesDomainProfile(Record):
    """Domain specification and intraday trailing HWM evaluation for CME Futures."""

    contract_symbol: Text
    gateway: Literal["cme_mdp3", "rithmic", "cqg"] = "cme_mdp3"
    session_window: Text = "Sunday-Friday 17:00-16:00 CT (Daily 1h maintenance)"
    data_granularity: Text = "L3 MBO / Tick-by-Tick"
    intraday_open_hwm_usd: FiniteFloat = Field(gt=0)
    current_open_equity_usd: FiniteFloat = Field(gt=0)
    trailing_drawdown_floor_usd: FiniteFloat = Field(gt=0)
    trailing_cushion_usd: FiniteFloat
    dealing_desk_routing: Literal["hybrid_b_book_internal_netting", "a_book_cme_hedge"]
    execution_permission: Literal["none"] = "none"


def evaluate_cme_futures_domain(
    contract_symbol: str,
    *,
    intraday_open_hwm_usd: float = 103_500.0,
    current_open_equity_usd: float = 102_100.0,
    max_trailing_dd_fraction: float = 0.04,
    net_desk_imbalance_contracts: int = 3,
) -> CmeFuturesDomainProfile:
    """Evaluate CME futures intraday open-equity trailing drawdown floor and B-Book netting."""
    floor_usd = round(intraday_open_hwm_usd * (1.0 - max_trailing_dd_fraction), 2)
    cushion = round(current_open_equity_usd - floor_usd, 2)
    routing: Literal["hybrid_b_book_internal_netting", "a_book_cme_hedge"] = (
        "a_book_cme_hedge" if abs(net_desk_imbalance_contracts) >= 10 else "hybrid_b_book_internal_netting"
    )
    return CmeFuturesDomainProfile(
        contract_symbol=contract_symbol.upper(),
        intraday_open_hwm_usd=intraday_open_hwm_usd,
        current_open_equity_usd=current_open_equity_usd,
        trailing_drawdown_floor_usd=floor_usd,
        trailing_cushion_usd=cushion,
        dealing_desk_routing=routing,
    )

