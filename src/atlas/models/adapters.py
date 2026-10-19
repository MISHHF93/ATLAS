"""Offline baselines and a bridge to the existing Gemini research interface."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from atlas.ai.provider import LLMProvider
from atlas.ai.schemas import MarketResearchResult
from atlas.models.schemas import (
    Capability, Forecast, ForecastPoint, ForecastRequest, ModelRef, ProviderInfo, Usage,
)


class NaiveForecastProvider:
    def describe(self) -> ProviderInfo:
        return ProviderInfo(provider_id="naive", location="local", capabilities={Capability.FORECAST}, models=("last_value", "zero_return"))

    async def forecast(self, model: ModelRef, request: ForecastRequest) -> Forecast:
        if model.provider_id != "naive" or model.revision != "1" or model.model_id not in self.describe().models:
            raise ValueError("Unknown baseline model revision")
        if model.model_id == "zero_return" and request.target != "return":
            raise ValueError("Zero-return baseline requires a return target")
        value = 0.0 if model.model_id == "zero_return" else request.observations[-1].value
        return Forecast(
            request_id=request.request_id, model=model, instrument_id=request.instrument_id,
            horizon_id=request.horizon_id, target=request.target, unit=request.unit,
            data_as_of=request.as_of, generated_at=datetime.now(timezone.utc),
            points=tuple(ForecastPoint(timestamp=stamp, value=value) for stamp in request.target_times),
            usage=Usage(cost_usd=Decimal(0), cost_kind="estimated"),
        )


class GeminiResearchAdapter:
    """Bridge accepts the existing provider; it neither loads keys nor starts calls on construction.

    This legacy synchronous adapter uses a worker thread. The SDK timeout bounds
    its network work; cancelling the coroutine cannot terminate that thread.
    """
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def describe(self) -> ProviderInfo:
        return ProviderInfo(provider_id="gemini", location="cloud", capabilities={Capability.RESEARCH, Capability.STRUCTURED_OUTPUT})

    async def research(self, context: str) -> MarketResearchResult:
        return await asyncio.to_thread(self._provider.analyze, context)
