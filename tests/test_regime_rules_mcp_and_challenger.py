"""Tests for regime awareness, deterministic trading rules, read-only MCP adapters,
authoritative calendars, data quality gates, and baseline-vs-tree walk-forward studies.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sys

import pytest
from pydantic import ValidationError

from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.marketdata.frozen import build_frozen_benchmark_dataset
from atlas.marketdata.mcp_adapters import MCPDataSourceAdapter
from atlas.marketdata.quality import validate_market_data_batch
from atlas.models.calendars import (
    MaintenanceWindow,
    MarketCalendar,
    calendar_session_state,
    construct_authoritative_targets,
)
from atlas.models.challengers import (
    LocalTreeChallengerProvider,
    fit_boosted_regression_tree,
    run_baseline_vs_tree_study,
)
from atlas.models.regimes import (
    RegimeConfig,
    ScheduledMacroEvent,
    classify_regime,
)
from atlas.models.registry import ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import (
    AssetClass,
    Capability,
    ForecastRequest,
    Horizon,
    Instrument,
    MarketDataRequest,
    ModelRef,
    Observation,
)

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)


def _sample_instrument(calendar_ref: str = "us-equity:xnys:v1") -> Instrument:
    return Instrument(
        instrument_id="test:spy:v1",
        venue="XNYS",
        symbol="SPY",
        asset_class=AssetClass.ETF,
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
    # 13:35 UTC is 5 mins after 13:30 UTC open (20:00 close - 390 mins) -> opening_auction
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 13, 35, tzinfo=timezone.utc)) == "opening_auction"
    # 16:00 UTC is mid-session -> regular_open
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)) == "regular_open"
    # 19:50 UTC is 10 mins before 20:00 UTC close -> closing_auction
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 19, 50, tzinfo=timezone.utc)) == "closing_auction"
    # 22:30 UTC is inside maintenance window -> maintenance
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc)) == "maintenance"
    # 2026-10-20 is a declared holiday -> holiday_closed
    assert calendar_session_state(trad_cal, as_of=datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)) == "holiday_closed"

    # Target construction skips 2026-10-20 holiday automatically
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

    # Crypto calendar funding window detection
    crypto_cal = MarketCalendar(
        calendar_ref="crypto:perp:v1",
        market_type="continuous_crypto",
        timezone="UTC",
        funding_timestamps=(datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc),),
    )
    assert calendar_session_state(crypto_cal, as_of=datetime(2026, 10, 19, 15, 50, tzinfo=timezone.utc)) == "funding_window"
    assert calendar_session_state(crypto_cal, as_of=NOW) == "continuous_24_7"


def test_causal_regime_detection_and_unknown_handling() -> None:
    # Insufficient observations -> volatility and trend stay "unknown"
    short_obs = (
        Observation(event_time=NOW - timedelta(minutes=10), available_at=NOW - timedelta(minutes=9), value=100.0),
        Observation(event_time=NOW - timedelta(minutes=5), available_at=NOW - timedelta(minutes=4), value=101.0),
    )
    unknown_state = classify_regime(as_of=NOW, instrument_id="test:spy:v1", observations=short_obs)
    assert unknown_state.volatility == "unknown"
    assert unknown_state.trend == "unknown"
    assert unknown_state.execution_permission == "none"
    assert unknown_state.to_feature_value().quality == "unknown"

    # Shock volatility + uptrend + pre-event macro window
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

    # Future observation availability must be rejected
    future_obs = (*shock_obs, Observation(event_time=NOW, available_at=NOW + timedelta(seconds=10), value=120.0))
    with pytest.raises(ValueError, match="Future observation"):
        classify_regime(as_of=NOW, instrument_id="comp:btc-perp:v1", observations=future_obs)


def test_deterministic_trading_rules_default_deny_and_enforcement() -> None:
    # Verify control plane does not import LLM modules
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

    # Unconfigured rulebook defaults to DENY
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

    # Configured competition rulebook passes compliant trade but keeps execution_permission="none"
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

    # Breach daily loss, trailing drawdown, consistency rule, and kill switch -> triggers auto-flatten
    breached_account = account.model_copy(
        update={
            "current_equity_usd": Decimal("91000"),  # >5% daily loss and >10% trailing DD from 102k
            "best_day_profit_usd": Decimal("1800"),
            "total_cumulative_profit_usd": Decimal("2000"),  # 90% single day profit share > 40%
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

    # Forbidden mutating MCP server (`irohan0/quant-mcp`) is rejected on construction
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

    # Write or non-allowlisted tool call is rejected before transport
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

    # FRED source is explicitly rejected for training/retention per Decision #29
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

    # Verify LocalTreeChallengerProvider enforces lookahead boundary
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

