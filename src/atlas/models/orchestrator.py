"""Research-only routing. Eligibility never becomes order permission."""
from datetime import datetime, timezone
from typing import Callable, Literal, cast

from atlas.models.evaluation import ProbabilityCalibrator
from atlas.models.providers import ForecastProvider, ModelRegistryProvider
from atlas.models.registry import MetadataRegistry, ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import (
    Capability, Eligibility, Forecast, ForecastRequest, Horizon, Instrument, ModelRef,
    Record, Text,
)


class Rejection(Record):
    model: ModelRef
    reason: Text


class ResearchSignal(Record):
    request_id: Text
    forecasts: tuple[Forecast, ...]
    rejections: tuple[Rejection, ...]
    disagreement_by_step: tuple[float, ...]
    strategy_candidates: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    combined_forecast: None = None
    execution_permission: Literal["none"] = "none"


class ModelOrchestrator:
    def __init__(
        self, providers: ProviderRegistry, instruments: MetadataRegistry[Instrument],
        horizons: MetadataRegistry[Horizon], models: ModelRegistryProvider,
        approvals: tuple[Eligibility, ...], runtimes: dict[str, ProviderRuntime], *,
        calibrators: dict[tuple[str, ...], ProbabilityCalibrator] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.providers, self.instruments, self.horizons = providers, instruments, horizons
        self.models, self.approvals, self.runtimes, self.now = models, approvals, runtimes, now
        self.calibrators = calibrators or {}

    def eligible_horizons(self, instrument_id: str, *, strategy_family: str, liquidity_score: float, cost_bps: float) -> tuple[Horizon, ...]:
        import math
        if not math.isfinite(liquidity_score) or not 0 <= liquidity_score <= 1 or not math.isfinite(cost_bps) or cost_bps < 0:
            raise ValueError("Invalid liquidity or transaction cost")
        if not self.instruments.get(instrument_id).permitted_research:
            return ()
        now = self.now()
        ids = {a.horizon_id for a in self.approvals if a.instrument_id == instrument_id
               and a.strategy_family == strategy_family and a.research_approved
               and a.approved_at <= now < a.expires_at and cost_bps <= a.max_cost_bps
               and liquidity_score >= a.min_liquidity_score}
        return tuple(h for h in self.horizons.list() if h.horizon_id in ids)

    async def run(self, request: ForecastRequest, *, liquidity_score: float, cost_bps: float) -> ResearchSignal:
        import math
        if not math.isfinite(liquidity_score) or not 0 <= liquidity_score <= 1 or not math.isfinite(cost_bps) or cost_bps < 0:
            raise ValueError("Invalid liquidity or cost estimate")
        request = ForecastRequest.model_validate(request.model_dump())
        instrument = self.instruments.get(request.instrument_id)
        horizon = self.horizons.get(request.horizon_id)
        now = self.now()
        if not instrument.permitted_research:
            raise ValueError("Instrument research permission missing")
        if request.quality != "verified" or any(feature.quality != "verified" for feature in request.features):
            raise ValueError("Unverified input quality")
        if len(request.target_times) != horizon.steps:
            raise ValueError("Target count does not match horizon")
        if request.as_of > now or request.target_times[0] <= now:
            raise ValueError("Request is future-dated or targets have elapsed")
        if (now - request.observations[-1].event_time).total_seconds() > horizon.max_data_age_seconds:
            raise ValueError("Stale observations")
        if any((now - feature.event_time).total_seconds() > horizon.max_data_age_seconds for feature in request.features):
            raise ValueError("Stale covariates")
        warnings: list[str] = []
        forecasts: list[Forecast] = []
        rejected: list[Rejection] = []
        strategies: set[str] = set()
        seen: set[tuple[str, str, str]] = set()
        for approval in self.approvals:
            if (approval.instrument_id, approval.horizon_id, approval.target, approval.unit) != (
                request.instrument_id, request.horizon_id, request.target, request.unit
            ):
                continue
            model = approval.model
            now = self.now()
            if not approval.research_approved or not approval.approved_at <= now < approval.expires_at:
                rejected.append(Rejection(model=model, reason="Research approval absent or expired"))
                continue
            if liquidity_score < approval.min_liquidity_score or cost_bps > approval.max_cost_bps:
                rejected.append(Rejection(model=model, reason="Liquidity or transaction cost outside validation scope"))
                continue
            if model.key in seen:
                strategies.add(approval.strategy_family)
                continue
            try:
                record = self.models.get(model)
                if not record.commercial_use_verified:
                    raise ValueError("Model license not verified for commercial research")
                provider = cast(ForecastProvider, self.providers.require(model.provider_id, Capability.FORECAST))
                runtime = self.runtimes[model.provider_id]
                forecast = await runtime.call("forecast", lambda: provider.forecast(model, request), retry_safe=True, usage=lambda item: item.usage)
                forecast = Forecast.model_validate(forecast.model_dump())
                finished = self.now()
                if (forecast.request_id, forecast.model, forecast.instrument_id, forecast.horizon_id, forecast.target, forecast.unit, forecast.data_as_of) != (
                    request.request_id, model, request.instrument_id, request.horizon_id, request.target, request.unit, request.as_of
                ):
                    raise ValueError("Forecast identity does not match request")
                if tuple(point.timestamp for point in forecast.points) != request.target_times:
                    raise ValueError("Forecast target timestamps do not match")
                if not request.as_of <= forecast.generated_at <= finished:
                    raise ValueError("Invalid forecast generation time")
                if (finished - forecast.generated_at).total_seconds() > horizon.max_forecast_age_seconds:
                    raise ValueError("Stale forecast")
                if (finished - request.observations[-1].event_time).total_seconds() > horizon.max_data_age_seconds or request.target_times[0] <= finished:
                    raise ValueError("Data or targets expired during inference")
                if forecast.probability_up is not None:
                    calibrator = self.calibrators.get((*model.key, request.instrument_id, request.horizon_id, request.target, request.unit))
                    if calibrator is None:
                        forecast = forecast.model_copy(update={"calibration_ref": None})
                        warnings.append(f"{model.model_id}: probability is uncalibrated")
                    else:
                        calibrated = calibrator.apply(forecast.probability_up, as_of=request.as_of,
                            instrument_id=request.instrument_id, horizon_id=request.horizon_id, model_revision=model.revision, target=request.target, unit=request.unit)
                        forecast = forecast.model_copy(update={"probability_up": calibrated, "calibration_ref": calibrator.calibration_id})
                if any(point.lower is None for point in forecast.points):
                    warnings.append(f"{model.model_id}: forecast interval unavailable")
                forecasts.append(forecast)
                seen.add(model.key)
                strategies.add(approval.strategy_family)
            except Exception as exc:
                # No provider response text, prompts, or credentials in research diagnostics.
                reason = type(exc).__name__
                rejected.append(Rejection(model=model, reason=reason or type(exc).__name__))
        # Earlier results may age while a later provider is running.
        completed_at = self.now()
        fresh: list[Forecast] = []
        strategies.clear()
        for forecast in forecasts:
            matching = [a for a in self.approvals if a.model == forecast.model and a.research_approved
                and a.instrument_id == request.instrument_id and a.horizon_id == request.horizon_id
                and a.target == request.target and a.unit == request.unit
                and a.approved_at <= completed_at < a.expires_at
                and liquidity_score >= a.min_liquidity_score and cost_bps <= a.max_cost_bps]
            data_expired = (completed_at - request.observations[-1].event_time).total_seconds() > horizon.max_data_age_seconds
            data_expired = data_expired or any((completed_at - f.event_time).total_seconds() > horizon.max_data_age_seconds for f in request.features)
            if not matching or data_expired or request.target_times[0] <= completed_at or (completed_at - forecast.generated_at).total_seconds() > horizon.max_forecast_age_seconds:
                rejected.append(Rejection(model=forecast.model, reason="Approval, input or forecast expired before result release"))
            else:
                fresh.append(forecast)
                strategies.update(a.strategy_family for a in matching)
        forecasts = fresh
        if len(forecasts) < 2:
            warnings.append("Disagreement unavailable with fewer than two eligible forecasts")
        spread = tuple(max(f.points[i].value for f in forecasts) - min(f.points[i].value for f in forecasts)
                       for i in range(horizon.steps)) if len(forecasts) >= 2 else ()
        return ResearchSignal(request_id=request.request_id, forecasts=tuple(forecasts), rejections=tuple(rejected),
                              disagreement_by_step=spread, strategy_candidates=tuple(sorted(strategies)), warnings=tuple(warnings))
