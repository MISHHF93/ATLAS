"""Shared Zone contract and lifecycle (formed -> confirmed -> touch/retest -> invalidated | expired)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from atlas.features.price_action.bars import EPS, Bar

Direction = Literal["bullish", "bearish", "neutral"]
ZONE_VERSION = 1


@dataclass
class Zone:
    instrument: str
    timeframe: int
    zone_type: str
    direction: Direction
    lower_bound: float
    upper_bound: float
    formed_at: int
    confirmed_at: int | None = None
    invalidated_at: int | None = None
    expired_at: int | None = None
    touch_count: int = 0
    first_retest_at: int | None = None
    source_event: str = ""
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    version: int = ZONE_VERSION
    max_age_seconds: int | None = None
    invalidation_buffer: float = 0.0
    _inside_prev: bool = False

    def __post_init__(self) -> None:
        if self.upper_bound < self.lower_bound:
            raise ValueError("upper_bound < lower_bound")

    @property
    def zone_id(self) -> str:
        return f"{self.instrument}:{self.timeframe}:{self.zone_type}:{self.direction}:{self.formed_at}"

    @property
    def height(self) -> float:
        return self.upper_bound - self.lower_bound

    @property
    def midpoint(self) -> float:
        return (self.upper_bound + self.lower_bound) / 2.0

    @property
    def active(self) -> bool:
        return self.confirmed_at is not None and self.invalidated_at is None and self.expired_at is None

    @property
    def status(self) -> str:
        if self.invalidated_at is not None:
            return "invalidated"
        if self.expired_at is not None:
            return "expired"
        if self.first_retest_at is not None:
            return "retested"
        return "confirmed" if self.confirmed_at is not None else "formed"

    def distance(self, price: float) -> float:
        if self.lower_bound <= price <= self.upper_bound:
            return 0.0
        return self.lower_bound - price if price < self.lower_bound else price - self.upper_bound

    def normalized_distance(self, price: float, atr: float | None) -> float | None:
        if atr is None:
            return None
        return self.distance(price) / max(atr, EPS)

    def update(self, bar: Bar) -> list[str]:
        """Apply one completed bar that ends after confirmation. Returns lifecycle events."""
        if not self.active or bar.end <= (self.confirmed_at or 0):
            return []
        ev: list[str] = []
        if self.max_age_seconds is not None and bar.end > self.confirmed_at + self.max_age_seconds:
            self.expired_at = bar.end
            return ["expired"]
        inside = bar.low <= self.upper_bound and bar.high >= self.lower_bound
        if inside and not self._inside_prev:
            self.touch_count += 1
            ev.append("touch")
            if self.first_retest_at is None:
                self.first_retest_at = bar.end
                ev.append("retest")
        self._inside_prev = inside
        if self.direction == "bullish" and bar.close < self.lower_bound - self.invalidation_buffer:
            self.invalidated_at = bar.end
            ev.append("invalidated")
        elif self.direction == "bearish" and bar.close > self.upper_bound + self.invalidation_buffer:
            self.invalidated_at = bar.end
            ev.append("invalidated")
        return ev

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_inside_prev")
        d.update(zone_id=self.zone_id, height=self.height, midpoint=self.midpoint, status=self.status,
                 execution_permission="none")
        return d
