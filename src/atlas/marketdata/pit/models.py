from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Bar(BaseModel):
    """OHLCV bar. `ts` = bar close (UTC). `available_at` = earliest time the bar
    may be used by a strategy (point-in-time); defaults to ts."""
    model_config = ConfigDict(frozen=True)
    symbol: str
    ts: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    available_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "Bar":
        if self.ts.tzinfo is None:
            raise ValueError("ts must be timezone-aware (UTC)")
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError("OHLC inconsistent")
        if self.available_at is None:
            object.__setattr__(self, "available_at", self.ts)
        elif self.available_at < self.ts:
            raise ValueError("available_at earlier than bar close => look-ahead")
        return self


class EarningsEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    date: str
    hour: str | None = None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    available_at: datetime
