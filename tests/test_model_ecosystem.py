import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atlas.models.adapters import GeminiResearchAdapter, NaiveForecastProvider
from atlas.models.calendars import SessionSchedule, resolve_session_targets
from atlas.models.evaluation import EvaluationRow, ProbabilityCalibrator, evaluate, evaluate_operations
from atlas.models.experiments import ExperimentStore
from atlas.models.orchestrator import ModelOrchestrator
from atlas.models.registry import InMemoryModelRegistry, MetadataRegistry, ProviderRegistry
from atlas.models.runtime import CallPolicy, CircuitOpen, ProviderRuntime, RateLimited, TransientProviderError
from atlas.models.schemas import (
    AssetClass, Capability, DatasetManifest, Eligibility, ForecastRequest, Horizon, Instrument,
    ModelRecord, ModelRef, Observation, ProviderInfo, TrainingJob, TrainingRequest, Usage,
)
from atlas.models.training import TrainingCoordinator

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
MODEL = ModelRef(provider_id="naive", model_id="last_value", revision="1")


def instrument(asset_class=AssetClass.EQUITY):
    extra = {}
    if asset_class in {AssetClass.OPTION, AssetClass.FUTURE}:
        extra["expiry"] = NOW + timedelta(days=30)
    if asset_class == AssetClass.OPTION:
        extra.update(underlying_id="example:share", strike="100", option_right="call")
    return Instrument(instrument_id="example:instrument:v1", venue="example", symbol="TEST",
        asset_class=asset_class, quote_currency="USD", contract_size="1", tick_size=".01",
        lot_size="1", margin_policy_ref="example:cash:v1", calendar_ref="example:sessions:v1",
        settlement="example:T+1", market_data={"trades", "quotes"}, permitted_research=True, **extra)


def horizon():
    return Horizon(horizon_id="session:v1", sampling="session", resolution="1 session", steps=2,
        clock="trading", family="swing", max_data_age_seconds=3600, max_forecast_age_seconds=60)


def request():
    return ForecastRequest(request_id="req1", instrument_id=instrument().instrument_id, horizon_id=horizon().horizon_id,
        as_of=NOW, target="price", unit="USD", dataset_id="fixture:v1", data_license_ref="invented",
        observations=(Observation(event_time=NOW-timedelta(minutes=5), available_at=NOW-timedelta(minutes=4), value=100),),
        target_times=(NOW+timedelta(days=1), NOW+timedelta(days=2)), quality="verified")


def approval(model=MODEL):
    return Eligibility(model=model, instrument_id=instrument().instrument_id, horizon_id=horizon().horizon_id,
        target="price", unit="USD", strategy_family="test_only", evaluation_ref="fixture-evaluation",
        approver="test-human", approved_at=NOW-timedelta(days=1), expires_at=NOW+timedelta(days=1),
        max_cost_bps=10, min_liquidity_score=.5, research_approved=True)


def model_record(model=MODEL):
    return ModelRecord(model=model, artifact_uri="builtin:last_value", artifact_sha256="a"*64,
        dataset_id="fixture:v1", experiment_id="test", license_ref="internal", commercial_use_verified=True)


class FixedBaseline(NaiveForecastProvider):
    async def forecast(self, model, req):
        result = await super().forecast(model, req)
        return result.model_copy(update={"generated_at": NOW})


def orchestrator(provider=None, approvals=None, record=None):
    providers = ProviderRegistry()
    providers.register(provider or FixedBaseline())
    instruments, horizons = MetadataRegistry(), MetadataRegistry()
    instruments.register(instrument())
    horizons.register(horizon())
    models = InMemoryModelRegistry()
    models.register(record or model_record())
    return ModelOrchestrator(providers, instruments, horizons, models,
        (approval(),) if approvals is None else approvals, {"naive": ProviderRuntime()}, now=lambda: NOW)


@pytest.mark.parametrize("asset_class", list(AssetClass))
def test_instruments_are_not_crypto_specific(asset_class):
    assert instrument(asset_class).execution_permission == "none"


def test_derivative_and_permission_validation():
    data = instrument().model_dump()
    with pytest.raises(ValidationError):
        Instrument.model_validate({**data, "asset_class": "option"})
    with pytest.raises(ValidationError):
        Instrument.model_validate({**data, "execution_permission": "live"})
    with pytest.raises(ValidationError):
        Instrument.model_validate({**data, "tick_size": "NaN"})


def test_point_in_time_and_unique_observations():
    data = request().model_dump()
    late = Observation(event_time=NOW, available_at=NOW+timedelta(seconds=1), value=1)
    with pytest.raises(ValidationError, match="Future"):
        ForecastRequest.model_validate({**data, "observations": (late,)})
    with pytest.raises(ValidationError, match="unique"):
        ForecastRequest.model_validate({**data, "observations": request().observations*2})
    with pytest.raises(ValidationError):
        Observation(event_time=NOW.replace(tzinfo=None), available_at=NOW, value=1)


def test_capabilities_are_not_invented():
    registry = ProviderRegistry()
    registry.register(NaiveForecastProvider())
    assert len(registry.discover(Capability.FORECAST)) == 1
    assert registry.discover(Capability.TRAIN) == ()
    with pytest.raises(ValueError):
        registry.require("naive", Capability.TRAIN)
    class Liar:
        def describe(self):
            return ProviderInfo(provider_id="liar", location="cloud", capabilities={Capability.TRAIN})
    with pytest.raises(TypeError):
        registry.register(Liar())


def test_gemini_preference_does_not_call_provider():
    class NeverCall:
        def analyze(self, context):
            raise AssertionError("Unexpected API call")
    registry = ProviderRegistry()
    gemini = GeminiResearchAdapter(NeverCall())
    registry.register(gemini)
    assert registry.preferred_research() is gemini
    assert Capability.TRAIN not in gemini.describe().capabilities


def test_registry_revision_immutability_and_rollback():
    registry = InMemoryModelRegistry()
    registry.register(model_record())
    second = MODEL.model_copy(update={"revision": "2"})
    registry.register(model_record(second))
    with pytest.raises(ValueError):
        registry.register(model_record())
    registry.set_research_alias("champion", MODEL)
    registry.set_research_alias("champion", second)
    assert registry.rollback_research_alias("champion") == MODEL


def test_orchestration_is_research_only():
    signal = asyncio.run(orchestrator().run(request(), liquidity_score=.8, cost_bps=1))
    assert len(signal.forecasts) == 1
    assert [p.value for p in signal.forecasts[0].points] == [100, 100]
    assert signal.execution_permission == "none"
    assert signal.combined_forecast is None
    assert signal.strategy_candidates == ("test_only",)
    assert signal.warnings


@pytest.mark.parametrize("change", [
    {"research_approved": False}, {"expires_at": NOW}, {"horizon_id": "different"},
    {"model": MODEL.model_copy(update={"revision": "2"})},
])
def test_missing_or_mismatched_approval_denies_forecasts(change):
    router = orchestrator(approvals=(approval().model_copy(update=change),))
    assert asyncio.run(router.run(request(), liquidity_score=.8, cost_bps=1)).forecasts == ()


def test_cost_liquidity_and_license_gates():
    router = orchestrator()
    assert not asyncio.run(router.run(request(), liquidity_score=.1, cost_bps=1)).forecasts
    assert not asyncio.run(router.run(request(), liquidity_score=.9, cost_bps=11)).forecasts
    router = orchestrator(record=model_record().model_copy(update={"commercial_use_verified": False}))
    assert not asyncio.run(router.run(request(), liquidity_score=.9, cost_bps=1)).forecasts


def test_stale_or_unknown_data_rejected_before_provider():
    for changed in [request().model_copy(update={"quality": "unknown"}),
        request().model_copy(update={"observations": (Observation(event_time=NOW-timedelta(days=1), available_at=NOW, value=1),)})]:
        with pytest.raises(ValueError):
            asyncio.run(orchestrator().run(changed, liquidity_score=.8, cost_bps=1))


def test_response_mismatch_isolated():
    class WrongProvider(FixedBaseline):
        async def forecast(self, model, req):
            result = await super().forecast(model, req)
            return result.model_copy(update={"unit": "EUR"})
    signal = asyncio.run(orchestrator(WrongProvider()).run(request(), liquidity_score=.8, cost_bps=1))
    assert not signal.forecasts and len(signal.rejections) == 1


def test_retry_and_cost_accounting():
    async def scenario():
        runtime = ProviderRuntime(CallPolicy(backoff_seconds=0))
        calls = 0
        async def invoke():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TransientProviderError()
            return Usage(cost_usd=".02", cost_kind="reported")
        result = await runtime.call("forecast", invoke, retry_safe=True, usage=lambda result: result)
        assert calls == 2 and result.cost_usd == Decimal(".02")
        assert runtime.known_cost_usd == Decimal(".02")
        assert runtime.unknown_cost_attempts == 1
        report = evaluate_operations(runtime.events, data_license_ref="fixture", complexity_notes="local test")
        assert report.availability == .5
    asyncio.run(scenario())


def test_permanent_error_and_unsafe_submission_not_retried():
    async def scenario():
        for error in (ValueError("invalid"), TransientProviderError()):
            runtime = ProviderRuntime()
            async def invoke():
                raise error
            with pytest.raises(type(error)):
                await runtime.call("submit", invoke)
            assert len(runtime.events) == 1
    asyncio.run(scenario())


def test_timeout_circuit_recovery_and_rate_limit():
    async def scenario():
        clock = [0.0]
        runtime = ProviderRuntime(CallPolicy(timeout_seconds=.01, failure_threshold=1, cooldown_seconds=2, requests_per_minute=2), clock=lambda: clock[0])
        async def stall():
            await asyncio.sleep(1)
        with pytest.raises(TimeoutError):
            await runtime.call("stall", stall)
        with pytest.raises(CircuitOpen):
            await runtime.call("blocked", stall)
        clock[0] = 3
        async def success():
            return 1
        assert await runtime.call("probe", success) == 1
        with pytest.raises(RateLimited):
            await runtime.call("limited", success)
        clock[0] = 64
        assert await runtime.call("reset", success) == 1
    asyncio.run(scenario())


def test_token_limit_requires_reservation():
    async def scenario():
        runtime = ProviderRuntime(CallPolicy(tokens_per_minute=100))
        async def success():
            return 1
        with pytest.raises(ValueError):
            await runtime.call("tokens", success)
        await runtime.call("tokens", success, reserved_tokens=80)
        with pytest.raises(RateLimited):
            await runtime.call("tokens", success, reserved_tokens=30)
    asyncio.run(scenario())


def dataset():
    return DatasetManifest(dataset_id="frozen", content_sha256="b"*64, source_refs=("fixture",),
        license_refs=("internal",), feature_lineage=("identity:v1",), transform_revision="1",
        train_end=NOW-timedelta(days=10), validation_start=NOW-timedelta(days=9), validation_end=NOW-timedelta(days=5),
        test_start=NOW-timedelta(days=4), test_end=NOW-timedelta(days=1))


def training_request():
    return TrainingRequest(experiment_id="exp1", idempotency_key="unique1", dataset=dataset(), method="supervised",
        code_revision="commit", environment_digest="envhash", seed=42, hyperparameters_json='{"depth": 2}',
        max_cost_usd="1", max_duration_seconds=60)


def test_dataset_splits_and_durable_experiments(tmp_path):
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate({**dataset().model_dump(), "validation_start": dataset().train_end})
    path = tmp_path / "experiments.sqlite"
    store = ExperimentStore(path)
    assert len(store.record(training_request())) == 64
    store.record_job(TrainingJob(job_id="job1", experiment_id="exp1", state="queued"))
    reopened = ExperimentStore(path)
    assert reopened.get("exp1") == training_request()
    assert reopened.history("exp1")[0].state == "queued"
    with pytest.raises(sqlite3.IntegrityError):
        store.record(training_request())


def test_training_timeout_records_unknown_without_retry(tmp_path):
    class Trainer:
        def describe(self):
            return ProviderInfo(provider_id="trainer", location="local", capabilities={Capability.TRAIN})
        async def submit_training(self, request):
            raise TransientProviderError()
        async def training_status(self, job_id):
            raise NotImplementedError
        async def cancel_training(self, job_id):
            raise NotImplementedError
    registry = ProviderRegistry()
    registry.register(Trainer())
    store = ExperimentStore(tmp_path / "training.sqlite")
    runtime = ProviderRuntime()
    coordinator = TrainingCoordinator(registry, store, {"trainer": runtime})
    with pytest.raises(TransientProviderError):
        asyncio.run(coordinator.submit("trainer", training_request()))
    assert store.history("exp1")[0].state == "unknown"
    assert len(runtime.events) == 1


def test_evaluation_math_and_no_trade_baseline():
    rows = [EvaluationRow(timestamp=NOW+timedelta(days=i), actual=10, predicted=9, naive=8,
        actual_return=.01, predicted_return=.02, proposed_position=1, transaction_cost=.002,
        probability_up=.8, regime="test", instrument_id="test", horizon_id="day") for i in range(8)]
    report = evaluate(rows, bootstrap_samples=100)
    assert report.mae == 1 and report.naive_mae == 2
    assert report.return_rmse == pytest.approx(.01)
    assert report.brier_score == pytest.approx(.04)
    assert report.expected_net_return == pytest.approx(.008)
    assert report.compounded_net_return == pytest.approx(1.008**8-1)
    assert report.no_trade_return == 0 and report.max_drawdown == 0
    assert report.paired_mae_improvement_interval == (1, 1)
    with pytest.raises(ValueError):
        evaluate(rows[::-1])


def test_calibration_is_out_of_sample_and_scope_bound():
    cal = ProbabilityCalibrator.fit(probabilities=[.8]*20, outcomes=[1]*15+[0]*5,
        calibration_id="cal1", instrument_id="test", horizon_id="day", model_revision="1", target="return", unit="fraction", fitted_through=NOW-timedelta(days=1))
    assert cal.apply(.8, as_of=NOW, instrument_id="test", horizon_id="day", model_revision="1", target="return", unit="fraction") == pytest.approx(16/22)
    with pytest.raises(ValueError):
        cal.apply(.8, as_of=NOW-timedelta(days=2), instrument_id="test", horizon_id="day", model_revision="1", target="return", unit="fraction")
    with pytest.raises(ValueError):
        cal.apply(.1, as_of=NOW, instrument_id="test", horizon_id="day", model_revision="1", target="return", unit="fraction")


def test_horizon_selection_respects_strategy_and_cost():
    router = orchestrator()
    assert router.eligible_horizons(instrument().instrument_id, strategy_family="test_only", liquidity_score=.8, cost_bps=1) == (horizon(),)
    assert router.eligible_horizons(instrument().instrument_id, strategy_family="other", liquidity_score=.8, cost_bps=1) == ()
    assert router.eligible_horizons(instrument().instrument_id, strategy_family="test_only", liquidity_score=.8, cost_bps=11) == ()


def test_session_targets_require_matching_versioned_schedule():
    selected_instrument = instrument()
    session_horizon = horizon()
    schedule = SessionSchedule(calendar_ref=selected_instrument.calendar_ref, session_targets=(
        NOW - timedelta(days=1), NOW + timedelta(days=1), NOW + timedelta(days=2), NOW + timedelta(days=3),
    ))
    assert resolve_session_targets(selected_instrument, session_horizon, schedule, as_of=NOW) == (
        NOW + timedelta(days=1), NOW + timedelta(days=2),
    )

    with pytest.raises(ValueError, match="does not match"):
        resolve_session_targets(selected_instrument, session_horizon,
            schedule.model_copy(update={"calendar_ref": "other-calendar:v1"}), as_of=NOW)
    with pytest.raises(ValueError, match="session-sampled"):
        resolve_session_targets(selected_instrument, session_horizon.model_copy(update={"sampling": "time"}), schedule, as_of=NOW)
    with pytest.raises(ValueError, match="enough future targets"):
        resolve_session_targets(selected_instrument, session_horizon,
            SessionSchedule(calendar_ref=selected_instrument.calendar_ref, session_targets=(NOW + timedelta(days=1),)),
            as_of=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_session_targets(selected_instrument, session_horizon, schedule, as_of=NOW.replace(tzinfo=None))


def test_dataset_bytes_must_match_manifest():
    import hashlib
    content = b"frozen synthetic observations"
    frozen = dataset().model_copy(update={"content_sha256": hashlib.sha256(content).hexdigest()})
    frozen.verify_content(content)
    with pytest.raises(ValueError):
        frozen.verify_content(b"changed")


def test_calibration_integrated_and_uncalibrated_output_labeled():
    class Probabilistic(FixedBaseline):
        async def forecast(self, model, req):
            result = await super().forecast(model, req)
            return result.model_copy(update={"probability_up": .8, "calibration_ref": "untrusted-provider-label"})
    router = orchestrator(Probabilistic())
    result = asyncio.run(router.run(request(), liquidity_score=.8, cost_bps=1))
    assert result.forecasts[0].calibration_ref is None
    assert any("uncalibrated" in warning for warning in result.warnings)
    cal = ProbabilityCalibrator.fit(probabilities=[.8]*20, outcomes=[1]*15+[0]*5,
        calibration_id="cal1", instrument_id=request().instrument_id, horizon_id=request().horizon_id,
        model_revision="1", target="price", unit="USD", fitted_through=NOW-timedelta(days=1))
    router.calibrators[(*MODEL.key, request().instrument_id, request().horizon_id, "price", "USD")] = cal
    result = asyncio.run(router.run(request(), liquidity_score=.8, cost_bps=1))
    assert result.forecasts[0].probability_up == pytest.approx(16/22)
    assert result.forecasts[0].calibration_ref == "cal1"


def test_future_and_stale_forecasts_are_excluded():
    for generated in (NOW+timedelta(seconds=1), NOW-timedelta(hours=2)):
        class BadTimestamp(FixedBaseline):
            async def forecast(self, model, req):
                result = await super().forecast(model, req)
                return result.model_copy(update={"generated_at": generated})
        result = asyncio.run(orchestrator(BadTimestamp()).run(request(), liquidity_score=.8, cost_bps=1))
        assert not result.forecasts


def test_provider_cannot_inject_execution_authority():
    class Unsafe(FixedBaseline):
        async def forecast(self, model, req):
            result = await super().forecast(model, req)
            return result.model_copy(update={"execution_permission": "live"})
    result = asyncio.run(orchestrator(Unsafe()).run(request(), liquidity_score=.8, cost_bps=1))
    assert not result.forecasts and result.execution_permission == "none"


def test_circuit_has_only_one_recovery_probe():
    async def scenario():
        clock = [0.0]
        runtime = ProviderRuntime(CallPolicy(failure_threshold=1, cooldown_seconds=1), clock=lambda: clock[0])
        async def fail():
            raise TransientProviderError()
        with pytest.raises(TransientProviderError):
            await runtime.call("fail", fail)
        clock[0] = 2
        entered, release = asyncio.Event(), asyncio.Event()
        async def probe():
            entered.set()
            await release.wait()
            return 1
        task = asyncio.create_task(runtime.call("probe", probe))
        await entered.wait()
        with pytest.raises(CircuitOpen):
            await runtime.call("second-probe", probe)
        release.set()
        assert await task == 1
    asyncio.run(scenario())


def test_retry_after_cannot_overrun_total_deadline():
    async def scenario():
        runtime = ProviderRuntime(CallPolicy(timeout_seconds=.01))
        async def invoke():
            raise TransientProviderError(retry_after=10)
        with pytest.raises(TimeoutError):
            await runtime.call("retry", invoke, retry_safe=True)
        assert len(runtime.events) == 1
    asyncio.run(scenario())


def test_empty_evaluation_groups_remain_visible():
    from atlas.models.evaluation import evaluate_groups
    row = EvaluationRow(timestamp=NOW, actual=1, predicted=1, naive=1, actual_return=0,
        predicted_return=0, proposed_position=0, transaction_cost=0, regime="rare",
        instrument_id="test", horizon_id="day")
    assert evaluate_groups([row], by="regime") == {"test|day|rare": None}


def test_drawdown_and_tail_loss_are_measured():
    rows = [EvaluationRow(timestamp=NOW+timedelta(days=i), actual=1, predicted=1, naive=1,
        actual_return=value, predicted_return=0, proposed_position=1, transaction_cost=0,
        regime="test", instrument_id="test", horizon_id="day") for i, value in enumerate([.1, -.2, 0, 0])]
    report = evaluate(rows, bootstrap_samples=100)
    assert report.max_drawdown == pytest.approx(.2)
    assert report.expected_shortfall_95 == pytest.approx(.2)
    assert report.brier_score is None


def test_whale_features_enforce_availability_and_quality():
    from atlas.models.schemas import FeatureValue
    feature = FeatureValue(name="exchange_inflow", source="fixture", lineage_ref="fixture:v1",
        license_ref="internal", quality="unknown", event_time=NOW-timedelta(seconds=30), available_at=NOW, value=5)
    req = request().model_copy(update={"features": (feature,)})
    with pytest.raises(ValueError, match="quality"):
        asyncio.run(orchestrator().run(req, liquidity_score=.8, cost_bps=1))
    with pytest.raises(ValidationError, match="Future"):
        ForecastRequest.model_validate({**request().model_dump(), "features": (feature.model_copy(update={"available_at": NOW+timedelta(seconds=1)}),)})


def test_model_registry_is_durable_and_rollback_keeps_audit_trail(tmp_path):
    from atlas.models.model_store import SQLiteModelRegistry
    path = tmp_path / "models.sqlite"
    registry = SQLiteModelRegistry(path)
    registry.register(model_record())
    second = MODEL.model_copy(update={"revision": "2"})
    registry.register(model_record(second))
    registry.set_research_alias("champion", MODEL)
    registry.set_research_alias("champion", second)
    reopened = SQLiteModelRegistry(path)
    assert reopened.resolve("champion") == second
    assert reopened.rollback_research_alias("champion") == MODEL
    assert [action for action, _ in reopened.alias_history("champion")] == ["set", "set", "rollback"]
    assert len(reopened.list_models()) == 2
    with pytest.raises(ValueError):
        reopened.register(model_record())
    providers = ProviderRegistry()
    providers.register(reopened)
    assert len(providers.discover(Capability.REGISTRY)) == 1


def test_result_release_rechecks_freshness_after_collection():
    router = orchestrator()
    calls = 0
    def clock():
        nonlocal calls
        calls += 1
        return NOW if calls <= 3 else NOW+timedelta(minutes=2)
    router.now = clock
    result = asyncio.run(router.run(request(), liquidity_score=.8, cost_bps=1))
    assert not result.forecasts
    assert not result.strategy_candidates
    assert any("release" in rejection.reason for rejection in result.rejections)


def test_margin_can_exceed_notional_and_option_strike_can_be_negative():
    from atlas.models.schemas import MarginRequirements
    margin = MarginRequirements(policy_ref="synthetic-short:v1", currency="USD", initial_rate="1.5", as_of=NOW)
    assert margin.initial_rate == Decimal("1.5")
    data = instrument(AssetClass.OPTION).model_dump()
    assert Instrument.model_validate({**data, "strike": "-10"}).strike == Decimal("-10")


@pytest.mark.parametrize("fails", [False, True])
def test_multiple_providers_preserve_disagreement_and_isolate_failure(fails):
    from atlas.models.schemas import ForecastPoint
    other = ModelRef(provider_id="other", model_id="alternative", revision="1")
    class Alternative:
        def describe(self):
            return ProviderInfo(provider_id="other", location="local", capabilities={Capability.FORECAST})
        async def forecast(self, model, req):
            if fails:
                raise ValueError("Invalid model output")
            base = await FixedBaseline().forecast(MODEL, req)
            return base.model_copy(update={"model": model, "points": tuple(ForecastPoint(timestamp=t, value=103) for t in req.target_times)})
    router = orchestrator(approvals=(approval(), approval(other)))
    router.providers.register(Alternative())
    router.models.register(model_record(other))
    router.runtimes["other"] = ProviderRuntime()
    result = asyncio.run(router.run(request(), liquidity_score=.8, cost_bps=1))
    assert len(result.forecasts) == (1 if fails else 2)
    assert result.disagreement_by_step == (() if fails else (3, 3))
    assert result.combined_forecast is None
    assert len(result.rejections) == (1 if fails else 0)
