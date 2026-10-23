"""Snapback Entry Strategy implementation for ATLAS.

Implements a deterministic state machine to detect the sequence:
Opening Box established -> Breakout -> Retest -> Confirmation -> Qualified.

This strategy relies on the ZoneEngine for structural boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Literal, Optional
import pandas as pd

from atlas.features.zones import ZoneEngine, ZoneType, PriceZone, ZoneDirection
from atlas.models.schemas import Record, Text


class SnapbackState(Enum):
    AWAITING_BREAKOUT = auto()
    AWAITING_RETEST = auto()
    AWAITING_CONFIRMATION = auto()
    QUALIFIED = auto()
    INVALIDATED = auto()
    EXPIRED = auto()


@dataclass
class SnapbackSetup(Record):
    """Represents a tracking instance of a Snapback setup attempt."""
    symbol: Text
    setup_id: Text
    initial_box: PriceZone
    state: SnapbackState = SnapbackState.AWAITING_BREAKOUT
    direction: Literal["long", "short"] | None = None
    breakout_time: Optional[datetime] = None
    retest_time: Optional[datetime] = None
    confirmation_time: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    execution_permission: Literal["none"] = "none"


class SnapbackDetector:
    """
    Deterministic setup detector for the Snapback Entry strategy.
    
    Tracks the progression of price relative to the Opening Box across
    multiple states to filter for high-quality retest entries.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.active_setup: SnapbackSetup | None = None

    def process_bars(self, df: pd.DataFrame, opening_box: PriceZone | None) -> SnapbackSetup | None:
        """
        Updates the state of the current Snapback setup based on price action.
        
        Args:
            df: DataFrame with OHLC data (last row is the most recent completed candle)
            opening_box: The current active Opening Box zone
        """
        if opening_box is None:
            return None

        # Initialize setup if none exists
        if self.active_setup is None:
            self.active_setup = SnapbackSetup(
                symbol=self.symbol,
                setup_id=f"snapback_{opening_box.start_time.strftime('%Y%m%d%H')}",
                initial_box=opening_box,
                state=SnapbackState.AWAITING_BREAKOUT
            )

        setup = self.active_setup
        last_candle = df.iloc[-1]
        close = last_candle['close']
        high = last_candle['high']
        low = last_candle['low']
        ts = last_candle['timestamp']

        # 1. AWAITING_BREAKOUT -> AWAITING_RETEST
        if setup.state == SnapbackState.AWAITING_BREAKOUT:
            if close > opening_box.boundary.high:
                setup.direction = "long"
                setup.state = SnapbackState.AWAITING_RETEST
                setup.breakout_time = ts
            elif close < opening_box.boundary.low:
                setup.direction = "short"
                setup.state = SnapbackState.AWAITING_RETEST
                setup.breakout_time = ts

        # 2. AWAITING_RETEST -> AWAITING_CONFIRMATION
        elif setup.state == SnapbackState.AWAITING_RETEST:
            if setup.direction == "long":
                # Retest: Price touches or enters the Opening Box from above
                if low <= opening_box.boundary.high:
                    setup.state = SnapbackState.AWAITING_CONFIRMATION
                    setup.retest_time = ts
            elif setup.direction == "short":
                # Retest: Price touches or enters the Opening Box from below
                if high >= opening_box.boundary.low:
                    setup.state = SnapbackState.AWAITING_CONFIRMATION
                    setup.retest_time = ts

        # 3. AWAITING_CONFIRMATION -> QUALIFIED
        elif setup.state == SnapbackState.AWAITING_CONFIRMATION:
            if setup.direction == "long":
                # Confirmation: Close back above the Opening Box High
                if close > opening_box.boundary.high:
                    setup.state = SnapbackState.QUALIFIED
                    setup.confirmation_time = ts
            elif setup.direction == "short":
                # Confirmation: Close back below the Opening Box Low
                if close < opening_box.boundary.low:
                    setup.state = SnapbackState.QUALIFIED
                    setup.confirmation_time = ts
            
            # Invalidation: Price closes on the opposite side of the Opening Box
            if (setup.direction == "long" and close < opening_box.boundary.low) or \
               (setup.direction == "short" and close > opening_box.boundary.high):
                setup.state = SnapbackState.INVALIDATED
                setup.invalidated_at = ts

        return setup if setup.state == SnapbackState.QUALIFIED else None

    def reset(self):
        """Resets the setup tracker (e.g., at the start of a new session)."""
        self.active_setup = None
