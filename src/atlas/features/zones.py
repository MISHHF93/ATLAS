"""Price Action Zone Engine for ATLAS.

Implements the detection and tracking of Opening, Breakout, Anchor, and Event boxes.
These zones are used as structural markers for strategy detection and ML features.

All zone calculations are performed with a strict 'as-of' discipline to prevent lookahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Literal, NamedTuple
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

    def to_lifecycle_zone(self, timeframe: int, *, max_age_seconds: int | None = None):
        """Adapter onto the canonical ``atlas.features.price_action.Zone`` (lifecycle: touch/retest/invalidate/expire).

        New code should use ``atlas.features.price_action`` directly. ``ZoneEngine`` is a compatibility facade over
        price_action for its existing callers (snapback, coordinator, research trainer/backtester)."""
        from atlas.features.price_action.zones import Zone
        direction = {ZoneDirection.BULLISH: "bullish", ZoneDirection.BEARISH: "bearish"}.get(self.direction, "neutral")
        formed = int(self.end_time.timestamp())
        return Zone(instrument=self.symbol, timeframe=int(timeframe), zone_type=f"legacy_{self.zone_type.name.lower()}",
                    direction=direction, lower_bound=float(self.boundary.low), upper_bound=float(self.boundary.high),
                    formed_at=formed, confirmed_at=formed, source_event=self.zone_id,
                    feature_snapshot=dict(self.metadata), max_age_seconds=max_age_seconds)


def _bars_from_df(df: pd.DataFrame, duration: int = 3600):
    from atlas.features.price_action.bars import Bar
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return [Bar(int(t.timestamp()), duration, float(o), float(h), float(l), float(c))
            for t, o, h, l, c in zip(ts, df["open"], df["high"], df["low"], df["close"])]


def _pz(symbol: str, zid: str, zt: ZoneType, d: ZoneDirection, high: float, low: float, start, end,
        **meta: Any) -> PriceZone:
    return PriceZone(zone_id=zid, symbol=symbol, zone_type=zt, direction=d, boundary=ZoneBoundary(float(high), float(low)),
                     start_time=start, end_time=end, metadata={"engine": "atlas.features.price_action", **meta},
                     execution_permission="none")


class ZoneEngine:
    """Compatibility facade over ``atlas.features.price_action`` (same methods, same ``PriceZone`` results).

    - Opening box: high/low of the first hour after ``session_start`` (the price_action opening range).
    - Breakout box: dual Bollinger close-beyond on the last bar, using canonical ``bollinger_batch``
      (close 20/2 and open 4/4, population std, the same rule as ``DualBollingerDetector``). The pre-rewrite engine used
      pandas sample std (ddof=1); the canonical definition is population std.
    - Anchor box: legacy two-candle rule, unchanged, with ``candle_geometry`` attached as metadata.
    - Event box: high/low of the clock hour containing ``event_time``.
    Each returned zone can be moved onto the lifecycle model with ``PriceZone.to_lifecycle_zone``.
    The pre-rewrite engine raised TypeError when building opening, breakout and event zones (required fields were missing); that is fixed here."""

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.active_zones: dict[ZoneType, PriceZone | None] = {zt: None for zt in ZoneType}

    def _hour_box(self, df: pd.DataFrame, start, kind: ZoneType, zid: str) -> PriceZone | None:
        end = start + pd.Timedelta(hours=1)
        w = df.loc[(df["timestamp"] >= start) & (df["timestamp"] < end)]
        if w.empty:
            return None
        return _pz(self.symbol, zid, kind, ZoneDirection.NEUTRAL, w["high"].max(), w["low"].min(), start, end,
                   price_action_zone_type="opening_range" if kind is ZoneType.OPENING else "event_range")

    def detect_opening_box(self, df: pd.DataFrame, session_start: datetime) -> PriceZone | None:
        return self._hour_box(df, session_start, ZoneType.OPENING, f"opening_{session_start.strftime('%Y%m%d%H')}")

    def detect_breakout_box(self, df: pd.DataFrame) -> PriceZone | None:
        if len(df) < 20:
            return None
        from atlas.features.price_action.indicators import bollinger_batch
        a = bollinger_batch(df["close"].astype(float).tolist(), 20, 2.0)[-1]
        b = bollinger_batch(df["open"].astype(float).tolist(), 4, 4.0)[-1]
        if a is None or b is None:
            return None
        c = float(df["close"].iloc[-1])
        ts = df["timestamp"].iloc[-1]
        if c > a[2] and c > b[2]:
            d, tag = ZoneDirection.BULLISH, "bull"
        elif c < a[0] and c < b[0]:
            d, tag = ZoneDirection.BEARISH, "bear"
        else:
            return None
        return _pz(self.symbol, f"breakout_{tag}_{ts}", ZoneType.BREAKOUT, d, df["high"].iloc[-1], df["low"].iloc[-1], ts, ts,
                   price_action_zone_type="dual_band_breakout", band_a=a, band_b=b)

    def detect_anchor_box(self, df: pd.DataFrame) -> PriceZone | None:
        if len(df) < 3:
            return None
        from atlas.features.price_action.bars import candle_geometry
        c1, c2 = df.iloc[-2], df.iloc[-1]
        geom = candle_geometry(_bars_from_df(df.iloc[-1:])[0])
        if c1["low"] < c2["low"] and c2["close"] > c2["open"]:
            return _pz(self.symbol, f"anchor_bull_{c2['timestamp']}", ZoneType.ANCHOR, ZoneDirection.BULLISH,
                       c2["close"], c1["low"], c1["timestamp"], c2["timestamp"], reversal_geometry=geom)
        if c1["high"] > c2["high"] and c2["close"] < c2["open"]:
            return _pz(self.symbol, f"anchor_bear_{c2['timestamp']}", ZoneType.ANCHOR, ZoneDirection.BEARISH,
                       c1["high"], c2["close"], c1["timestamp"], c2["timestamp"], reversal_geometry=geom)
        return None

    def detect_event_box(self, df: pd.DataFrame, event_time: datetime) -> PriceZone | None:
        start = event_time.replace(minute=0, second=0, microsecond=0)
        return self._hour_box(df, start, ZoneType.EVENT, f"event_{event_time.strftime('%Y%m%d%H%M')}")

    def update_zones(self, df: pd.DataFrame, session_start: datetime | None = None,
                     event_time: datetime | None = None) -> dict[ZoneType, PriceZone | None]:
        if session_start:
            self.active_zones[ZoneType.OPENING] = self.detect_opening_box(df, session_start)
        self.active_zones[ZoneType.BREAKOUT] = self.detect_breakout_box(df)
        self.active_zones[ZoneType.ANCHOR] = self.detect_anchor_box(df)
        if event_time:
            self.active_zones[ZoneType.EVENT] = self.detect_event_box(df, event_time)
        return self.active_zones
