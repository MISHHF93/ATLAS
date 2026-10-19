"""Structured research output.

`confidence` is the model's own estimate. It is not a calibrated probability
and must not be used as a position size.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regime: Literal["trending", "ranging", "volatile", "unknown"]
    summary: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list, max_length=12)
