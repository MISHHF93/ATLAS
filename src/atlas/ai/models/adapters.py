"""Offline baselines, seasonal/statistical baselines, metered Gemini research, and optional xAI narrator."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal
import json
from statistics import mean
from typing import Any

from atlas.ai.policy import PolicyError, screen_context
from atlas.ai.provider import LLMProvider
from atlas.ai.schemas import MarketResearchResult
from atlas.schemas import (
    Capability,
    Forecast,
    ForecastPoint,
    ForecastRequest,
    ModelRef,
    ProviderInfo,
    Record,
    Text,
    Usage,
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


class SeasonalStatisticalForecastProvider:
    """Local seasonal-naive and EWMA statistical baseline provider (`UNIVERSAL_AI_ECOSYSTEM.md`)."""

    def __init__(self, *, seasonal_period: int = 4, ewma_alpha: float = 0.35) -> None:
        if seasonal_period < 2 or not 0 < ewma_alpha <= 1:
            raise ValueError("Invalid seasonal_period or ewma_alpha")
        self.seasonal_period = seasonal_period
        self.ewma_alpha = ewma_alpha

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="statistical_baseline",
            location="local",
            capabilities=frozenset({Capability.FORECAST}),
            models=("seasonal_naive", "ewma_level"),
        )

    async def forecast(self, model: ModelRef, request: ForecastRequest) -> Forecast:
        if model.provider_id != "statistical_baseline" or model.revision != "1" or model.model_id not in self.describe().models:
            raise ValueError("Unknown statistical baseline model revision")
        values = [obs.value for obs in request.observations]
        if model.model_id == "seasonal_naive":
            if len(values) < self.seasonal_period:
                raise ValueError("Insufficient observations for seasonal_naive period")
            season_slice = values[-self.seasonal_period:]
            points = tuple(
                ForecastPoint(
                    timestamp=stamp,
                    value=season_slice[idx % self.seasonal_period],
                )
                for idx, stamp in enumerate(request.target_times)
            )
        else:
            level = values[0]
            for val in values[1:]:
                level = self.ewma_alpha * val + (1.0 - self.ewma_alpha) * level
            residual_spread = max(1e-6, mean(abs(v - level) for v in values)) * 1.96
            points = tuple(
                ForecastPoint(
                    timestamp=stamp,
                    value=round(level, 6),
                    lower=round(level - residual_spread, 6),
                    upper=round(level + residual_spread, 6),
                    interval_coverage=0.95,
                )
                for stamp in request.target_times
            )
        return Forecast(
            request_id=request.request_id,
            model=model,
            instrument_id=request.instrument_id,
            horizon_id=request.horizon_id,
            target=request.target,
            unit=request.unit,
            data_as_of=request.as_of,
            generated_at=datetime.now(timezone.utc),
            points=points,
            usage=Usage(cost_usd=Decimal("0"), cost_kind="estimated"),
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


# Dated price table per 1M tokens from `docs/research/AI_ECOSYSTEM.md` (checked 2026-10-19)
VERIFIED_TOKEN_PRICES_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "gemini-3.8-flash": (Decimal("0.75"), Decimal("3.75")),
    "gemini-4-argon": (Decimal("2.00"), Decimal("10.00")),
    "grok-4.7": (Decimal("2.00"), Decimal("6.00")),
}


class MeteredResearchEnvelope(Record):
    provider_id: Text
    model_id: Text
    note: MarketResearchResult
    usage: Usage
    privacy_mode: Text


def estimate_token_usage(model_id: str, input_tokens: int, output_tokens: int) -> Usage:
    """Calculate token usage and USD cost from dated snapshot prices; unknown models stay cost_kind='unknown'."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts must be nonnegative")
    rates = VERIFIED_TOKEN_PRICES_PER_MILLION.get(model_id)
    if rates is None:
        return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=None, cost_kind="unknown")
    in_rate, out_rate = rates
    cost = (Decimal(input_tokens) * in_rate + Decimal(output_tokens) * out_rate) / Decimal("1000000")
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost.quantize(Decimal("0.000001")), cost_kind="estimated")


class XAINarratorAdapter:
    """Optional second narrator over native HTTP/transport without an OpenAI SDK (`DECISIONS.md` #15).

    Records explicit privacy mode (`zdr_enabled` vs 30-day retention) per `AI_ECOSYSTEM.md`.
    Confidence remains uncalibrated and never enters forecast combination.
    """

    def __init__(
        self,
        *,
        model: str = "grok-4.7",
        zdr_enabled: bool = False,
        transport: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.model = model
        self.zdr_enabled = zdr_enabled
        self._transport = transport

    @property
    def privacy_mode(self) -> str:
        return "xai:zdr_enabled" if self.zdr_enabled else "xai:default_30d_retention"

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="xai",
            location="cloud",
            capabilities=frozenset({Capability.RESEARCH, Capability.STRUCTURED_OUTPUT}),
            models=(self.model,),
        )

    async def research(self, context: str) -> MarketResearchResult:
        envelope = await self.research_metered(context)
        return envelope.note

    async def research_metered(self, context: str) -> MeteredResearchEnvelope:
        screen_context(context)
        if self._transport is None:
            raise PolicyError("xAI HTTP transport is not configured")
        payload = await self._transport(self.model, context)
        raw_text = payload.get("text", "")
        if not raw_text:
            raise RuntimeError("xAI narrator returned an empty response")
        note = MarketResearchResult.model_validate_json(
            raw_text if isinstance(raw_text, str) else json.dumps(raw_text)
        )
        in_tokens = int(payload.get("input_tokens", max(1, len(context) // 4)))
        out_tokens = int(payload.get("output_tokens", max(1, len(str(raw_text)) // 4)))
        usage = estimate_token_usage(self.model, in_tokens, out_tokens)
        return MeteredResearchEnvelope(
            provider_id="xai",
            model_id=self.model,
            note=note,
            usage=usage,
            privacy_mode=self.privacy_mode,
        )
