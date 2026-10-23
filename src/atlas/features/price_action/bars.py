"""Bar contract and confirmation rule shared by every price-action detector.

bar_start = t, bar_end = t + duration, and
bar_confirmed = now >= bar_end AND provider_completion_verified.
Times are integer UNIX seconds (UTC). Nothing here can submit an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

EPS = 1e-12


@dataclass(frozen=True)
class Bar:
    start: int
    duration: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    provider_completion_verified: bool = True

    @property
    def end(self) -> int:
        return self.start + self.duration

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("duration must be positive")
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"inconsistent OHLC at {self.start}")


def bar_confirmed(bar: Bar, now: int) -> bool:
    return now >= bar.end and bar.provider_completion_verified


def candle_geometry(bar: Bar) -> dict[str, float]:
    """Body, wicks and ratios normalised by max(range, EPS)."""
    body = abs(bar.close - bar.open)
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    rng = bar.high - bar.low
    d = max(rng, EPS)
    return {
        "body": body, "upper_wick": upper, "lower_wick": lower, "range": rng,
        "body_ratio": body / d, "upper_wick_ratio": upper / d, "lower_wick_ratio": lower / d,
        "close_location": (bar.close - bar.low) / d,
    }


def bars_from_rows(rows: Iterable[Sequence[float]], duration: int) -> list[Bar]:
    """(t, o, h, l, c, v) rows -> Bars (the UDF/bar-projection row shape)."""
    return [Bar(int(r[0]), duration, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]) if len(r) > 5 else 0.0)
            for r in rows]
