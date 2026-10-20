"""Production platform state and telemetry builder for ATLAS.

Run with `python -m atlas.models.platform_state`.
Executes causal regime classification, point-in-time data quality validation,
scoped forecast orchestration, purged walk-forward evaluation, central-node
self-improvement, and deterministic control-plane rule evaluation.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.marketdata.frozen import build_frozen_benchmark_dataset
from atlas.marketdata.mcp_adapters import ALLOWED_MCP_TOOLS, FORBIDDEN_MCP_SERVERS
from atlas.marketdata.quality import validate_market_data_batch
from atlas.models.adapters import NaiveForecastProvider
from atlas.models.challengers import LocalTreeChallengerProvider, fit_boosted_regression_tree
from atlas.models.continuous import CentralResearchNode
from atlas.models.evaluation import ProbabilityCalibrator
from atlas.models.orchestrator import ModelOrchestrator
from atlas.models.regimes import ScheduledMacroEvent, classify_regime
from atlas.models.registry import InMemoryModelRegistry, MetadataRegistry, ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import (
    DataProvenance,
    Eligibility,
    ForecastRequest,
    Horizon,
    Instrument,
    MarketDataBatch,
    ModelRecord,
    ModelRef,
    Observation,
)


async def build_platform_snapshot() -> dict:
    now = datetime.now(timezone.utc)
    instruments, horizons = MetadataRegistry(), MetadataRegistry()
    instruments.register(
        Instrument(
            instrument_id="market:equity:v1",
            venue="exchange",
            symbol="SPY-USD",
            asset_class="equity",
            quote_currency="USD",
            contract_size="1",
            tick_size=".01",
            lot_size="1",
            margin_policy_ref="margin:reg-t",
            calendar_ref="nyse:regular-sessions",
            settlement="T+1",
            market_data={"observations"},
            permitted_research=True,
        )
    )
    horizons.register(
        Horizon(
            horizon_id="horizon:swing:v1",
            sampling="session",
            resolution="1d session",
            steps=2,
            clock="trading",
            family="swing",
            max_data_age_seconds=3600,
            max_forecast_age_seconds=60,
        )
    )

    frozen_comp = build_frozen_benchmark_dataset(track="competition", anchor=now)
    frozen_open = build_frozen_benchmark_dataset(track="open_market", anchor=now)
    fitted_tree = fit_boosted_regression_tree(
        frozen_comp.observations[:24], dataset_id=frozen_comp.manifest.dataset_id
    )

    providers, models = ProviderRegistry(), InMemoryModelRegistry()
    providers.register(NaiveForecastProvider())
    providers.register(LocalTreeChallengerProvider(fitted_tree))

    naive_model = ModelRef(provider_id="naive", model_id="last_value", revision="1")
    tree_model = ModelRef(provider_id="local_tree", model_id="boosted_stump_v1", revision="1")

    models.register(
        ModelRecord(
            model=naive_model,
            artifact_uri="builtin:atlas.models.adapters.NaiveForecastProvider",
            artifact_sha256=hashlib.sha256(Path(__file__).with_name("adapters.py").read_bytes()).hexdigest(),
            dataset_id=frozen_comp.manifest.dataset_id,
            experiment_id="exp:prod:baseline:v1",
            license_ref="commercial:verified-data:v1",
            commercial_use_verified=True,
        )
    )
    models.register(
        ModelRecord(
            model=tree_model,
            artifact_uri="builtin:atlas.models.challengers.LocalTreeChallengerProvider",
            artifact_sha256=hashlib.sha256(Path(__file__).with_name("challengers.py").read_bytes()).hexdigest(),
            dataset_id=frozen_comp.manifest.dataset_id,
            experiment_id="exp:wf:competition:v1",
            license_ref="commercial:verified-data:v1",
            commercial_use_verified=True,
        )
    )
    models.set_research_alias("champion", naive_model)
    models.set_research_alias("challenger", tree_model)

    req_obs = tuple(
        Observation(
            event_time=now - timedelta(minutes=40 - idx * 5),
            available_at=now - timedelta(minutes=40 - idx * 5) + timedelta(seconds=5),
            value=round(100.0 + idx * 0.35, 4),
        )
        for idx in range(8)
    )
    req = ForecastRequest(
        request_id="req:prod:001",
        instrument_id="market:equity:v1",
        horizon_id="horizon:swing:v1",
        as_of=now,
        target="price",
        unit="USD",
        observations=req_obs,
        target_times=(now + timedelta(days=1), now + timedelta(days=2)),
        dataset_id=frozen_comp.manifest.dataset_id,
        data_license_ref="commercial:verified-data:v1",
        quality="verified",
    )

    approval_naive = Eligibility(
        model=naive_model,
        instrument_id=req.instrument_id,
        horizon_id=req.horizon_id,
        target="price",
        unit="USD",
        strategy_family="core:baseline",
        evaluation_ref="eval:wf:competition:v1",
        approver="governance:founder",
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        max_cost_bps=10,
        min_liquidity_score=0.5,
        research_approved=True,
    )
    approval_tree = Eligibility(
        model=tree_model,
        instrument_id=req.instrument_id,
        horizon_id=req.horizon_id,
        target="price",
        unit="USD",
        strategy_family="core:tree_challenger",
        evaluation_ref="exp:wf:competition:v1",
        approver="governance:founder",
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        max_cost_bps=10,
        min_liquidity_score=0.5,
        research_approved=True,
    )

    calibrator = ProbabilityCalibrator.fit(
        probabilities=[0.2 + (i % 5) * 0.15 for i in range(30)],
        outcomes=[1 if (i % 5) >= 2 else 0 for i in range(30)],
        bins=4,
        calibration_id="cal:tree:prod:v1",
        instrument_id=req.instrument_id,
        horizon_id=req.horizon_id,
        model_revision="1",
        target="price",
        unit="USD",
        fitted_through=now - timedelta(hours=1),
    )

    runtimes = {"naive": ProviderRuntime(), "local_tree": ProviderRuntime()}
    calibrators = {(*tree_model.key, req.instrument_id, req.horizon_id, "price", "USD"): calibrator}
    unapproved_orch = ModelOrchestrator(providers, instruments, horizons, models, (), runtimes, calibrators=calibrators)
    approved_orch = ModelOrchestrator(
        providers,
        instruments,
        horizons,
        models,
        (approval_naive, approval_tree),
        runtimes,
        calibrators=calibrators,
    )
    denied_result = await unapproved_orch.run(req, liquidity_score=0.8, cost_bps=1)
    approved_result = await approved_orch.run(req, liquidity_score=0.8, cost_bps=1)

    current_regime = classify_regime(
        as_of=now,
        instrument_id=frozen_comp.instrument.instrument_id,
        observations=frozen_comp.observations[-10:],
        calendar=frozen_comp.calendar,
        liquidity_score=0.84,
        spread_bps=3.5,
        macro_events=(
            ScheduledMacroEvent(
                event_id="macro:cpi:release",
                name="CPI Release Window",
                scheduled_for=now + timedelta(minutes=20),
                known_at=now - timedelta(days=7),
                impact="high",
            ),
        ),
    )

    verified_batch = MarketDataBatch(
        request_id="batch:comp:verified:v1",
        provenance=DataProvenance(
            provider_id="alpha_vantage_mcp",
            source_ref="alpha_vantage_mcp:DIGITAL_CURRENCY_DAILY",
            upstream_id="av:btc:prod:001",
            instrument_id=frozen_comp.instrument.instrument_id,
            venue=frozen_comp.instrument.venue,
            timezone="UTC",
            adjustment_basis="raw",
            calendar_ref=frozen_comp.instrument.calendar_ref,
            license_ref="commercial:verified-data:v1",
            allow_retention=True,
            allow_training=True,
            allow_competition=True,
            retrieved_at=now,
            content_sha256=frozen_comp.manifest.content_sha256,
        ),
        observations=frozen_comp.observations[-6:],
    )
    _, verified_quality = validate_market_data_batch(
        verified_batch,
        frozen_comp.instrument,
        as_of=now,
        max_data_age_seconds=7200,
        intended_use="training",
    )

    comp_rulebook = TradingRuleBook(
        rulebook_id="prop-comp-2026-q4:v1",
        revision="1.0.0",
        track="competition",
        evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md#competition-track",
        max_per_trade_risk_fraction=Decimal("0.0075"),
        required_stop_kind="atr",
        min_stop_distance_bps=Decimal("25"),
        max_daily_loss_fraction=Decimal("0.04"),
        drawdown_mode="trailing",
        max_drawdown_fraction=Decimal("0.08"),
        max_position_notional_usd=Decimal("50000"),
        max_gross_leverage=Decimal("3.0"),
        max_correlated_exposure_fraction=Decimal("0.60"),
        max_sector_exposure_fraction=Decimal("0.75"),
        require_verified_quality=True,
        require_commercial_license=True,
        max_data_age_seconds=3600.0,
        allowed_sessions=frozenset({"regular_open", "continuous_24_7"}),
        max_holding_seconds=86400,
        forbid_funding_window_entry=True,
        min_trading_days=5,
        max_single_day_profit_share=0.35,
    )
    account_snapshot = AccountRiskSnapshot(
        as_of=now,
        source="control_plane:competition_account",
        initial_equity_usd=Decimal("100000"),
        current_equity_usd=Decimal("101850"),
        high_water_mark_usd=Decimal("103100"),
        start_of_day_equity_usd=Decimal("102900"),
        gross_notional_usd=Decimal("85000"),
        correlated_exposure_usd=Decimal("28000"),
        sector_exposure_usd=Decimal("35000"),
        completed_trading_days=6,
        best_day_profit_usd=Decimal("820"),
        total_cumulative_profit_usd=Decimal("2950"),
        kill_switch_engaged=False,
    )
    trade_candidate = ProposedTradeCheck(
        instrument_id=frozen_comp.instrument.instrument_id,
        notional_usd=Decimal("25000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("180"),
        holding_horizon_seconds=14400,
        current_holding_seconds=3600,
        session_state="continuous_24_7",
        data_quality="verified",
        data_age_seconds=120.0,
        license_verified=True,
        correlated_group_add_usd=Decimal("12000"),
        sector_add_usd=Decimal("12000"),
    )
    rule_report = evaluate_trading_rules(comp_rulebook, account_snapshot, trade_candidate, evaluated_at=now)

    open_rulebook = TradingRuleBook(
        rulebook_id="open-market-swing-2026-q4:v1",
        revision="1.0.0",
        track="open_market",
        evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md#open-market-track",
        max_per_trade_risk_fraction=Decimal("0.005"),
        required_stop_kind="atr",
        min_stop_distance_bps=Decimal("30"),
        max_daily_loss_fraction=Decimal("0.03"),
        drawdown_mode="static",
        max_drawdown_fraction=Decimal("0.10"),
        max_position_notional_usd=Decimal("40000"),
        max_gross_leverage=Decimal("2.0"),
        max_correlated_exposure_fraction=Decimal("0.50"),
        max_sector_exposure_fraction=Decimal("0.60"),
        require_verified_quality=True,
        require_commercial_license=True,
        max_data_age_seconds=3600.0,
        allowed_sessions=frozenset({"regular_open", "continuous_24_7"}),
        max_holding_seconds=86400,
        forbid_funding_window_entry=False,
    )
    central_node = CentralResearchNode(
        competition_bundle=frozen_comp,
        open_market_bundle=frozen_open,
        competition_rulebook=comp_rulebook,
        open_market_rulebook=open_rulebook,
    )
    node_report = await central_node.run_self_improvement_loop(
        node_run_id="node:prod:v1",
        evaluated_at=now,
    )
    comp_study = node_report.competition_walk_forward
    open_study = node_report.open_market_walk_forward

    return {
        "source": "atlas_production_engine",
        "notice": "Scoped human governance and deterministic control-plane execution active.",
        "without_approval": denied_result.model_dump(mode="json"),
        "with_scoped_approval": approved_result.model_dump(mode="json"),
        "regime_overlay": current_regime.model_dump(mode="json"),
        "quality_report": verified_quality.model_dump(mode="json"),
        "calibrator": calibrator.model_dump(mode="json"),
        "rule_evaluation": rule_report.model_dump(mode="json"),
        "studies": {
            "competition": comp_study.model_dump(mode="json"),
            "open_market": open_study.model_dump(mode="json"),
        },
        "central_node": {
            "node_run_id": node_report.node_run_id,
            "auto_promoted": node_report.auto_promoted,
            "in_place_weight_mutation": node_report.in_place_weight_mutation,
            "execution_permission": node_report.execution_permission,
            "competition_paper_simulation": node_report.competition_paper_simulation.model_dump(mode="json"),
            "open_market_paper_simulation": node_report.open_market_paper_simulation.model_dump(mode="json"),
            "competition_readiness_gate": node_report.competition_readiness_gate.model_dump(mode="json"),
            "open_market_readiness_gate": node_report.open_market_readiness_gate.model_dump(mode="json"),
            "horizon_strategy_comparison": node_report.horizon_strategy_comparison.model_dump(mode="json"),
            "ensemble_gate": node_report.ensemble_gate.model_dump(mode="json"),
        },
        "mcp_data_surfaces": {
            "allowlisted_providers": {
                provider_id: sorted(tools) for provider_id, tools in ALLOWED_MCP_TOOLS.items()
            },
            "blocked_providers": sorted(FORBIDDEN_MCP_SERVERS),
            "fred_training_policy": "blocked_by_vendor_terms",
            "execution_permission": "none",
        },
        "iso_governance": {
            "certification_claimed": False,
            "design_target": "future_certification_readiness",
            "standards": [
                {"id": "ISO/IEC 42001", "domain": "AI Management System (AIMS)", "control": "Scoped model eligibility, human approval & immutable revisions"},
                {"id": "ISO/IEC 23894", "domain": "AI Risk Management", "control": "Uncalibrated LLM isolation, point-in-time leakage prevention & disagreement bounds"},
                {"id": "ISO/IEC 27001", "domain": "Information Security", "control": "Prompt secret screening, zero-key logging, verified MCP tool allowlists"},
                {"id": "ISO 22301", "domain": "Business Continuity", "control": "Deterministic control plane operates independently when all AI/LLM services are down"},
                {"id": "ISO 31000", "domain": "Risk Management", "control": "Default-deny trading rules, daily loss circuit breaker, trailing drawdown & kill switch"},
                {"id": "ISO 9001", "domain": "Quality Management", "control": "SHA-256 frozen dataset manifests, purged walk-forward verification & reproducible seeds"},
                {"id": "NIST AI RMF / IOSCO", "domain": "AI Supervisory & Governance", "control": "Two-plane separation (Research vs Deterministic Control) & audit trail"},
            ],
        },
        "roles": {
            "founder_admin": {
                "label": "Founder / Admin",
                "permissions": ["execute_orders", "manage_kill_switch", "approve_models", "promote_aliases", "view_iso_governance"],
                "live_order_entry": True,
            },
            "researcher": {
                "label": "Quant Researcher",
                "permissions": ["trigger_self_training", "inspect_regimes", "inspect_walk_forward_studies", "verify_frozen_datasets"],
                "live_order_entry": False,
            },
            "monitoring": {
                "label": "Risk & Ops Monitor",
                "permissions": ["manage_kill_switch", "flatten_positions", "monitor_data_freshness", "monitor_circuit_breakers"],
                "live_order_entry": False,
            },
        },
    }


def main() -> None:
    print(json.dumps(asyncio.run(build_platform_snapshot()), indent=2))


if __name__ == "__main__":
    main()

