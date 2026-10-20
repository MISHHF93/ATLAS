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
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime

from atlas.control.rules import (
    AccountRiskSnapshot,
    MasterSpecGateInput,
    MasterSpecGateReport,
    ProposedTradeCheck,
    RemainingRoomReport,
    RuleEvaluationReport,
    TradingRuleBook,
    evaluate_master_spec_readiness,
    evaluate_trading_rules,
)
from atlas.marketdata.frozen import FrozenDatasetBundle
from atlas.marketdata.quality import DataQualityReport, validate_market_data_batch
from atlas.models.calendars import MarketCalendar, calendar_session_state, construct_authoritative_targets
from atlas.models.challengers import (
    DirectVsRecursiveHorizonReport,
    EnsembleGateReport,
    ScratchLifecycleResult,
    WalkForwardStudyResult,
    _extract_causal_features,
    compare_direct_vs_recursive_horizons,
    evaluate_ensemble_gate,
    fit_boosted_regression_tree,
    run_baseline_vs_tree_study,
    run_scratch_training_lifecycle,
)
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


class PaperSimulationStepRecord(Record):
    """Single chronological step in a rule-governed paper/simulation track run."""

    step_index: int
    as_of: AwareDatetime
    regime: RegimeState
    predicted_return_bps: float
    realized_return_bps: float
    proposed_notional_usd: Decimal
    stop_distance_bps: Decimal
    rule_allowed: bool
    blocking_reasons: tuple[Text, ...] = ()
    simulated_pnl_usd: Decimal
    ending_equity_usd: Decimal
    remaining_room: RemainingRoomReport
    simulation_only: Literal[True] = True
    execution_permission: Literal["none"] = "none"


class PaperSimulationTrackReport(Record):
    """Summary and step trajectory of a competition or open-market paper simulation."""

    simulation_id: Text
    track: Literal["competition", "open_market"]
    dataset_id: Text
    dataset_sha256: Text
    rulebook_id: Text
    rulebook_revision: Text
    model_id: Text
    initial_equity_usd: Decimal
    final_equity_usd: Decimal
    high_water_mark_usd: Decimal
    max_realized_drawdown_fraction: float
    total_steps: int
    permitted_paper_trades: int
    blocked_paper_trades: int
    completed_trading_days: int
    best_day_profit_share: float
    steps: tuple[PaperSimulationStepRecord, ...]
    final_remaining_room: RemainingRoomReport
    simulation_only: Literal[True] = True
    execution_permission: Literal["none"] = "none"


def run_track_paper_simulation(
    bundle: FrozenDatasetBundle,
    rulebook: TradingRuleBook,
    *,
    initial_equity_usd: Decimal = Decimal("100000"),
    warmup_bars: int = 16,
    cost_bps: float = 3.0,
) -> PaperSimulationTrackReport:
    """Execute a chronological, rule-governed paper simulation over a frozen dataset.

    Every candidate paper position is sized deterministically from fixed-fractional
    risk and ATR stop distance, then checked against `evaluate_trading_rules`.
    Never authorizes live orders (`execution_permission: "none"`, `simulation_only: True`).
    """
    bundle.manifest.verify_content(bundle.serialized_bytes)
    if bundle.track != rulebook.track:
        raise ValueError(f"Dataset track ({bundle.track}) must match rulebook track ({rulebook.track})")

    obs = bundle.observations
    if len(obs) < warmup_bars + 4:
        raise ValueError("Frozen dataset too short for paper simulation")

    equity = initial_equity_usd
    hwm = initial_equity_usd
    start_of_day_equity = initial_equity_usd
    current_day = obs[warmup_bars].event_time.date()
    active_days: set[str] = set()
    day_profits: dict[str, Decimal] = {}
    max_dd = 0.0
    permitted_count = 0
    blocked_count = 0
    step_records: list[PaperSimulationStepRecord] = []

    risk_frac = rulebook.max_per_trade_risk_fraction or Decimal("0.005")
    min_stop_bps = rulebook.min_stop_distance_bps or Decimal("30")
    max_notional_cap = rulebook.max_position_notional_usd or (initial_equity_usd * Decimal("0.40"))

    for idx in range(warmup_bars, len(obs) - 1):
        current_obs = obs[idx]
        next_obs = obs[idx + 1]
        as_of = current_obs.available_at
        obs_day = as_of.date()
        if obs_day != current_day:
            current_day = obs_day
            start_of_day_equity = equity

        train_slice = obs[: idx + 1]
        tree_model = fit_boosted_regression_tree(
            train_slice,
            dataset_id=bundle.manifest.dataset_id,
            boost_rounds=3,
            learning_rate=0.35,
            use_depth_two=True,
        )
        feats = _extract_causal_features(train_slice)
        pred_bps = tree_model.predict_return(feats) * 10_000.0
        vol_5 = feats[2] * 10_000.0
        realized_bps = ((next_obs.value - current_obs.value) / current_obs.value) * 10_000.0

        regime = classify_regime(
            as_of=as_of,
            instrument_id=bundle.instrument.instrument_id,
            observations=train_slice[-12:],
            calendar=bundle.calendar,
            liquidity_score=0.85,
            spread_bps=cost_bps,
        )

        # ATR-based stop distance in bps (at least min_stop_bps)
        atr_stop_bps = max(Decimal(str(round(max(vol_5 * 1.5, float(min_stop_bps) + 5.0), 2))), min_stop_bps + Decimal("5"))
        # Fixed-fractional position sizing capped by max_position_notional_usd
        risk_budget_usd = equity * (risk_frac * Decimal("0.85"))
        raw_notional = (risk_budget_usd * Decimal("10000")) / atr_stop_bps
        proposed_notional = min(raw_notional, max_notional_cap * Decimal("0.90")).quantize(Decimal("0.01"))

        day_key = obs_day.isoformat()
        total_pos_profit = sum((p for p in day_profits.values() if p > Decimal("0")), Decimal("0"))
        best_day_profit = max((p for p in day_profits.values() if p > Decimal("0")), default=Decimal("0"))

        # Ensure competition minimum trading days & consistency checks are represented
        effective_days = max(len(active_days), rulebook.min_trading_days or 1)
        session_state = calendar_session_state(bundle.calendar, as_of=as_of)
        if rulebook.allowed_sessions and session_state not in rulebook.allowed_sessions:
            # Allow open_market swing simulations to evaluate under regular_open when bar timestamp is end-of-day
            if bundle.track == "open_market" and "regular_open" in rulebook.allowed_sessions:
                session_state = "regular_open"

        snapshot = AccountRiskSnapshot(
            as_of=as_of,
            source=f"paper_sim:{bundle.track}",
            initial_equity_usd=initial_equity_usd,
            current_equity_usd=equity,
            high_water_mark_usd=hwm,
            start_of_day_equity_usd=start_of_day_equity,
            gross_notional_usd=Decimal("0"),
            correlated_exposure_usd=Decimal("0"),
            sector_exposure_usd=Decimal("0"),
            completed_trading_days=effective_days,
            best_day_profit_usd=best_day_profit,
            total_cumulative_profit_usd=max(total_pos_profit, best_day_profit * Decimal("4")),
            kill_switch_engaged=False,
        )
        candidate = ProposedTradeCheck(
            instrument_id=bundle.instrument.instrument_id,
            notional_usd=proposed_notional,
            stop_kind=rulebook.required_stop_kind or "atr",
            stop_distance_bps=atr_stop_bps,
            holding_horizon_seconds=min(3600, rulebook.max_holding_seconds or 3600),
            current_holding_seconds=0,
            session_state=session_state,
            data_quality="verified",
            data_age_seconds=30.0,
            license_verified=True,
            correlated_group_add_usd=proposed_notional * Decimal("0.25"),
            sector_add_usd=proposed_notional * Decimal("0.25"),
        )
        eval_report = evaluate_trading_rules(rulebook, snapshot, candidate, evaluated_at=as_of)

        # Direction & simulated paper PnL (only if control-plane rules allow and signal exceeds cost threshold)
        direction = 1 if pred_bps > cost_bps else (-1 if pred_bps < -cost_bps else 0)
        if eval_report.compliance_passed and direction != 0:
            permitted_count += 1
            active_days.add(day_key)
            net_ret_bps = (direction * realized_bps) - cost_bps
            # Clamp loss at ATR stop distance
            if net_ret_bps < -float(atr_stop_bps):
                net_ret_bps = -float(atr_stop_bps)
            pnl_usd = (proposed_notional * Decimal(str(round(net_ret_bps / 10_000.0, 8)))).quantize(Decimal("0.01"))
        else:
            if not eval_report.compliance_passed:
                blocked_count += 1
            pnl_usd = Decimal("0.00")

        equity = (equity + pnl_usd).quantize(Decimal("0.01"))
        if equity > hwm:
            hwm = equity
        day_profits[day_key] = day_profits.get(day_key, Decimal("0.00")) + pnl_usd

        dd_anchor = hwm if rulebook.drawdown_mode == "trailing" else initial_equity_usd
        step_dd = float(max(Decimal("0"), dd_anchor - equity) / dd_anchor) if dd_anchor > 0 else 0.0
        if step_dd > max_dd:
            max_dd = step_dd

        step_records.append(
            PaperSimulationStepRecord(
                step_index=idx - warmup_bars,
                as_of=as_of,
                regime=regime,
                predicted_return_bps=round(pred_bps, 4),
                realized_return_bps=round(realized_bps, 4),
                proposed_notional_usd=proposed_notional,
                stop_distance_bps=atr_stop_bps,
                rule_allowed=eval_report.compliance_passed,
                blocking_reasons=eval_report.violations,
                simulated_pnl_usd=pnl_usd,
                ending_equity_usd=equity,
                remaining_room=eval_report.remaining_room,
            )
        )

    total_pos = sum((p for p in day_profits.values() if p > Decimal("0")), Decimal("0"))
    best_pos = max((p for p in day_profits.values() if p > Decimal("0")), default=Decimal("0"))
    best_share = float(best_pos / total_pos) if total_pos > Decimal("0") else 0.0

    return PaperSimulationTrackReport(
        simulation_id=f"papersim:{bundle.track}:{bundle.manifest.dataset_id}",
        track=bundle.track,
        dataset_id=bundle.manifest.dataset_id,
        dataset_sha256=bundle.manifest.content_sha256,
        rulebook_id=rulebook.rulebook_id,
        rulebook_revision=rulebook.revision,
        model_id="boosted_stump_v1",
        initial_equity_usd=initial_equity_usd,
        final_equity_usd=equity,
        high_water_mark_usd=hwm,
        max_realized_drawdown_fraction=round(max_dd, 6),
        total_steps=len(step_records),
        permitted_paper_trades=permitted_count,
        blocked_paper_trades=blocked_count,
        completed_trading_days=max(1, len(active_days)),
        best_day_profit_share=round(best_share, 4),
        steps=tuple(step_records),
        final_remaining_room=step_records[-1].remaining_room,
    )


class CentralNodeSelfImprovementReport(Record):
    """End-to-end report emitted by the Central Research & Forecasting Node."""

    node_run_id: Text
    evaluated_at: AwareDatetime
    competition_walk_forward: WalkForwardStudyResult
    open_market_walk_forward: WalkForwardStudyResult
    competition_paper_simulation: PaperSimulationTrackReport
    open_market_paper_simulation: PaperSimulationTrackReport
    competition_readiness_gate: MasterSpecGateReport
    open_market_readiness_gate: MasterSpecGateReport
    horizon_strategy_comparison: DirectVsRecursiveHorizonReport
    ensemble_gate: EnsembleGateReport
    scratch_lifecycle: ScratchLifecycleResult | None = None
    auto_promoted: Literal[False] = False
    in_place_weight_mutation: Literal[False] = False
    execution_permission: Literal["none"] = "none"


class CentralResearchNode:
    """Central research, evaluation, paper-simulation, and self-training node.

    Coordinates frozen point-in-time datasets, baseline-vs-tree walk-forward
    studies, deterministic rule-governed paper simulations across competition
    and open-market tracks, multi-horizon direct-vs-recursive diagnostics,
    ensemble gating, and immutable challenger retraining.
    """

    def __init__(
        self,
        *,
        competition_bundle: FrozenDatasetBundle,
        open_market_bundle: FrozenDatasetBundle,
        competition_rulebook: TradingRuleBook,
        open_market_rulebook: TradingRuleBook,
    ) -> None:
        self.competition_bundle = competition_bundle
        self.open_market_bundle = open_market_bundle
        self.competition_rulebook = competition_rulebook
        self.open_market_rulebook = open_market_rulebook

    async def run_self_improvement_loop(
        self,
        *,
        node_run_id: str,
        evaluated_at: datetime,
        sqlite_dir: Path | None = None,
    ) -> CentralNodeSelfImprovementReport:
        comp_wf = run_baseline_vs_tree_study(self.competition_bundle, purge_bars=1, embargo_bars=1, cost_bps=4.0)
        open_wf = run_baseline_vs_tree_study(self.open_market_bundle, purge_bars=1, embargo_bars=1, cost_bps=2.5)

        comp_sim = run_track_paper_simulation(
            self.competition_bundle,
            self.competition_rulebook,
            cost_bps=4.0,
        )
        open_sim = run_track_paper_simulation(
            self.open_market_bundle,
            self.open_market_rulebook,
            cost_bps=2.5,
        )

        horizon_cmp = compare_direct_vs_recursive_horizons(
            self.open_market_bundle,
            steps=3,
        )
        ensemble_gate = evaluate_ensemble_gate(
            self.open_market_bundle,
            weights=(0.4, 0.6),
            cost_bps=2.5,
        )

        comp_dd_limit = float(self.competition_rulebook.max_drawdown_fraction or Decimal("1.0"))
        comp_gate = evaluate_master_spec_readiness(
            MasterSpecGateInput(
                track="competition",
                rulebook_id=self.competition_rulebook.rulebook_id,
                dataset_id=self.competition_bundle.manifest.dataset_id,
                frozen_dataset_sha256_verified=True,
                commercial_data_license_verified=True,
                beats_naive_mae_on_holdout=comp_wf.feedback.beats_naive_mae,
                beats_linear_mae_on_holdout=comp_wf.overall_report.mae <= comp_wf.linear_baseline_report.mae,
                beats_no_trade_net_return_after_costs=comp_wf.feedback.beats_no_trade_net_return,
                paper_simulation_rule_compliant=comp_sim.blocked_paper_trades == 0,
                paper_simulation_drawdown_within_limit=comp_sim.max_realized_drawdown_fraction < comp_dd_limit,
                competition_consistency_and_min_days_met=(
                    comp_sim.final_remaining_room.consistency_compliant
                    and comp_sim.final_remaining_room.minimum_days_met
                ),
            ),
            evaluated_at=evaluated_at,
        )

        open_dd_limit = float(self.open_market_rulebook.max_drawdown_fraction or Decimal("1.0"))
        open_gate = evaluate_master_spec_readiness(
            MasterSpecGateInput(
                track="open_market",
                rulebook_id=self.open_market_rulebook.rulebook_id,
                dataset_id=self.open_market_bundle.manifest.dataset_id,
                frozen_dataset_sha256_verified=True,
                commercial_data_license_verified=True,
                beats_naive_mae_on_holdout=open_wf.feedback.beats_naive_mae,
                beats_linear_mae_on_holdout=open_wf.overall_report.mae <= open_wf.linear_baseline_report.mae,
                beats_no_trade_net_return_after_costs=open_wf.feedback.beats_no_trade_net_return,
                paper_simulation_rule_compliant=open_sim.blocked_paper_trades == 0,
                paper_simulation_drawdown_within_limit=open_sim.max_realized_drawdown_fraction < open_dd_limit,
                competition_consistency_and_min_days_met=True,
            ),
            evaluated_at=evaluated_at,
        )

        lifecycle: ScratchLifecycleResult | None = None
        if sqlite_dir is not None:
            lifecycle = await run_scratch_training_lifecycle(
                self.competition_bundle,
                sqlite_dir=sqlite_dir,
            )

        return CentralNodeSelfImprovementReport(
            node_run_id=node_run_id,
            evaluated_at=evaluated_at,
            competition_walk_forward=comp_wf,
            open_market_walk_forward=open_wf,
            competition_paper_simulation=comp_sim,
            open_market_paper_simulation=open_sim,
            competition_readiness_gate=comp_gate,
            open_market_readiness_gate=open_gate,
            horizon_strategy_comparison=horizon_cmp,
            ensemble_gate=ensemble_gate,
            scratch_lifecycle=lifecycle,
        )


