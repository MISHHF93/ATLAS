"""Continuous 24/7 research cycle runner with deterministic anomaly halt and zero silent fallback.

Implements `RESEARCH_OPERATING_CONTRACT.md` ("Continuous research behavior"):
- Polls approved read-only source via `ReadOnlyDataProvider`
- Validates quality, freshness, calendar match, license rights, and content hash
- Computes causal `RegimeState`
- Runs `ModelOrchestrator` for scoped forecasts
- Evaluates deterministic `TradingRuleBook` remaining room
- Stops and marks the scope `unavailable` on license expiry, provider errors,
  rate-limit exhaustion, stale/malformed inputs, calendar mismatch, or integrity
  hash change, without falling back silently to another data source.
"""
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime

from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    RuleEvaluationReport,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.marketdata.quality import DataQualityReport, validate_market_data_batch
from atlas.models.calendars import MarketCalendar, construct_authoritative_targets
from atlas.models.orchestrator import ModelOrchestrator, ResearchSignal
from atlas.models.providers import ReadOnlyDataProvider
from atlas.models.regimes import RegimeConfig, RegimeState, classify_regime
from atlas.models.schemas import (
    ForecastRequest,
    Horizon,
    Instrument,
    MarketDataRequest,
    Record,
    Text,
)


class ResearchCycleAuditEvent(Record):
    cycle_id: Text
    as_of: AwareDatetime
    instrument_id: Text
    horizon_id: Text
    provider_id: Text
    scope_status: Literal["healthy", "unavailable_halted"]
    halt_reason: Text | None = None
    fallback_attempted: Literal[False] = False
    execution_permission: Literal["none"] = "none"


class ResearchCycleResult(Record):
    audit_event: ResearchCycleAuditEvent
    quality_report: DataQualityReport | None = None
    regime_state: RegimeState | None = None
    research_signal: ResearchSignal | None = None
    rule_report: RuleEvaluationReport | None = None
    execution_permission: Literal["none"] = "none"


class ContinuousResearchRunner:
    """Executes one deterministic 24/7 research tick without silent source fallback."""

    def __init__(
        self,
        *,
        data_provider: ReadOnlyDataProvider,
        orchestrator: ModelOrchestrator,
        instrument: Instrument,
        horizon: Horizon,
        calendar: MarketCalendar,
        rulebook: TradingRuleBook,
        regime_config: RegimeConfig | None = None,
    ) -> None:
        self.data_provider = data_provider
        self.orchestrator = orchestrator
        self.instrument = instrument
        self.horizon = horizon
        self.calendar = calendar
        self.rulebook = rulebook
        self.regime_config = regime_config or RegimeConfig()
        self.audit_log: list[ResearchCycleAuditEvent] = []

    def _halt(self, cycle_id: str, as_of: datetime, provider_id: str, reason: str, quality: DataQualityReport | None = None) -> ResearchCycleResult:
        event = ResearchCycleAuditEvent(
            cycle_id=cycle_id,
            as_of=as_of,
            instrument_id=self.instrument.instrument_id,
            horizon_id=self.horizon.horizon_id,
            provider_id=provider_id,
            scope_status="unavailable_halted",
            halt_reason=reason,
        )
        self.audit_log.append(event)
        return ResearchCycleResult(audit_event=event, quality_report=quality)

    async def run_cycle(
        self,
        *,
        cycle_id: str,
        data_request: MarketDataRequest,
        account_snapshot: AccountRiskSnapshot,
        trade_candidate: ProposedTradeCheck,
        target: str = "price",
        unit: str = "USD",
        liquidity_score: float = 0.80,
        cost_bps: float = 2.0,
        expected_content_sha256: str | None = None,
        step_seconds: int | None = 3600,
    ) -> ResearchCycleResult:
        as_of = data_request.as_of
        provider_id = data_request.provider_id

        # 1. Fetch read-only market data (never falls back to another provider on failure)
        try:
            batch = await self.data_provider.fetch_market_data(data_request)
        except Exception as exc:
            return self._halt(cycle_id, as_of, provider_id, f"provider_error:{type(exc).__name__}")

        # 2. Optional frozen content hash integrity check
        if expected_content_sha256 is not None and batch.provenance.content_sha256 != expected_content_sha256:
            return self._halt(cycle_id, as_of, provider_id, "integrity_hash_mismatch")

        # 3. Validate quality, freshness, license, and calendar match
        validated_batch, quality_report = validate_market_data_batch(
            batch,
            self.instrument,
            as_of=as_of,
            max_data_age_seconds=self.horizon.max_data_age_seconds,
            intended_use="competition" if self.rulebook.track == "competition" else "retention",
        )
        if quality_report.quality_status != "verified":
            reason = ",".join(quality_report.blocking_issues) or "quality_unverified"
            return self._halt(cycle_id, as_of, provider_id, f"quality_gate_failed:{reason}", quality=quality_report)

        # 4. Construct authoritative targets from calendar
        try:
            targets = construct_authoritative_targets(
                self.instrument,
                self.horizon,
                self.calendar,
                as_of=as_of,
                step_seconds=step_seconds,
            )
        except Exception as exc:
            return self._halt(cycle_id, as_of, provider_id, f"calendar_target_error:{type(exc).__name__}", quality=quality_report)

        # 5. Classify causal regime
        regime_state = classify_regime(
            as_of=as_of,
            instrument_id=self.instrument.instrument_id,
            observations=validated_batch.observations,
            config=self.regime_config,
            calendar=self.calendar,
            liquidity_score=liquidity_score,
            spread_bps=cost_bps,
        )

        # 6. Run scoped forecast orchestrator
        forecast_req = ForecastRequest(
            request_id=f"fc:{cycle_id}",
            instrument_id=self.instrument.instrument_id,
            horizon_id=self.horizon.horizon_id,
            as_of=as_of,
            target=target,
            unit=unit,
            observations=validated_batch.observations,
            features=validated_batch.features,
            target_times=targets,
            dataset_id=f"live_research:{cycle_id}",
            data_license_ref=validated_batch.provenance.license_ref,
            quality=validated_batch.quality,
        )
        signal = await self.orchestrator.run(
            forecast_req,
            liquidity_score=liquidity_score,
            cost_bps=cost_bps,
        )

        # 7. Evaluate deterministic control-plane rulebook
        rule_report = evaluate_trading_rules(
            self.rulebook,
            account_snapshot,
            trade_candidate,
            evaluated_at=as_of,
        )

        event = ResearchCycleAuditEvent(
            cycle_id=cycle_id,
            as_of=as_of,
            instrument_id=self.instrument.instrument_id,
            horizon_id=self.horizon.horizon_id,
            provider_id=provider_id,
            scope_status="healthy",
            halt_reason=None,
        )
        self.audit_log.append(event)
        return ResearchCycleResult(
            audit_event=event,
            quality_report=quality_report,
            regime_state=regime_state,
            research_signal=signal,
            rule_report=rule_report,
        )

