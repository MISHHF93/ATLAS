"""Price Action Zone Engine for ATLAS.

Implements the detection and tracking of Opening, Breakout, Anchor, and Event boxes.
These zones are used as structural markers for strategy detection and ML features.

All zone calculations are performed with a strict 'as-of' discipline to prevent lookahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Literal, NamedTuple
import pandas as pd
import numpy as np

from atlas.models.schemas import Record, Text


class ZoneType(Enum):
    OPENING = auto()
    BREAKOUT = auto()
    ANCHOR = auto()
    EVENT = auto()


class ZoneDirection(Enum):
    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()


@dataclass(frozen=False)
class ZoneBoundary:
    high: float
    low: float
    
    @property
    def height(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class PriceZone(Record):
    """A detected structural zone in the market."""
    zone_id: Text
    symbol: Text
    zone_type: ZoneType
    direction: ZoneDirection
    boundary: ZoneBoundary
    start_time: datetime
    end_time: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_permission: Literal["none"] = "none"


class ZoneEngine:
    """
    Engine for detecting and updating Price Action Zones.
    
    This engine processes OHLC data to identify Opening, Breakout, Anchor, and Event boxes
    based on the ATLAS Price Action Framework specifications.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.active_zones: dict[ZoneType, PriceZone | None] = {
            zt: None for zt in ZoneType
        }

    def detect_opening_box(self, df: pd.DataFrame, session_start: datetime) -> PriceZone | None:
        """
        Detects the Opening Box: high/low of the first 1-hour candle of a session.
        
        Args:
            df: DataFrame with 'timestamp', 'high', 'low'
            session_start: The start time of the trading session (UTC)
        """
        # Filter for the first hour of the session
        session_end = session_start + pd.Timedelta(hours=1)
        mask = (df['timestamp'] >= session_start) & (df['timestamp'] < session_end)
        hour_data = df.loc[mask]
        
        if hour_data.empty:
            return None
            
        high = float(hour_data['high'].max())
        low = float(hour_data['low'].min())
        
        zone = PriceZone(
            zone_id=f"opening_{session_start.strftime('%Y%m%d%H')}",
            symbol=self.symbol,
            zone_type=ZoneType.OPENING,
            direction=ZoneDirection.NEUTRAL,
            boundary=ZoneBoundary(high, low),
            start_time=session_start,
            end_time=session_end
        )
        return zone

    def detect_breakout_box(self, df: pd.DataFrame) -> PriceZone | None:
        """
        Detects the Breakout Box using Double Bollinger Band piercing.
        
        BB1: Length 20, StdDev 2, Source: Close
        BB2: Length 4, StdDev 4, Source: Open
        """
        if len(df) < 20:
            return None
            
        # BB1 (Close)
        close = df['close']
        ma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        bb1_upper = ma20 + (2 * std20)
        bb1_lower = ma20 - (2 * std20)
        
        # BB2 (Open)
        open_px = df['open']
        ma4 = open_px.rolling(window=4).mean()
        std4 = open_px.rolling(window=4).std()
        bb2_upper = ma4 + (4 * std4)
        bb2_lower = ma4 - (4 * std4)
        
        last_idx = -1
        # Bullish Trigger
        if (close.iloc[last_idx] > bb1_upper.iloc[last_idx] and 
            close.iloc[last_idx] > bb2_upper.iloc[last_idx]):
            
            return PriceZone(
                zone_id=f"breakout_bull_{df['timestamp'].iloc[last_idx]}",
                symbol=self.symbol,
                zone_type=ZoneType.BREAKOUT,
                direction=ZoneDirection.BULLISH,
                boundary=ZoneBoundary(df['high'].iloc[last_idx], df['low'].iloc[last_idx]),
                start_time=df['timestamp'].iloc[last_idx],
                end_time=df['timestamp'].iloc[last_idx]
            )
            
        # Bearish Trigger
        if (close.iloc[last_idx] < bb1_lower.iloc[last_idx] and 
            close.iloc[last_idx] < bb2_lower.iloc[last_idx]):
            
            return PriceZone(
                zone_id=f"breakout_bear_{df['timestamp'].iloc[last_idx]}",
                symbol=self.symbol,
                zone_type=ZoneType.BREAKOUT,
                direction=ZoneDirection.BEARISH,
                boundary=ZoneBoundary(df['high'].iloc[last_idx], df['low'].iloc[last_idx]),
                start_time=df['timestamp'].iloc[last_idx],
                end_time=df['timestamp'].iloc[last_idx]
            )
            
        return None

    def detect_anchor_box(self, df: pd.DataFrame) -> PriceZone | None:
        """
        Detects Anchor Boxes: swing extreme followed by reversal.
        """
        if len(df) < 3:
            return None
            
        # Simplified swing detection: local extremum
        # Bullish: low < prev_low AND low < next_low AND close > open (Hammer-like)
        # Since this is real-time, we check for the completion of the reversal candle
        
        # Check last 2 candles
        c1 = df.iloc[-2] # potential swing
        c2 = df.iloc[-1] # reversal candle
        
        # Bullish Anchor
        if c1['low'] < c2['low'] and c2['close'] > c2['open']:
            return PriceZone(
                zone_id=f"anchor_bull_{c2['timestamp']}",
                symbol=self.symbol,
                zone_type=ZoneType.ANCHOR,
                direction=ZoneDirection.BULLISH,
                boundary=ZoneBoundary(c2['close'], c1['low']),
                start_time=c1['timestamp'],
                end_time=c2['timestamp'],
                metadata={},
                execution_permission="none"
            )
            
        # Bearish Anchor
        if c1['high'] > c2['high'] and c2['close'] < c2['open']:
            return PriceZone(
                zone_id=f"anchor_bear_{c2['timestamp']}",
                symbol=self.symbol,
                zone_type=ZoneType.ANCHOR,
                direction=ZoneDirection.BEARISH,
                boundary=ZoneBoundary(c1['high'], c2['close']),
                start_time=c1['timestamp'],
                end_time=c2['timestamp'],
                metadata={},
                execution_permission="none"
            )
            
        return None

    def detect_event_box(self, df: pd.DataFrame, event_time: datetime) -> PriceZone | None:
        """
        Detects Event Box: range of 1-hour candle around an economic event.
        """
        # Align to the start of the hour containing the event
        event_hour_start = event_time.replace(minute=0, second=0, microsecond=0)
        event_hour_end = event_hour_start + pd.Timedelta(hours=1)
        
        mask = (df['timestamp'] >= event_hour_start) & (df['timestamp'] < event_hour_end)
        event_data = df.loc[mask]
        
        if event_data.empty:
            return None
            
        high = float(event_data['high'].max())
        low = float(event_data['low'].min())
        
        return PriceZone(
            zone_id=f"event_{event_time.strftime('%Y%m%d%H%M')}",
            symbol=self.symbol,
            zone_type=ZoneType.EVENT,
            direction=ZoneDirection.NEUTRAL,
            boundary=ZoneBoundary(high, low),
            start_time=event_hour_start,
            end_time=event_hour_end
        )

    def update_zones(self, df: pd.DataFrame, session_start: datetime | None = None, event_time: datetime | None = None) -> dict[ZoneType, PriceZone | None]:
        """Updates all active zones for the symbol."""
        if session_start:
            self.active_zones[ZoneType.OPENING] = self.detect_opening_box(df, session_start)
            
        self.active_zones[ZoneType.BREAKOUT] = self.detect_breakout_box(df)
        self.active_zones[ZoneType.ANCHOR] = self.detect_anchor_box(df)
        
        if event_time:
            self.active_zones[ZoneType.EVENT] = self.detect_event_box(df, event_time)
            
        return self.active_zones
