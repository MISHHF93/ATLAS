"""Validated market candle schema. Prices stay decimal strings."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Candle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue: str
    symbol: str
    interval: str
    open_time: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    source: Literal["fixture"]

    @field_validator("open_time")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("open_time must include a timezone")
        return value

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def finite_nonnegative_decimal(cls, value: str) -> str:
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Expected a decimal string") from exc
        if not number.is_finite() or number < 0:
            raise ValueError("Expected a finite nonnegative decimal")
        return value

    @model_validator(mode="after")
    def valid_price_range(self) -> Self:
        low, high = Decimal(self.low), Decimal(self.high)
        if not low <= Decimal(self.open) <= high or not low <= Decimal(self.close) <= high:
            raise ValueError("Open and close must lie within low and high")
        return self


class CandlePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: str
    source: Literal["fixture"]
    candles: list[Candle] = Field(default_factory=list)
