from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from atlas.research.vertical_slice import (
    FEATURE_FAMILIES,
    FEATURE_NAMES,
    PAPER_STATE_KEY,
    ForecastLedger,
    SliceConfig,
    VerticalSliceScheduler,
    VerticalSliceService,
    build_feature_rows,
    build_paper_engine,
    build_research_feature_rows,
    execute_forecast_paper_trade,
    fit_softmax,
    normalize_candles,
    purged_walk_forward,
    resolve_forecast,
    serialize_paper_state,
)

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def synthetic_rows(count: int = 240, *, drift: float = 0.0004) -> list[dict]:
    rows: list[dict] = []
    price = 100.0
    for index in range(count):
        price = price * (1.0 + 0.0018 * math.sin(index / 6.0) + drift)
        open_px = price * (1.0 - 0.001)
        rows.append(
            {
                "timestamp": (START + timedelta(days=index)).isoformat(),
                "open": open_px,
                "high": max(open_px, price) * 1.004,
                "low": min(open_px, price) * 0.996,
                "close": price,
                "volume": 1_000.0 + index,
            }
        )
    return rows


def test_normalize_candles_is_point_in_time_and_reports_quality() -> None:
    rows = synthetic_rows(5)
    rows[1]["available_at"] = (START + timedelta(minutes=1)).isoformat()
    rows[2]["close"] = -1
    candles, quality = normalize_candles(rows, symbol="btc-usd", bucket_seconds=86_400)

    assert quality["rows_usable"] == 4
    assert quality["rows_rejected"] == 1
    assert quality["point_in_time"] is True
    assert all(candle.available_at >= candle.timestamp for candle in candles)
    assert candles[0].symbol == "BTC-USD"
    assert candles[0].available_at == candles[0].timestamp + timedelta(days=1)


def test_feature_rows_do_not_change_when_future_bars_are_appended() -> None:
    all_candles, _ = normalize_candles(synthetic_rows(80), symbol="BTC-USD", bucket_seconds=86_400)
    prefix, _ = normalize_candles(synthetic_rows(60), symbol="BTC-USD", bucket_seconds=86_400)
    config = SliceConfig()

    short_rows = build_feature_rows(prefix, config)
    long_rows = build_feature_rows(all_candles, config)

    assert len(short_rows) > 0
    for short, long in zip(short_rows, long_rows):
        assert short.decision_time == long.decision_time
        assert short.features == long.features
    assert all(row.target_time > row.decision_time for row in short_rows)


def test_research_features_do_not_use_future_reference_bars() -> None:
    primary, _ = normalize_candles(synthetic_rows(120), symbol="BTC-USD", bucket_seconds=86_400)
    reference_short, _ = normalize_candles(synthetic_rows(80), symbol="ETH-USD", bucket_seconds=86_400)
    reference_long, _ = normalize_candles(synthetic_rows(120), symbol="ETH-USD", bucket_seconds=86_400)
    config = SliceConfig()

    short_rows, names, available = build_research_feature_rows(
        primary,
        config,
        reference_candles=reference_short,
        include_session=True,
        include_cross_asset=True,
    )
    long_rows, _, _ = build_research_feature_rows(
        primary,
        config,
        reference_candles=reference_long,
        include_session=True,
        include_cross_asset=True,
    )

    assert available is True
    assert "ref_return_5" in names
    cutoff = reference_short[-1].available_at
    short_by_time = {
        row.decision_time: row.features
        for row in short_rows
        if row.decision_time <= cutoff
    }
    assert short_by_time
    for row in long_rows:
        if row.decision_time in short_by_time:
            assert row.features == short_by_time[row.decision_time]


def test_softmax_probabilities_are_finite_and_normalized() -> None:
    rows = build_feature_rows(
        normalize_candles(synthetic_rows(160), symbol="BTC-USD", bucket_seconds=86_400)[0],
        SliceConfig(),
    )
    resolved = [row for row in rows if row.resolved]
    model = fit_softmax([row.features for row in resolved], [int(row.label) for row in resolved], epochs=120)
    probabilities = model.predict_proba(resolved[0].features)

    assert probabilities.shape == (3,)
    assert float(probabilities.sum()) == pytest.approx(1.0)
    assert np.all(probabilities >= 0)
    assert all(math.isfinite(value) for value in probabilities)
    assert model.model_id.startswith("softmax_logistic:")
    assert sum(item["importance"] for item in model.importance()) == pytest.approx(1.0)


def test_purged_walk_forward_has_no_label_overlap() -> None:
    rows = build_feature_rows(
        normalize_candles(synthetic_rows(260), symbol="BTC-USD", bucket_seconds=86_400)[0],
        SliceConfig(),
    )
    resolved = [row for row in rows if row.resolved]
    report = purged_walk_forward(resolved, "BTC-USD", cost_bps=16.0, config=SliceConfig(epochs=100))

    assert report["status"] == "scored"
    assert report["folds"]
    assert all(fold["no_label_overlap"] for fold in report["folds"])
    assert report["model"]["rows"] == sum(fold["test_rows"] for fold in report["folds"])
    assert report["model"]["execution_permission"] == "none"


def test_xgboost_challenger_scores_on_the_same_purged_folds() -> None:
    pytest.importorskip("xgboost")
    rows = build_feature_rows(
        normalize_candles(synthetic_rows(260), symbol="BTC-USD", bucket_seconds=86_400)[0],
        SliceConfig(),
    )
    resolved = [row for row in rows if row.resolved]
    report = purged_walk_forward(resolved, "BTC-USD", cost_bps=16.0, config=SliceConfig(epochs=80))

    challenger = report["xgboost_challenger"]
    assert challenger["status"] == "scored"
    assert challenger["model"]["rows"] == report["model"]["rows"]
    assert challenger["model"]["execution_permission"] == "none"
    assert report["primary_model_family"] in {"softmax_logistic", "xgboost_multiclass"}
    assert report["selection"]["primary_model_family"] == report["primary_model_family"]


def test_ledger_persists_forecast_and_resolves_measured_outcome(tmp_path: Path) -> None:
    db = tmp_path / "slice.sqlite3"
    ledger = ForecastLedger(db)
    service = VerticalSliceService(ledger=ledger, config=SliceConfig(epochs=120, min_train_rows=20))
    rows = synthetic_rows(220)
    report = service.run(
        symbols=["BTC-USD"],
        candles_by_symbol={"BTC-USD": rows},
        fetch=False,
        now=START + timedelta(days=220),
    )
    symbol_report = report["symbols"][0]
    assert symbol_report["status"] == "forecast_recorded"
    chart = symbol_report["chart"]
    assert len(chart["bars"]) >= 20
    assert chart["markers"][0]["forecast_id"] == symbol_report["forecast"]["forecast_id"]
    assert chart["markers"][0]["action"] == symbol_report["forecast"]["action"]
    persisted_chart = service.chart("BTC-USD")
    assert persisted_chart["bars"][-1]["time"] == chart["bars"][-1]["time"]
    assert persisted_chart["execution_permission"] == "none"
    forecast = ledger.recent_forecasts(1)[0]
    assert forecast["execution_permission"] == "none"
    assert report["execution_permission"] == "none"

    next_day = START + timedelta(days=220)
    rows.append(
        {
            "timestamp": next_day.isoformat(),
            "open": rows[-1]["close"],
            "high": rows[-1]["close"] * 1.03,
            "low": rows[-1]["close"] * 0.99,
            "close": rows[-1]["close"] * 1.02,
            "volume": 5_000.0,
        }
    )
    resolved = service.resolve(
        symbols=["BTC-USD"],
        candles_by_symbol={"BTC-USD": rows},
        fetch=False,
        as_of=next_day + timedelta(days=2),
    )

    assert resolved["count"] >= 1
    stored = ledger.recent_forecasts(1)[0]
    assert stored["status"] == "resolved"
    assert stored["realized_return"] is not None
    assert stored["brier_score"] is not None
    assert service.status()["forecasts"]["resolved"] >= 1
    ledger.close()


def _forecast(
    forecast_id: str,
    *,
    action: str,
    confidence: float,
    edge: float,
    interval_low: float,
    interval_high: float,
    probabilities: list[float],
) -> dict:
    decision_time = datetime(2024, 8, 9, tzinfo=timezone.utc)
    return {
        "forecast_id": forecast_id,
        "symbol": "BTC-USD",
        "track": "competition",
        "model_id": "softmax_logistic:test:12f",
        "decision_time": decision_time.isoformat(),
        "target_time": (decision_time + timedelta(days=1)).isoformat(),
        "reference_price": 100.0,
        "features": {name: 0.0 for name in FEATURE_NAMES} | {"atr_5_pct": 0.01},
        "probabilities": probabilities,
        "action": action,
        "action_reason": "test",
        "confidence": confidence,
        "edge": edge,
        "interval_low": interval_low,
        "interval_high": interval_high,
        "expected_return": 0.01,
        "cost_bps": 16.0,
        "execution_permission": "none",
    }


def test_authorized_paper_trade_uses_control_plane_and_resolves(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "paper.sqlite3")
    config = SliceConfig()
    engine = build_paper_engine(config=config)
    forecast = _forecast(
        "fc_test_authorized",
        action="long",
        confidence=0.90,
        edge=0.88,
        interval_low=-0.02,
        interval_high=0.04,
        probabilities=[0.02, 0.08, 0.90],
    )

    trade = execute_forecast_paper_trade(forecast, engine, config)

    assert trade["control_plane_decision"] == "authorized_paper"
    assert trade["position_id"] is not None
    assert trade["authorized_notional_usd"] > 0
    assert trade["execution_permission"] == "none"

    ledger.insert_forecast(
        {
            "forecast_id": forecast["forecast_id"],
            "run_id": "run_test",
            "symbol": forecast["symbol"],
            "track": forecast["track"],
            "model_id": forecast["model_id"],
            "model_revision": "test",
            "dataset_hash": "test",
            "decision_time": forecast["decision_time"],
            "target_time": forecast["target_time"],
            "reference_price": forecast["reference_price"],
            "features_json": "{}",
            "probabilities_json": "[0.02, 0.08, 0.90]",
            "predicted_class": "up",
            "action": "long",
            "action_reason": forecast["action_reason"],
            "confidence": forecast["confidence"],
            "edge": forecast["edge"],
            "interval_low": forecast["interval_low"],
            "interval_high": forecast["interval_high"],
            "cost_bps": forecast["cost_bps"],
            "status": "open",
            "execution_permission": "none",
        }
    )
    ledger.insert_trade(trade)
    stored = ledger.recent_forecasts(1)[0]
    result = resolve_forecast(
        ledger,
        stored,
        exit_price=102.0,
        resolved_at=datetime(2024, 8, 10, tzinfo=timezone.utc),
        engine=engine,
    )

    assert result["realized_return"] == pytest.approx(0.02)
    assert result["trade"]["pnl_usd"] > 0
    assert ledger.summary()["paper_trades"]["resolved"] == 1
    ledger.close()


def test_uncertainty_gate_rejects_before_order_creation() -> None:
    config = SliceConfig()
    engine = build_paper_engine(config=config)
    forecast = _forecast(
        "fc_test_rejected",
        action="long",
        confidence=0.30,
        edge=0.05,
        interval_low=-0.25,
        interval_high=0.30,
        probabilities=[0.25, 0.45, 0.30],
    )

    trade = execute_forecast_paper_trade(forecast, engine, config)

    assert trade["control_plane_decision"] == "rejected_by_uncertainty_gate"
    assert trade["position_id"] is None
    assert engine.base_engine.open_positions == []
    assert engine.base_engine.order_history[-1].position_id is None


def test_abstain_never_creates_an_order() -> None:
    config = SliceConfig()
    engine = build_paper_engine(config=config)
    forecast = _forecast(
        "fc_test_abstain",
        action="abstain",
        confidence=0.50,
        edge=0.0,
        interval_low=-0.01,
        interval_high=0.01,
        probabilities=[0.25, 0.50, 0.25],
    )
    forecast.pop("target_time")
    forecast.pop("expected_return")

    trade = execute_forecast_paper_trade(forecast, engine, config)

    assert trade["control_plane_decision"] == "abstained"
    assert engine.base_engine.order_history == []


def _persist_forecast(ledger: ForecastLedger, forecast: dict) -> None:
    ledger.insert_forecast(
        {
            "forecast_id": forecast["forecast_id"],
            "run_id": "run_restart_test",
            "symbol": forecast["symbol"],
            "track": forecast["track"],
            "model_id": forecast["model_id"],
            "model_revision": "test",
            "dataset_hash": "test",
            "decision_time": forecast["decision_time"],
            "target_time": forecast["target_time"],
            "bucket_seconds": forecast.get("bucket_seconds"),
            "horizon_steps": forecast.get("horizon_steps"),
            "reference_price": forecast["reference_price"],
            "features_json": json.dumps(forecast["features"], sort_keys=True),
            "probabilities_json": json.dumps(forecast["probabilities"]),
            "predicted_class": "up",
            "action": forecast["action"],
            "action_reason": forecast["action_reason"],
            "confidence": forecast["confidence"],
            "edge": forecast["edge"],
            "interval_low": forecast["interval_low"],
            "interval_high": forecast["interval_high"],
            "cost_bps": forecast["cost_bps"],
            "status": "open",
            "execution_permission": "none",
        }
    )


def test_paper_state_restores_and_resumes_after_restart(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "restart.sqlite3")
    config = SliceConfig()
    engine = build_paper_engine(config=config)
    forecast = _forecast(
        "fc_restart_authorized",
        action="long",
        confidence=0.90,
        edge=0.88,
        interval_low=-0.02,
        interval_high=0.04,
        probabilities=[0.02, 0.08, 0.90],
    )
    trade = execute_forecast_paper_trade(forecast, engine, config)
    assert trade["control_plane_decision"] == "authorized_paper"
    _persist_forecast(ledger, forecast)
    ledger.insert_trade(trade)
    saved_at = datetime(2024, 8, 9, tzinfo=timezone.utc)
    ledger.save_state(
        PAPER_STATE_KEY,
        serialize_paper_state(engine, updated_at=saved_at),
        saved_at,
    )

    restored = VerticalSliceService(ledger=ledger, config=config)
    base = restored.engine.base_engine
    assert [position.position_id for position in base.open_positions] == [trade["position_id"]]
    assert base.order_history[-1].entry_price == pytest.approx(100.0)
    assert base.current_equity_usd == config.starting_equity_usd
    assert restored.status()["paper_state"]["restored"] is True

    resolution_rows = [
        {
            "timestamp": datetime(2024, 8, 9, tzinfo=timezone.utc).isoformat(),
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1_000.0,
        }
    ]
    resolved = restored.resolve(
        symbols=["BTC-USD"],
        candles_by_symbol={"BTC-USD": resolution_rows},
        fetch=False,
        as_of=datetime(2024, 8, 10, tzinfo=timezone.utc),
    )

    assert resolved["count"] == 1
    assert resolved["resolved"][0]["trade"]["pnl_usd"] > 0
    assert base.open_positions[0].status == "closed"
    assert base.current_equity_usd > config.starting_equity_usd
    assert ledger.summary()["paper_trades"]["resolved"] == 1

    after_restart = VerticalSliceService(ledger=ledger, config=config)
    assert after_restart.engine.base_engine.open_positions == []
    assert after_restart.engine.base_engine.current_equity_usd == base.current_equity_usd
    ledger.close()


def test_per_horizon_paper_books_are_isolated_and_restored(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "horizons.sqlite3")
    config = SliceConfig()
    service = VerticalSliceService(ledger=ledger, config=config)
    decision = datetime(2024, 8, 9, tzinfo=timezone.utc)
    forecast = _forecast(
        "fc_horizon_five",
        action="long",
        confidence=0.90,
        edge=0.88,
        interval_low=-0.02,
        interval_high=0.04,
        probabilities=[0.02, 0.08, 0.90],
    )
    forecast["bucket_seconds"] = 86_400
    forecast["horizon_steps"] = 5
    forecast["target_time"] = (decision + timedelta(days=5)).isoformat()
    trade = execute_forecast_paper_trade(forecast, service._engine_for(5), config)
    assert trade["control_plane_decision"] == "authorized_paper"
    _persist_forecast(ledger, forecast)
    ledger.insert_trade(trade)
    service._save_paper_state(decision)

    restored = VerticalSliceService(ledger=ledger, config=config)
    assert {1, 5}.issubset(restored._engines)
    assert [
        position.position_id
        for position in restored._engine_for(5).base_engine.open_positions
    ] == [trade["position_id"]]
    assert restored._engine_for(1).base_engine.open_positions == []
    books = restored.status()["paper_account"]["books"]
    assert {"1", "5"}.issubset(books)

    resolution_rows = [
        {
            "timestamp": datetime(2024, 8, 13, tzinfo=timezone.utc).isoformat(),
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1_000.0,
        }
    ]
    resolved = restored.resolve(
        symbols=["BTC-USD"],
        candles_by_symbol={"BTC-USD": resolution_rows},
        fetch=False,
        as_of=datetime(2024, 8, 15, tzinfo=timezone.utc),
    )

    assert resolved["count"] == 1
    assert resolved["resolved"][0]["trade"]["pnl_usd"] > 0
    assert all(
        position.status == "closed"
        for position in restored._engine_for(5).base_engine.open_positions
    )
    assert restored._engine_for(5).base_engine.current_equity_usd > config.starting_equity_usd
    assert restored._engine_for(1).base_engine.current_equity_usd == config.starting_equity_usd
    ledger.close()


def test_scheduler_runs_once_per_completed_bar_and_resumes_state(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "scheduler.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=120, min_train_rows=20),
    )
    rows = synthetic_rows(240)
    scheduler = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        bucket_seconds=86_400,
        poll_seconds=1,
        initial_delay_seconds=0,
    )
    first_now = START + timedelta(days=240)

    first = scheduler.tick(candles_by_symbol={"BTC-USD": rows}, now=first_now)
    assert first["runs"] == 1
    assert first["resolutions"] == 0
    assert first["skips"] == 0
    assert ledger.recent_forecasts(1)[0]["status"] == "open"

    second = scheduler.tick(
        candles_by_symbol={"BTC-USD": rows},
        now=first_now + timedelta(minutes=5),
    )
    assert second["runs"] == 1
    assert second["skips"] == 1

    next_timestamp = START + timedelta(days=240)
    rows.append(
        {
            "timestamp": next_timestamp.isoformat(),
            "open": rows[-1]["close"],
            "high": rows[-1]["close"] * 1.03,
            "low": rows[-1]["close"] * 0.99,
            "close": rows[-1]["close"] * 1.02,
            "volume": 5_000.0,
        }
    )
    third = scheduler.tick(
        candles_by_symbol={"BTC-USD": rows},
        now=next_timestamp + timedelta(days=1),
    )
    assert third["runs"] == 2
    assert third["resolutions"] >= 1
    assert third["execution_permission"] == "none"

    resumed = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        bucket_seconds=86_400,
        poll_seconds=1,
        initial_delay_seconds=0,
    )
    assert resumed.status()["runs"] == 2
    assert resumed.status()["resolutions"] >= 1
    assert resumed.status()["execution_permission"] == "none"
    ledger.close()


def test_scheduler_serves_multiple_horizons_with_separate_books(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "scheduler_horizons.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=80, min_train_rows=20),
    )
    rows = synthetic_rows(240)
    scheduler = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        bucket_seconds=86_400,
        horizons=(1, 5),
        poll_seconds=1,
        initial_delay_seconds=0,
    )
    first_now = START + timedelta(days=240)

    first = scheduler.tick(candles_by_symbol={"BTC-USD": rows}, now=first_now)
    assert first["runs"] == 2
    assert first["skips"] == 0
    assert {detail["horizon"] for detail in first["details"]} == {1, 5}

    second = scheduler.tick(
        candles_by_symbol={"BTC-USD": rows},
        now=first_now + timedelta(minutes=5),
    )
    assert second["runs"] == 2
    assert second["skips"] == 2

    next_timestamp = START + timedelta(days=240)
    rows.append(
        {
            "timestamp": next_timestamp.isoformat(),
            "open": rows[-1]["close"],
            "high": rows[-1]["close"] * 1.03,
            "low": rows[-1]["close"] * 0.99,
            "close": rows[-1]["close"] * 1.02,
            "volume": 5_000.0,
        }
    )
    third = scheduler.tick(
        candles_by_symbol={"BTC-USD": rows},
        now=next_timestamp + timedelta(days=1),
    )
    assert third["runs"] == 4
    assert third["resolutions"] >= 1
    assert {1, 5}.issubset(service._engines)
    assert third["horizons"] == [1, 5]

    resumed = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        bucket_seconds=86_400,
        horizons=(1, 5),
        poll_seconds=1,
        initial_delay_seconds=0,
    )
    assert resumed.status()["runs"] == 4
    assert resumed.status()["horizons"] == [1, 5]
    assert resumed.status()["execution_permission"] == "none"
    ledger.close()


def test_multi_horizon_evaluation_is_isolated_from_paper_ledger(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "evaluation.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=80, min_train_rows=30),
    )
    rows = synthetic_rows(300)

    result = service.evaluate_multi(
        symbols=["BTC-USD", "ETH-USD"],
        bucket_seconds=86_400,
        horizon_steps=[1, 5],
        now=START + timedelta(days=300),
        fetch=False,
        candles_by_symbol={"BTC-USD": rows, "ETH-USD": rows},
    )

    assert result["status"] == "evaluated"
    assert result["cells"] == 4
    assert len(result["rows"]) == 4
    assert result["scored_cells"] >= 1
    assert all(row["execution_permission"] == "none" for row in result["rows"])
    assert {row["horizon_steps"] for row in result["rows"]} == {1, 5}
    assert all("selected_model_family" in row for row in result["rows"])
    assert ledger.summary()["forecasts"]["total"] == 0
    assert ledger.summary()["paper_trades"]["authorized"] == 0
    ledger.close()


def test_feature_ablation_is_measured_and_read_only(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "ablation.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=60, min_train_rows=30),
    )
    before = ledger.summary()

    result = service.ablate_features(
        symbol="BTC-USD",
        candles=synthetic_rows(260),
        fetch=False,
        families=["momentum", "volume"],
        now=START + timedelta(days=260),
    )

    assert result["status"] == "measured"
    assert result["read_only"] is True
    assert result["symbol"] == "BTC-USD"
    assert result["execution_permission"] == "none"
    assert set(result["families"]) == set(FEATURE_FAMILIES)
    rows = {row["family"]: row for row in result["ablations"]}
    assert set(rows) == {"momentum", "volume"}
    for row in rows.values():
        assert row["status"] == "scored"
        assert row["metrics"]["execution_permission"] == "none"
        assert "delta_brier_removed" in row
        assert row["evidence"] in {"removal_worsened", "removal_improved", "inconclusive"}
    assert ledger.summary() == before
    ledger.close()


def test_research_session_and_cross_asset_features_are_measured(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "research_features.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=50, min_train_rows=30),
    )
    before = ledger.summary()

    result = service.ablate_features(
        symbol="BTC-USD",
        candles=synthetic_rows(280, drift=0.0004),
        reference_candles=synthetic_rows(280, drift=0.0002),
        fetch=False,
        families=["session", "cross_asset"],
        include_session=True,
        include_cross_asset=True,
        include_regimes=True,
        now=START + timedelta(days=280),
    )

    assert result["status"] == "measured"
    assert result["read_only"] is True
    assert result["execution_permission"] == "none"
    assert "session_sin" in result["feature_names"]
    assert "weekday_cos" in result["feature_names"]
    assert "ref_return_5" in result["feature_names"]
    assert result["research_features"]["reference_available"] is True
    rows = {row["family"]: row for row in result["ablations"]}
    assert set(rows) == {"session", "cross_asset"}
    for row in rows.values():
        assert row["status"] == "scored"
        assert row["evidence"] in {"removal_worsened", "removal_improved", "inconclusive"}
        assert row["regime_metrics"]
        assert row["execution_permission"] == "none"
    assert ledger.summary() == before
    ledger.close()


def test_feature_ablation_matrix_covers_symbols_and_horizons(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "ablation_multi.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=50, min_train_rows=30),
    )
    before = ledger.summary()
    rows = synthetic_rows(260)

    result = service.ablate_multi(
        symbols=["BTC-USD", "ETH-USD"],
        horizon_steps=[1, 5],
        families=["momentum"],
        include_regimes=True,
        candles_by_symbol={"BTC-USD": rows, "ETH-USD": rows},
        fetch=False,
        now=START + timedelta(days=260),
    )

    assert result["status"] == "evaluated"
    assert result["read_only"] is True
    assert result["include_regimes"] is True
    assert result["execution_permission"] == "none"
    assert result["symbols"] == ["BTC-USD", "ETH-USD"]
    assert result["horizons"] == [1, 5]
    assert result["cells"] == 4
    assert result["scored_cells"] >= 1
    assert len(result["rows"]) == 4
    for row in result["rows"]:
        assert row["execution_permission"] == "none"
        assert row["symbol"] in {"BTC-USD", "ETH-USD"}
        assert row["horizon_steps"] in {1, 5}
        if row["status"] == "scored":
            assert [item["family"] for item in row["ablations"]] == ["momentum"]
            assert set(row["supported_families"] + row["negative_families"] + row["inconclusive_families"]) == {"momentum"}
            regime_metrics = row["ablations"][0]["regime_metrics"]
            assert isinstance(regime_metrics, dict)
            assert regime_metrics
            assert all(
                structure["execution_permission"] == "none"
                for structure in regime_metrics.values()
            )
            assert row["baseline"]["regime_metrics"]
    assert ledger.summary() == before
    ledger.close()


def test_scheduler_process_lock_prevents_duplicate_owners(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "scheduler_lock.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=40, min_train_rows=20),
    )
    first = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        initial_delay_seconds=9999,
        poll_seconds=9999,
    )
    second = VerticalSliceScheduler(
        service,
        symbols=("BTC-USD",),
        initial_delay_seconds=9999,
        poll_seconds=9999,
    )
    try:
        started = first.start()
        assert started["running"] is True
        blocked = second.start()
        assert blocked["running"] is False
        assert second.status()["last_error"] == "scheduler_lock_held_elsewhere"
        first.stop()
        assert second.start()["running"] is True
    finally:
        first.stop()
        second.stop()
        ledger.close()


def test_manual_scheduler_tick_releases_the_process_lock(tmp_path: Path) -> None:
    ledger = ForecastLedger(tmp_path / "scheduler_tick_lock.sqlite3")
    service = VerticalSliceService(
        ledger=ledger,
        config=SliceConfig(epochs=40, min_train_rows=20),
    )
    first = VerticalSliceScheduler(service, symbols=("BTC-USD",), poll_seconds=9999)
    second = VerticalSliceScheduler(service, symbols=("BTC-USD",), poll_seconds=9999)
    try:
        first.tick(
            candles_by_symbol={"BTC-USD": synthetic_rows(240)},
            now=START + timedelta(days=240),
        )
        assert first._process_lock_handle is None
        assert second.start()["running"] is True
    finally:
        first.stop()
        second.stop()
        ledger.close()


def test_vertical_slice_status_exposes_scheduler_contract() -> None:
    from fastapi.testclient import TestClient

    from atlas.api.app import app

    with TestClient(app) as client:
        response = client.get("/api/research/vertical-slice/status")
        assert response.status_code == 200
        body = response.json()
        assert body["execution_permission"] == "none"
        assert body["scheduler"]["execution_permission"] == "none"
        assert "running" in body["scheduler"]
        assert "last_check_at" in body["scheduler"]
        assert body["paper_account"]["execution_permission"] == "none"
        assert body["paper_account"]["status"] in {"available", "unavailable"}
        experimental = client.get("/api/research/experimental-status").json()
        assert experimental["audited_path"] == "/api/research/vertical-slice"
        assert experimental["execution_permission"] == "none"
        assert experimental["state"] == "retired"
        retired = client.get("/api/advanced-ml/status")
        assert retired.status_code == 503
        assert retired.json()["detail"]["state"] == "retired"
        assert (
            retired.json()["detail"]["audited_path"]
            == "/api/research/vertical-slice"
        )
