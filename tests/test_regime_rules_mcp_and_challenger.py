"""Tests for regime awareness, deterministic trading rules, read-only MCP adapters,
authoritative calendars, data quality gates, microstructure covariates, continuous
24/7 research runner, seasonal/xAI adapters, and baseline-vs-tree walk-forward studies.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sys

import pytest

from atlas.ai.policy import PolicyError
from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.marketdata.frozen import build_frozen_benchmark_dataset
from atlas.marketdata.mcp_adapters import MCPDataSourceAdapter
from atlas.marketdata.microstructure import (
    RawMicrostructureEvent,
    WhaleMicrostructurePolicy,
    normalize_microstructure_covariates,
)
from atlas.marketdata.quality import validate_market_data_batch
from atlas.marketdata.sec_edgar import (
    SECEdgarFilingFact,
    select_as_filed_sec_facts,
    validate_sec_user_agent,
)
from atlas.models.adapters import (
    NaiveForecastProvider,
    SeasonalStatisticalForecastProvider,
    XAINarratorAdapter,
    estimate_token_usage,
)
from atlas.models.calendars import (
    MaintenanceWindow,
    MarketCalendar,
    calendar_session_state,
    construct_authoritative_targets,
)
from atlas.models.challengers import (
    LocalTreeChallengerProvider,
    compare_direct_vs_recursive_horizons,
    evaluate_ensemble_gate,
    fit_boosted_regression_tree,
    fit_regime_conditioned_tree,
    fit_scratch_linear_baseline,
    run_baseline_vs_tree_study,
    run_feature_ablation_study,
    run_scratch_training_lifecycle,
)
from atlas.models.continuous import CentralResearchNode, ContinuousResearchRunner, run_track_paper_simulation
from atlas.models.evaluation import (
    HierarchyAggregationMap,
    ProbabilityCalibrator,
    score_multi_output_forecasts,
    verify_hierarchical_coherence,
)
from atlas.models.model_store import SQLiteModelRegistry
from atlas.models.orchestrator import ModelOrchestrator
from atlas.models.regimes import (
    RegimeConfig,
    ScheduledMacroEvent,
    classify_regime,
)
from atlas.models.registry import InMemoryModelRegistry, MetadataRegistry, ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import (
    AssetClass,
    Capability,
    Eligibility,
    ForecastRequest,
    Horizon,
    Instrument,
    MarketDataRequest,
    ModelRecord,
    ModelRef,
    Observation,
)

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)


def _sample_instrument(calendar_ref: str = "us-equity:xnys:v1", asset_class: AssetClass = AssetClass.ETF) -> Instrument:
    return Instrument(
        instrument_id="test:spy:v1",
        venue="XNYS",
        symbol="SPY",
        asset_class=asset_class,
        quote_currency="USD",
        contract_size="1",
        tick_size="0.01",
        lot_size="1",
        margin_policy_ref="reg-t:v1",
        calendar_ref=calendar_ref,
        settlement="T+1",
        market_data=frozenset({"observations"}),
        permitted_research=True,
    )


def test_authoritative_calendar_sessions_holidays_maintenance_and_funding() -> None:
    session_close = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)
    next_close = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
    third_close = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)
    trad_cal = MarketCalendar(
        calendar_ref="us-equity:xnys:v1",
        market_type="traditional_session",
        timezone="America/New_York",
        session_targets=(session_close, next_close, third_close),
        holidays=("2026-10-20",),
        early_closes=(datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc),),
        maintenance_windows=(
            MaintenanceWindow(
                start_time=datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc),
                reason="Scheduled exchange upgrade",
            ),
        ),
    )
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 13, 35, tzinfo=timezone.utc)) == "opening_auction"
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)) == "regular_open"
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 19, 50, tzinfo=timezone.utc)) == "closing_auction"
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc)) == "maintenance"
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)) == "holiday_closed"

    inst = _sample_instrument()
    hor = Horizon(
        horizon_id="swing:2d:v1",
        sampling="session",
        resolution="1 session",
        steps=2,
        clock="trading",
        family="swing",
        max_data_age_seconds=3600,
        max_forecast_age_seconds=60,
    )
    targets = construct_authoritative_targets(inst, hor, trad_cal, as_of=NOW)
    assert targets == (session_close, third_close)

    crypto_cal = MarketCalendar(
        calendar_ref="crypto:perp:v1",
        market_type="continuous_crypto",
        timezone="UTC",
        funding_timestamps=(datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc),),
    )
    assert calendar_session_state(crypto_cal, as_of=datetime(2026, 10, 19, 15, 50, tzinfo=timezone.utc)) == "funding_window"
    assert calendar_session_state(crypto_cal, as_of=NOW) == "continuous_24_7"


def test_causal_regime_detection_and_unknown_handling() -> None:
    short_obs = (
        Observation(event_time=NOW - timedelta(minutes=10), available_at=NOW - timedelta(minutes=9), value=100.0),
        Observation(event_time=NOW - timedelta(minutes=5), available_at=NOW - timedelta(minutes=4), value=101.0),
    )
    unknown_state = classify_regime(as_of=NOW, instrument_id="test:spy:v1", observations=short_obs)
    assert unknown_state.volatility == "unknown"
    assert unknown_state.trend == "unknown"
    assert unknown_state.execution_permission == "none"
    assert unknown_state.to_feature_value().quality == "unknown"

    shock_obs = tuple(
        Observation(
            event_time=NOW - timedelta(minutes=30 - i * 5),
            available_at=NOW - timedelta(minutes=30 - i * 5) + timedelta(seconds=5),
            value=100.0 * (1.0 + (0.04 * i if i % 2 == 0 else -0.01 * i)),
        )
        for i in range(6)
    )
    crypto_cal = MarketCalendar(
        calendar_ref="crypto:perp:v1",
        market_type="continuous_crypto",
        timezone="UTC",
    )
    event = ScheduledMacroEvent(
        event_id="fomc:2026",
        name="FOMC Rate Decision",
        scheduled_for=NOW + timedelta(minutes=15),
        known_at=NOW - timedelta(days=30),
        impact="high",
    )
    state = classify_regime(
        as_of=NOW,
        instrument_id="comp:btc-perp:v1",
        observations=shock_obs,
        config=RegimeConfig(min_observations=5),
        calendar=crypto_cal,
        liquidity_score=0.20,
        spread_bps=35.0,
        macro_events=(event,),
    )
    assert state.volatility == "shock_vol"
    assert state.liquidity == "stressed_liquidity"
    assert state.session == "continuous_24_7"
    assert state.macro_event == "pre_event"
    assert state.to_feature_value().quality == "verified"

    future_obs = (*shock_obs, Observation(event_time=NOW, available_at=NOW + timedelta(seconds=10), value=120.0))
    with pytest.raises(ValueError, match="Future observation"):
        classify_regime(as_of=NOW, instrument_id="comp:btc-perp:v1", observations=future_obs)


def test_deterministic_trading_rules_default_deny_and_enforcement() -> None:
    import atlas.control.rules as rules_mod
    assert "atlas.ai" not in sys.modules or not any(
        k.startswith("atlas.ai") for k in rules_mod.__dict__.values() if isinstance(k, str)
    )

    account = AccountRiskSnapshot(
        as_of=NOW,
        source="fixture:account",
        initial_equity_usd=Decimal("100000"),
        current_equity_usd=Decimal("99000"),
        high_water_mark_usd=Decimal("102000"),
        start_of_day_equity_usd=Decimal("100000"),
        gross_notional_usd=Decimal("50000"),
        completed_trading_days=5,
        best_day_profit_usd=Decimal("500"),
        total_cumulative_profit_usd=Decimal("2000"),
    )
    candidate = ProposedTradeCheck(
        instrument_id="comp:btc-perp:v1",
        notional_usd=Decimal("20000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("200"),
        holding_horizon_seconds=3600,
        session_state="continuous_24_7",
        data_quality="verified",
        data_age_seconds=30.0,
        license_verified=True,
    )

    unconfigured = TradingRuleBook(
        rulebook_id="empty:v1",
        revision="1",
        track="open_market",
        evidence_ref="pending",
    )
    denied_report = evaluate_trading_rules(unconfigured, account, candidate, evaluated_at=NOW)
    assert not denied_report.compliance_passed
    assert any(v.startswith("default_deny_unconfigured:") for v in denied_report.violations)
    assert denied_report.execution_permission == "none"

    comp_rules = TradingRuleBook(
        rulebook_id="prop:v1",
        revision="1",
        track="competition",
        evidence_ref="prop-rulebook:v1",
        max_per_trade_risk_fraction=Decimal("0.01"),
        required_stop_kind="atr",
        min_stop_distance_bps=Decimal("50"),
        max_daily_loss_fraction=Decimal("0.05"),
        drawdown_mode="trailing",
        max_drawdown_fraction=Decimal("0.10"),
        max_position_notional_usd=Decimal("50000"),
        max_gross_leverage=Decimal("2.0"),
        max_correlated_exposure_fraction=Decimal("0.50"),
        max_sector_exposure_fraction=Decimal("0.50"),
        max_data_age_seconds=300.0,
        max_holding_seconds=7200,
        min_trading_days=5,
        max_single_day_profit_share=0.40,
    )
    ok_report = evaluate_trading_rules(comp_rules, account, candidate, evaluated_at=NOW)
    assert ok_report.compliance_passed
    assert ok_report.execution_permission == "none"
    assert not ok_report.auto_flatten_required

    breached_account = account.model_copy(
        update={
            "current_equity_usd": Decimal("91000"),
            "best_day_profit_usd": Decimal("1800"),
            "total_cumulative_profit_usd": Decimal("2000"),
            "kill_switch_engaged": True,
        }
    )
    breach_report = evaluate_trading_rules(comp_rules, breached_account, candidate, evaluated_at=NOW)
    assert not breach_report.compliance_passed
    assert breach_report.auto_flatten_required
    assert breach_report.kill_switch_active
    assert "daily_loss_circuit_breaker: daily loss limit reached or breached" in breach_report.violations
    assert "max_drawdown_breached:trailing" in breach_report.violations
    assert "competition_consistency_rule_breached: single day profit share too high" in breach_report.violations


def test_mcp_read_only_allowlist_and_fred_training_prohibition() -> None:
    runtime = ProviderRuntime()

    async def fake_transport(provider_id: str, tool_name: str, params: dict) -> dict:
        return {
            "upstream_id": "test-001",
            "timezone": "UTC",
            "adjustment_basis": "split_adjusted",
            "observations": [
                {
                    "event_time": (NOW - timedelta(minutes=15)).isoformat(),
                    "available_at": (NOW - timedelta(minutes=14)).isoformat(),
                    "value": 580.25,
                }
            ],
        }

    with pytest.raises(ValueError, match="disallowed"):
        MCPDataSourceAdapter(
            "irohan0/quant-mcp",
            runtime=runtime,
            transport=fake_transport,
            venue="XNYS",
            calendar_ref="us-equity:xnys:v1",
            license_ref="unknown",
        )

    adapter = MCPDataSourceAdapter(
        "financial_datasets_mcp",
        runtime=runtime,
        transport=fake_transport,
        venue="XNYS",
        calendar_ref="us-equity:xnys:v1",
        license_ref="financial_datasets:pro:v1",
        allow_retention=True,
        allow_training=True,
    )
    registry = ProviderRegistry()
    registry.register(adapter)
    assert len(registry.discover(Capability.DATA_SOURCE)) == 1

    bad_req = MarketDataRequest(
        request_id="req-bad",
        provider_id="financial_datasets_mcp",
        tool_name="place_market_order",
        instrument_id="test:spy:v1",
        as_of=NOW,
        start_time=NOW - timedelta(hours=1),
        end_time=NOW,
    )
    with pytest.raises(PermissionError):
        asyncio.run(adapter.fetch_market_data(bad_req))

    good_req = bad_req.model_copy(update={"tool_name": "get_historical_stock_prices"})
    batch = asyncio.run(adapter.fetch_market_data(good_req))
    assert batch.execution_permission == "none"

    inst = _sample_instrument()
    verified_batch, report = validate_market_data_batch(
        batch,
        inst,
        as_of=NOW,
        max_data_age_seconds=3600,
        intended_use="training",
    )
    assert verified_batch.quality == "verified"
    assert report.quality_status == "verified"

    fred_batch = batch.model_copy(
        update={
            "provenance": batch.provenance.model_copy(
                update={"source_ref": "fin_data_mcp:fred_series", "license_ref": "fred:terms"}
            )
        }
    )
    rejected_batch, fred_report = validate_market_data_batch(
        fred_batch,
        inst,
        as_of=NOW,
        max_data_age_seconds=3600,
        intended_use="training",
    )
    assert rejected_batch.quality == "rejected"
    assert "fred_terms_prohibit_ai_training_and_archival" in fred_report.blocking_issues


def test_frozen_dataset_and_purged_walk_forward_baseline_vs_tree_study() -> None:
    comp_bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    open_bundle = build_frozen_benchmark_dataset(track="open_market", anchor=NOW)
    assert comp_bundle.manifest.dataset_id != open_bundle.manifest.dataset_id

    study = run_baseline_vs_tree_study(comp_bundle, purge_bars=1, embargo_bars=1, cost_bps=4.0)
    assert study.track == "competition"
    assert study.execution_permission == "none"
    assert study.challenger_record.execution_permission == "none"
    assert study.feedback.auto_promoted is False
    assert study.feedback.weights_mutated_in_place is False
    assert study.overall_report.samples >= 4
    assert study.regime_reports

    ablation = run_feature_ablation_study(comp_bundle, cost_bps=4.0)
    assert len(ablation.variants) == 4
    assert ablation.execution_permission == "none"

    tree = fit_boosted_regression_tree(comp_bundle.observations[:24], dataset_id=comp_bundle.manifest.dataset_id)
    provider = LocalTreeChallengerProvider(tree)
    model_ref = ModelRef(provider_id="local_tree", model_id="boosted_stump_v1", revision="1")
    early_as_of = comp_bundle.observations[10].available_at
    early_req = ForecastRequest(
        request_id="req-tree",
        instrument_id=comp_bundle.instrument.instrument_id,
        horizon_id="1h:v1",
        as_of=early_as_of,
        target="price",
        unit="USD",
        observations=comp_bundle.observations[:10],
        target_times=(early_as_of + timedelta(hours=1),),
        dataset_id=comp_bundle.manifest.dataset_id,
        data_license_ref="internal",
        quality="verified",
    )
    with pytest.raises(ValueError, match="lookahead"):
        asyncio.run(provider.forecast(model_ref, early_req))


def test_whale_microstructure_normalization_and_asset_class_boundary() -> None:
    crypto_inst = _sample_instrument(calendar_ref="crypto:perp:v1", asset_class=AssetClass.CRYPTO_DERIVATIVE)
    equity_inst = _sample_instrument(calendar_ref="us-equity:xnys:v1", asset_class=AssetClass.ETF)

    events = (
        RawMicrostructureEvent(
            event_id="evt-1",
            kind="exchange_inflow",
            instrument_id=crypto_inst.instrument_id,
            event_time=NOW - timedelta(minutes=10),
            available_at=NOW - timedelta(minutes=9),
            value=1250.0,
            unit="BTC",
            source="onchain_fixture",
            lineage_ref="onchain:v1",
            license_ref="internal:licensed",
            attribution_confidence=0.90,
            confirmations=12,
            is_internal_custody_reshuffle=False,
        ),
        # Internal custody reshuffle must be excluded automatically
        RawMicrostructureEvent(
            event_id="evt-reshuffle",
            kind="large_transfer",
            instrument_id=crypto_inst.instrument_id,
            event_time=NOW - timedelta(minutes=8),
            available_at=NOW - timedelta(minutes=7),
            value=5000.0,
            unit="BTC",
            source="onchain_fixture",
            lineage_ref="onchain:v1",
            license_ref="internal:licensed",
            is_internal_custody_reshuffle=True,
        ),
        # Low confirmations -> marked quality="unknown"
        RawMicrostructureEvent(
            event_id="evt-unconfirmed",
            kind="exchange_outflow",
            instrument_id=crypto_inst.instrument_id,
            event_time=NOW - timedelta(minutes=5),
            available_at=NOW - timedelta(minutes=4),
            value=300.0,
            unit="BTC",
            source="onchain_fixture",
            lineage_ref="onchain:v1",
            license_ref="internal:licensed",
            confirmations=1,
        ),
    )
    features = normalize_microstructure_covariates(events, crypto_inst, as_of=NOW)
    assert len(features) == 2
    assert features[0].quality == "verified"
    assert features[1].quality == "unknown"

    # Applying an on-chain wallet feature to an Equity/ETF must raise ValueError
    with pytest.raises(ValueError, match="not valid for asset_class"):
        normalize_microstructure_covariates(events[:1], equity_inst, as_of=NOW)


def test_seasonal_statistical_xai_narrator_and_multi_horizon_coherence() -> None:
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    stat_provider = SeasonalStatisticalForecastProvider(seasonal_period=4, ewma_alpha=0.4)
    req = ForecastRequest(
        request_id="req-stat",
        instrument_id=bundle.instrument.instrument_id,
        horizon_id="1h:v1",
        as_of=NOW,
        target="price",
        unit="USD",
        observations=bundle.observations[-8:],
        target_times=(NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
        dataset_id=bundle.manifest.dataset_id,
        data_license_ref="internal",
        quality="verified",
    )
    seasonal_fc = asyncio.run(
        stat_provider.forecast(ModelRef(provider_id="statistical_baseline", model_id="seasonal_naive", revision="1"), req)
    )
    ewma_fc = asyncio.run(
        stat_provider.forecast(ModelRef(provider_id="statistical_baseline", model_id="ewma_level", revision="1"), req)
    )
    assert len(seasonal_fc.points) == 2
    assert ewma_fc.points[0].lower is not None

    lead_report = score_multi_output_forecasts([ewma_fc], [(ewma_fc.points[0].value, ewma_fc.points[1].value)])
    assert lead_report.mae_by_step == (0.0, 0.0)
    assert lead_report.joint_interval_coverage == 1.0

    hmap = HierarchyAggregationMap(
        hierarchy_id="crypto_basket:v1",
        parent_node="total_notional",
        child_nodes=("btc_notional", "eth_notional"),
        weights=(1.0, 1.0),
    )
    coherent, diff = verify_hierarchical_coherence(
        hmap,
        {"total_notional": (150.0, 160.0), "btc_notional": (100.0, 105.0), "eth_notional": (50.0, 55.0)},
    )
    assert coherent and diff == 0.0

    # Metered token pricing & xAI narrator privacy mode and secret screening
    usage = estimate_token_usage("gemini-3.8-flash", 100_000, 20_000)
    assert usage.cost_usd == Decimal("0.150000")

    async def mock_xai_transport(model: str, context: str) -> dict:
        return {
            "text": json.dumps({
                "regime": "volatile",
                "summary": "Mocked xAI narrator note.",
                "confidence": 0.4,
                "risk_flags": ["uncalibrated"],
            }),
            "input_tokens": 500,
            "output_tokens": 100,
        }

    xai = XAINarratorAdapter(zdr_enabled=True, transport=mock_xai_transport)
    assert xai.privacy_mode == "xai:zdr_enabled"
    envelope = asyncio.run(xai.research_metered("Plain market observations"))
    assert envelope.note.regime == "volatile"
    assert envelope.usage.cost_usd == Decimal("0.001600")
    with pytest.raises(PolicyError, match="secret"):
        asyncio.run(xai.research_metered("xai-1234567890abcdefghijklmnop"))


def test_sqlite_durable_approvals_calibrators_and_continuous_runner_halt(tmp_path) -> None:
    store = SQLiteModelRegistry(tmp_path / "durable.sqlite")
    model = ModelRef(provider_id="naive", model_id="last_value", revision="1")
    store.register(
        ModelRecord(
            model=model,
            artifact_uri="builtin:naive",
            artifact_sha256="a" * 64,
            dataset_id="frozen:v1",
            experiment_id="exp:v1",
            license_ref="internal",
            commercial_use_verified=True,
        )
    )
    app_rec = Eligibility(
        model=model,
        instrument_id="comp:btc-perp:v1",
        horizon_id="1h:v1",
        target="price",
        unit="USD",
        strategy_family="baseline",
        evaluation_ref="eval:v1",
        approver="founder",
        approved_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=4),
        max_cost_bps=10.0,
        min_liquidity_score=0.5,
        research_approved=True,
    )
    key = store.register_approval(app_rec)
    assert len(store.list_approvals()) == 1
    revoked = store.revoke_approval(key, reviewer="founder_audit")
    assert not revoked.research_approved
    assert [action for action, _, _ in store.approval_history(key)] == ["approve", "revoke"]

    cal = ProbabilityCalibrator.fit(
        probabilities=[0.7] * 20,
        outcomes=[1] * 14 + [0] * 6,
        calibration_id="cal:sqlite:v1",
        instrument_id="comp:btc-perp:v1",
        horizon_id="1h:v1",
        model_revision="1",
        target="price",
        unit="USD",
        fitted_through=NOW - timedelta(hours=2),
    )
    store.register_calibrator("naive", "last_value", cal)
    assert len(store.list_calibrators()) == 1

    # ContinuousResearchRunner: test healthy tick vs automatic halt on hash mismatch (no silent fallback)
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    runtime = ProviderRuntime()

    async def transport(provider_id: str, tool_name: str, params: dict) -> dict:
        return {
            "upstream_id": "cycle-1",
            "timezone": "UTC",
            "adjustment_basis": "raw",
            "observations": [
                {
                    "event_time": o.event_time.isoformat(),
                    "available_at": o.available_at.isoformat(),
                    "value": o.value,
                }
                for o in bundle.observations[-6:]
            ],
        }

    mcp = MCPDataSourceAdapter(
        "alpha_vantage_mcp",
        runtime=runtime,
        transport=transport,
        venue=bundle.instrument.venue,
        calendar_ref=bundle.instrument.calendar_ref,
        license_ref="internal:licensed",
        allow_retention=True,
        allow_competition=True,
    )
    providers = ProviderRegistry()
    providers.register(NaiveForecastProvider())
    instruments, horizons = MetadataRegistry(), MetadataRegistry()
    instruments.register(bundle.instrument)
    hor = Horizon(
        horizon_id="1h:v1",
        sampling="time",
        resolution="1h",
        steps=2,
        clock="wall",
        family="intraday",
        max_data_age_seconds=7200,
        max_forecast_age_seconds=60,
    )
    horizons.register(hor)
    mem_models = InMemoryModelRegistry()
    mem_models.register(store.get(model))
    orch = ModelOrchestrator(
        providers,
        instruments,
        horizons,
        mem_models,
        (app_rec,),
        {"naive": ProviderRuntime()},
        now=lambda: NOW,
    )
    rulebook = TradingRuleBook(
        rulebook_id="comp:v1",
        revision="1",
        track="competition",
        evidence_ref="doc",
        max_per_trade_risk_fraction=Decimal("0.01"),
        min_stop_distance_bps=Decimal("50"),
        max_daily_loss_fraction=Decimal("0.05"),
        max_drawdown_fraction=Decimal("0.10"),
        max_position_notional_usd=Decimal("50000"),
        max_gross_leverage=Decimal("2.0"),
        max_correlated_exposure_fraction=Decimal("0.50"),
        max_sector_exposure_fraction=Decimal("0.50"),
        max_data_age_seconds=3600.0,
        max_holding_seconds=7200,
        min_trading_days=5,
    )
    runner = ContinuousResearchRunner(
        data_provider=mcp,
        orchestrator=orch,
        instrument=bundle.instrument,
        horizon=hor,
        calendar=bundle.calendar,
        rulebook=rulebook,
    )
    data_req = MarketDataRequest(
        request_id="cycle-req-1",
        provider_id="alpha_vantage_mcp",
        tool_name="DIGITAL_CURRENCY_DAILY",
        instrument_id=bundle.instrument.instrument_id,
        as_of=NOW,
        start_time=NOW - timedelta(hours=6),
        end_time=NOW,
    )
    acct = AccountRiskSnapshot(
        as_of=NOW,
        source="fixture",
        initial_equity_usd=Decimal("100000"),
        current_equity_usd=Decimal("100000"),
        high_water_mark_usd=Decimal("100000"),
        start_of_day_equity_usd=Decimal("100000"),
        gross_notional_usd=Decimal("10000"),
        completed_trading_days=5,
    )
    cand = ProposedTradeCheck(
        instrument_id=bundle.instrument.instrument_id,
        notional_usd=Decimal("10000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("100"),
        holding_horizon_seconds=3600,
        session_state="continuous_24_7",
        data_quality="verified",
        data_age_seconds=10.0,
        license_verified=True,
    )
    healthy = asyncio.run(
        runner.run_cycle(cycle_id="c1", data_request=data_req, account_snapshot=acct, trade_candidate=cand)
    )
    assert healthy.audit_event.scope_status == "healthy"
    assert healthy.execution_permission == "none"

    halted = asyncio.run(
        runner.run_cycle(
            cycle_id="c2",
            data_request=data_req,
            account_snapshot=acct,
            trade_candidate=cand,
            expected_content_sha256="f" * 64,
        )
    )
    assert halted.audit_event.scope_status == "unavailable_halted"
    assert halted.audit_event.halt_reason == "integrity_hash_mismatch"
    assert halted.audit_event.fallback_attempted is False


def test_scratch_linear_and_tree_training_lifecycle_with_rollback(tmp_path) -> None:
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    linear = fit_scratch_linear_baseline(bundle.observations[:24], dataset_id=bundle.manifest.dataset_id)
    assert len(linear.weights) == 3

    lifecycle = asyncio.run(run_scratch_training_lifecycle(bundle, sqlite_dir=tmp_path))
    assert lifecycle.training_job.state == "succeeded"
    assert lifecycle.challenger_record.execution_permission == "none"
    assert lifecycle.execution_permission == "none"
    assert lifecycle.alias_before_rollback.model_id == "gbdt_depth2_v1"
    assert lifecycle.alias_after_rollback.model_id == "last_value"
    assert lifecycle.linear_baseline_mae > 0
    assert lifecycle.tree_challenger_mae > 0


def test_sec_edgar_point_in_time_as_filed_and_restatement_exclusion() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        validate_sec_user_agent("bad-agent")
    assert validate_sec_user_agent("ATLASResearch compliance@atlas-example.com")

    period_end = NOW - timedelta(days=45)
    original_10q = SECEdgarFilingFact(
        accession_number="0001-26-000001",
        cik="0000320193",
        instrument_id="open:spy-etf:v1",
        form_type="10-Q",
        concept="Revenues",
        value=85_000.0,
        unit="USD_millions",
        fiscal_period_end=period_end,
        acceptance_time=NOW - timedelta(days=10),
    )
    # Amendment 10-Q/A filed BEFORE as_of
    prior_amendment = SECEdgarFilingFact(
        accession_number="0001-26-000002",
        cik="0000320193",
        instrument_id="open:spy-etf:v1",
        form_type="10-Q/A",
        concept="Revenues",
        value=84_200.0,
        unit="USD_millions",
        fiscal_period_end=period_end,
        acceptance_time=NOW - timedelta(days=2),
        is_amendment=True,
    )
    # Future restatement accepted AFTER as_of -> must never leak into as_of
    future_restatement = SECEdgarFilingFact(
        accession_number="0001-26-000003",
        cik="0000320193",
        instrument_id="open:spy-etf:v1",
        form_type="10-Q/A",
        concept="Revenues",
        value=79_000.0,
        unit="USD_millions",
        fiscal_period_end=period_end,
        acceptance_time=NOW + timedelta(days=5),
        is_amendment=True,
    )
    facts = (original_10q, prior_amendment, future_restatement)

    as_filed_only = select_as_filed_sec_facts(
        facts, instrument_id="open:spy-etf:v1", as_of=NOW, allow_vintage_amendments=False
    )
    assert len(as_filed_only) == 1
    assert as_filed_only[0].value == 85_000.0

    vintage_replay = select_as_filed_sec_facts(
        facts, instrument_id="open:spy-etf:v1", as_of=NOW, allow_vintage_amendments=True
    )
    assert len(vintage_replay) == 1
    assert vintage_replay[0].value == 84_200.0


def test_regime_conditioned_tree_gate_direct_vs_recursive_and_ensemble_gate() -> None:
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    study = run_baseline_vs_tree_study(bundle, purge_bars=1, embargo_bars=1, cost_bps=4.0)

    locked_study = study.model_copy(update={"regime_variant_unlocked": False})
    with pytest.raises(PermissionError, match="locked"):
        fit_regime_conditioned_tree(bundle, prerequisite_study=locked_study)

    unlocked_study = study.model_copy(update={"regime_variant_unlocked": True})
    regime_tree = fit_regime_conditioned_tree(bundle, prerequisite_study=unlocked_study)
    assert regime_tree.execution_permission == "none"
    assert regime_tree.predict_return((0.002, 0.001, 0.003), "low_vol") != regime_tree.predict_return(
        (0.002, 0.001, 0.003), "shock_vol"
    )

    d_vs_r = compare_direct_vs_recursive_horizons(bundle, steps=3)
    assert d_vs_r.steps == 3
    assert len(d_vs_r.direct_mae_by_step) == 3
    assert len(d_vs_r.recursive_mae_by_step) == 3
    assert d_vs_r.execution_permission == "none"

    ens_report = evaluate_ensemble_gate(bundle, weights=(0.4, 0.6))
    assert ens_report.combiner_enabled is False
    assert ens_report.execution_permission == "none"


def test_central_research_node_and_track_paper_simulation(tmp_path) -> None:
    comp_bundle = build_frozen_benchmark_dataset(track="competition", anchor=NOW)
    open_bundle = build_frozen_benchmark_dataset(track="open_market", anchor=NOW)

    comp_rulebook = TradingRuleBook(
        rulebook_id="prop-comp:v1",
        revision="1.0.0",
        track="competition",
        evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md",
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
    open_rulebook = TradingRuleBook(
        rulebook_id="open-market:v1",
        revision="1.0.0",
        track="open_market",
        evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md",
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

    # Track mismatch must fail closed
    with pytest.raises(ValueError, match="must match rulebook track"):
        run_track_paper_simulation(comp_bundle, open_rulebook)

    node = CentralResearchNode(
        competition_bundle=comp_bundle,
        open_market_bundle=open_bundle,
        competition_rulebook=comp_rulebook,
        open_market_rulebook=open_rulebook,
    )
    report = asyncio.run(
        node.run_self_improvement_loop(
            node_run_id="node:test:v1",
            evaluated_at=NOW,
            sqlite_dir=tmp_path,
        )
    )
    assert report.execution_permission == "none"
    assert report.auto_promoted is False
    assert report.in_place_weight_mutation is False
    assert report.competition_paper_simulation.simulation_only is True
    assert report.competition_paper_simulation.execution_permission == "none"
    assert report.competition_paper_simulation.total_steps > 20
    assert report.open_market_paper_simulation.simulation_only is True
    assert report.open_market_paper_simulation.execution_permission == "none"
    assert report.competition_readiness_gate.execution_permission == "none"
    assert report.competition_readiness_gate.capital_pathway_prereqs_met is False
    assert "live_execution_engine_audit_pending" in report.competition_readiness_gate.unmet_capital_pathway_gates
    assert report.open_market_readiness_gate.execution_permission == "none"
    assert report.open_market_readiness_gate.capital_pathway_prereqs_met is False
    assert report.scratch_lifecycle is not None
    assert report.scratch_lifecycle.training_job.state == "succeeded"


def test_actionable_control_plane_engine_and_api_endpoints() -> None:
    from fastapi.testclient import TestClient
    from atlas.api.app import app

    client = TestClient(app)

    # 1. Inspect initial actionable state
    state_res = client.get("/api/control/state")
    assert state_res.status_code == 200
    state_body = state_res.json()
    assert state_body["kill_switch_engaged"] is False
    assert len(state_body["open_positions"]) >= 1

    # 2. Submit a valid rule-compliant order via POST /api/control/order
    order_res = client.post(
        "/api/control/order",
        json={
            "track": "competition",
            "instrument_id": "comp:btc-perp:v1",
            "side": "buy",
            "notional_usd": "15000",
            "stop_kind": "atr",
            "stop_distance_bps": "150",
            "holding_horizon_seconds": 7200,
        },
    )
    assert order_res.status_code == 200
    order_body = order_res.json()
    assert order_body["decision"]["control_plane_decision"] == "authorized_and_executed"
    assert order_body["decision"]["position_id"] is not None

    # 3. Submit an oversized order that violates max_position_notional_usd -> rejected deterministically
    bad_order_res = client.post(
        "/api/control/order",
        json={
            "track": "competition",
            "instrument_id": "comp:btc-perp:v1",
            "side": "sell",
            "notional_usd": "95000",
            "stop_kind": "atr",
            "stop_distance_bps": "150",
            "holding_horizon_seconds": 7200,
        },
    )
    assert bad_order_res.status_code == 200
    bad_body = bad_order_res.json()
    assert bad_body["decision"]["control_plane_decision"] == "rejected_by_control_plane"
    assert len(bad_body["decision"]["violations"]) > 0

    # 4. Trigger self-training and lifecycle promotion/rollback via POST endpoints
    train_res = client.post("/api/research/train")
    assert train_res.status_code == 200
    assert train_res.json()["training_runs_completed"] >= 2

    promote_res = client.post("/api/control/lifecycle", json={"action": "promote_challenger"})
    assert promote_res.status_code == 200
    assert "local_tree:boosted_stump_v1" in promote_res.json()["active_champion_model"]

    rollback_res = client.post("/api/control/lifecycle", json={"action": "rollback_to_champion"})
    assert rollback_res.status_code == 200
    assert rollback_res.json()["active_champion_model"] == "naive:last_value:v1"

    # 5. Engage kill switch -> auto-flattens all open positions & blocks orders; then reset kill switch
    ks_on = client.post("/api/control/kill-switch", json={"engaged": True, "reason": "test_emergency_halt"})
    assert ks_on.status_code == 200
    assert ks_on.json()["kill_switch_engaged"] is True
    assert len(ks_on.json()["open_positions"]) == 0

    ks_off = client.post("/api/control/kill-switch", json={"engaged": False, "reason": "test_reset"})
    assert ks_off.status_code == 200
    assert ks_off.json()["kill_switch_engaged"] is False

    # 6. Verify production platform snapshot endpoint (/api/platform/snapshot)
    snap_res = client.get("/api/platform/snapshot")
    assert snap_res.status_code == 200
    snap_body = snap_res.json()
    assert snap_body["source"] == "atlas_production_engine"
    assert "with_scoped_approval" in snap_body
    assert "control_plane_state" in snap_body

    # 7. Verify interactive functional endpoints (walk-forward, MCP fetch, market ingest, readiness audit)
    wf_res = client.post(
        "/api/research/walk-forward",
        json={"track": "competition", "cost_bps": 3.5, "purge_bars": 2, "embargo_bars": 1},
    )
    assert wf_res.status_code == 200
    assert wf_res.json()["study"]["purge_bars"] == 2

    mcp_res = client.post(
        "/api/market/mcp-fetch",
        json={"provider_id": "alpha_vantage_mcp", "tool_name": "DIGITAL_CURRENCY_DAILY"},
    )
    assert mcp_res.status_code == 200
    assert mcp_res.json()["quality_status"] == "verified"

    ingest_res = client.post(
        "/api/market/ingest",
        json={"symbol": "BTC-USD", "interval": "1h", "close_price": "68120.50", "volume": "155.0"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["candle"]["close"] == "68120.50"

    audit_res = client.post("/api/control/readiness-audit")
    assert audit_res.status_code == 200
    audit_body = audit_res.json()
    assert audit_body["research_challenger_ready"] is False
    assert audit_body["capital_pathway_prereqs_met"] is False
    assert audit_body["execution_permission"] == "none"
    assert "does_not_beat_no_trade_after_costs" in audit_body["unmet_research_gates"]
    assert "live_execution_engine_audit_pending" in audit_body["unmet_capital_pathway_gates"]

    # 8. Verify snapshot telemetry & interactive microstructure, SEC EDGAR, and 24/7 research tick endpoints
    assert len(snap_body["money_records"]) == 8
    assert len(snap_body["microstructure_covariates"]) == 3
    assert len(snap_body["sec_edgar_facts"]) == 3
    assert snap_body["calendars_telemetry"]["competition_calendar"]["market_type"] == "continuous_crypto"

    micro_res = client.post(
        "/api/market/microstructure",
        json={"kind": "order_flow_imbalance", "value": 0.45, "unit": "ratio", "confirmations": 10, "is_internal_custody_reshuffle": False},
    )
    assert micro_res.status_code == 200
    assert micro_res.json()["accepted_count"] == 1

    sec_res = client.post(
        "/api/market/sec-edgar",
        json={"concept": "Revenues", "value": 96500000000.0, "form_type": "10-Q/A", "allow_vintage_amendments": False},
    )
    assert sec_res.status_code == 200
    assert sec_res.json()["selected_count"] == 0
    assert sec_res.json()["execution_permission"] == "none"

    tick_res = client.post(
        "/api/research/continuous-tick",
        json={"observation_note": "Liquid perpetual session with steady basis.", "workload": "frequent"},
    )
    assert tick_res.status_code == 200
    assert tick_res.json()["status"] == "completed"
    assert tick_res.json()["execution_permission"] == "none"

    # 9. Verify User Profile and Connectors Library endpoints
    prof_get = client.get("/api/profile")
    assert prof_get.status_code == 200
    assert prof_get.json()["role"] == "founder_admin"
    assert prof_get.json()["operator_id"] == "op:founder:001"

    prof_post = client.post(
        "/api/profile",
        json={
            "display_name": "Founder & Principal Architect",
            "title": "Principal Quant & Control-Plane Architect",
            "organization": "ATLAS Autonomous Intelligence",
            "role": "founder_admin",
            "default_track": "competition",
            "risk_profile_pct": "0.75",
            "preferred_timezone": "UTC",
            "default_workload": "frequent",
            "sec_user_agent": "ATLASResearch compliance@atlas.local",
            "alerts_kill_switch": True,
            "alerts_regime_shift": True,
            "alerts_freshness_breach": True,
        },
    )
    assert prof_post.status_code == 200
    assert prof_post.json()["display_name"] == "Founder & Principal Architect"

    conn_get = client.get("/api/connectors")
    assert conn_get.status_code == 200
    assert len(conn_get.json()["connectors"]) == 11

    conn_act = client.post(
        "/api/connectors/action",
        json={"connector_id": "alpha_vantage_mcp", "action": "test_connection"},
    )
    assert conn_act.status_code == 200
    assert conn_act.json()["status"] == "ok"
    assert conn_act.json()["connector"]["connector_id"] == "alpha_vantage_mcp"

    # 10. Verify Live Listings, Data Syncing Center, and Global Platform Configurations endpoints
    list_get = client.get("/api/listings")
    assert list_get.status_code == 200
    assert len(list_get.json()["listings"]) >= 6

    list_act = client.post(
        "/api/listings/action",
        json={
            "instrument_id": "comp:avax-usd:v1",
            "symbol": "AVAX-USD",
            "name": "Avalanche Perpetual Swap",
            "track": "competition",
            "price": "29.40",
            "action": "add_listing",
        },
    )
    assert list_act.status_code == 200
    assert any(item["symbol"] == "AVAX-USD" for item in list_act.json()["listings"])

    sync_get = client.get("/api/sync")
    assert sync_get.status_code == 200
    assert len(sync_get.json()["pipelines"]) == 6

    sync_run = client.post("/api/sync/run", json={"pipeline_id": "all", "cadence": "15s"})
    assert sync_run.status_code == 200
    assert sync_run.json()["status"] == "ok"

    cfg_get = client.get("/api/configurations")
    assert cfg_get.status_code == 200
    assert cfg_get.json()["default_challenger_family"] == "boosted_stump_v1"

    cfg_post = client.post(
        "/api/configurations",
        json={
            "competition_max_notional_usd": "50000.00",
            "open_market_max_notional_usd": "40000.00",
            "daily_loss_limit_pct": "4.00",
            "trailing_drawdown_limit_pct": "8.00",
            "per_trade_risk_limit_pct": "0.75",
            "min_stop_distance_bps": 25,
            "auto_flatten_on_breach": True,
            "enforce_consistency_rule": True,
            "default_challenger_family": "gbdt_depth2_v1",
            "gemini_workload_tier": "deep",
            "secret_context_screening": True,
            "ensemble_correlation_gate": 0.80,
            "default_purge_bars": 1,
            "default_embargo_bars": 1,
            "default_round_trip_cost_bps": 4.0,
            "sync_cadence_seconds": 15,
            "provider_timeout_ms": 8000,
            "max_provider_retries": 2,
            "circuit_breaker_threshold": 3,
            "sec_edgar_rate_limit_rps": 10,
        },
    )
    assert cfg_post.status_code == 200
    assert cfg_post.json()["default_challenger_family"] == "gbdt_depth2_v1"

    # 11. Verify API Data Warehouse (/api/warehouse, /api/warehouse/action) & Live Internet Sync
    wh_get = client.get("/api/warehouse")
    assert wh_get.status_code == 200
    assert len(wh_get.json()["nodes"]) == 6
    assert any(n["node_id"] == "bigquery_analytics_hub" for n in wh_get.json()["nodes"])

    wh_act = client.post(
        "/api/warehouse/action",
        json={
            "node_id": "bigquery_analytics_hub",
            "action": "run_pit_query",
            "sql_filter": "SELECT symbol, close, available_at FROM atlas_pit_ohlcv_1h WHERE available_at <= as_of LIMIT 5",
        },
    )
    assert wh_act.status_code == 200
    assert wh_act.json()["status"] == "ok"
    assert wh_act.json()["execution_permission"] == "none"

    live_sync = client.post(
        "/api/market/live-internet-sync",
        json={"symbol": "BTC-USD", "granularity": 3600},
    )
    assert live_sync.status_code == 200
    assert live_sync.json()["status"] == "ok"
    assert len(live_sync.json()["candles"]) >= 6

    # 12. Verify Institutional Quant, Signal, Correlation & DOM Matrix (/api/matrix, /api/matrix/recompute)
    mat_get = client.get("/api/matrix")
    assert mat_get.status_code == 200
    mat_body = mat_get.json()
    assert len(mat_body["signal_matrix"]) == 9
    assert len(mat_body["correlation_matrix"]["tickers"]) == 9
    assert len(mat_body["correlation_matrix"]["values"]) == 9
    assert len(mat_body["model_regime_matrix"]) == 5
    assert len(mat_body["orderbook_dom"]["bids"]) == 6

    mat_recomp = client.post(
        "/api/matrix/recompute",
        json={"symbol": "NVDA", "horizon_filter": "1h"},
    )
    assert mat_recomp.status_code == 200
    assert mat_recomp.json()["status"] == "ok"
    assert mat_recomp.json()["execution_permission"] == "none"
    assert mat_recomp.json()["active_symbol"] == "NVDA"

    # 13. Verify 7-Tab Master Roadmap (A-Z), Whale Order Flow ML (WF-01..WF-08) & Prop B2B SaaS Verticals
    rm_get = client.get("/api/master-roadmap")
    assert rm_get.status_code == 200
    rm_body = rm_get.json()
    assert len(rm_body["roadmap_az"]) == 26
    assert all(r["status"] == "Implemented" for r in rm_body["roadmap_az"])
    assert len(rm_body["b2b_saas_verticals"]) == 12
    assert len(rm_body["whale_execution_ml"]) == 8
    assert len(rm_body["global_multi_domain"]) == 5
    assert len(rm_body["whale_decision_matrix"]) == 5
    assert rm_body["execution_permission"] == "none"

    wf_eval = client.post(
        "/api/master-roadmap/evaluate-whale",
        json={"symbol": "NVDA", "scenario_index": 2, "whale_shares": 25000, "urgency_kappa": 0.65},
    )
    assert wf_eval.status_code == 200
    wf_body = wf_eval.json()
    assert wf_body["focus_symbol"] == "NVDA"
    assert wf_body["execution_permission"] == "none"
    assert wf_body["live_wf_telemetry"]["wf04_almgren_chriss"]["total_shares"] == 25000.0
    assert wf_body["whale_decision_matrix"][2]["active"] is True

    saas_act = client.post(
        "/api/master-roadmap/saas-action",
        json={"vertical_id": "SAAS-03", "action": "sybil_scan"},
    )
    assert saas_act.status_code == 200
    assert saas_act.json()["status"] == "ok"
    assert saas_act.json()["execution_permission"] == "none"











