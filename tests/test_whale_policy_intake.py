"""Tests for ATLAS Autonomous Whale Model Training (`src/atlas/models/whale_policy.py`),
Microstructure Feature Extractor (`src/atlas/features/microstructure.py`), and
Deterministic Control Plane Signal Intake & Bracket Order Bridge (`src/atlas/control/engine.py`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.control.engine import ActionableControlPlaneEngine
from atlas.features.microstructure import (
    BookLevelSnapshot,
    MicrostructureWhaleFeatureExtractor,
    compute_exponential_multilevel_ofi,
    compute_hawkes_child_order_intensity,
    compute_rolling_kyles_lambda,
    compute_rolling_vpin,
)
from atlas.models.whale_policy import WhalePolicyModel, WhalePolicyTrainer
from atlas.strategies.base import StrategySignal
from atlas.strategies.connectors import CcxtPerpConnector


def test_task1_microstructure_whale_feature_extractor():
    """Verify VPIN volume bucketing, exponential Top-5 OFI, rolling Kyle's Lambda, and Hawkes intensity."""
    # 1. Rolling VPIN with V = ADV / N (N=50)
    price_deltas = [12.0, 15.0, -4.0, 18.0, 22.0, 14.0, -3.0, 19.0, 25.0, 16.0]
    trade_vols = [120.0, 140.0, 90.0, 160.0, 180.0, 150.0, 80.0, 170.0, 200.0, 150.0]
    vpin_rep = compute_rolling_vpin(price_deltas, trade_vols, adv=10000.0, buckets_per_day_n=50, window_m=10)
    assert vpin_rep.execution_permission == "none"
    assert vpin_rep.bucket_volume_v == pytest.approx(200.0)
    assert 0.0 <= vpin_rep.vpin <= 1.0
    assert vpin_rep.num_buckets_n >= 1

    # 2. Exponential Multi-Level OFI across Top 5 L2 levels
    prev_book = [
        BookLevelSnapshot(level=k, bid_price=100.0 - 0.1 * k, bid_size=50.0 * k, ask_price=100.0 + 0.1 * k, ask_size=50.0 * k)
        for k in range(1, 6)
    ]
    curr_book = [
        BookLevelSnapshot(level=k, bid_price=100.0 - 0.1 * k, bid_size=85.0 * k, ask_price=100.0 + 0.1 * k, ask_size=30.0 * k)
        for k in range(1, 6)
    ]
    ofi_rep = compute_exponential_multilevel_ofi(prev_book, curr_book, alpha=0.45)
    assert ofi_rep.execution_permission == "none"
    assert len(ofi_rep.level_contributions) == 5
    assert ofi_rep.ofi_raw > 0
    assert ofi_rep.dominant_pressure == "buy"

    # 3. Rolling Kyle's Lambda
    signed_flows = [120.0, 140.0, -90.0, 160.0, 180.0, 150.0, -80.0, 170.0, 200.0, 150.0]
    kyle_rep = compute_rolling_kyles_lambda(price_deltas, signed_flows, window=8)
    assert kyle_rep.execution_permission == "none"
    assert kyle_rep.sample_count == 8
    assert kyle_rep.lambda_impact > 0

    # 4. Hawkes Process Child-Order Intensity (branching ratio alpha/beta -> 0.92)
    hawkes_rep = compute_hawkes_child_order_intensity(
        [1.0, 2.2, 3.1, 3.6, 3.85, 3.95],
        eval_time_sec=4.0,
        mu_0=0.50,
        alpha=0.92,
        beta=1.00,
    )
    assert hawkes_rep.execution_permission == "none"
    assert hawkes_rep.branching_ratio == pytest.approx(0.92)
    assert hawkes_rep.iceberg_clustering_detected is True

    # 5. Unified Extractor
    candles = [
        {"open": 68000.0 + i * 50, "high": 68120.0 + i * 50, "low": 67950.0 + i * 50, "close": 68080.0 + i * 50, "volume": 1200.0 + i * 80}
        for i in range(16)
    ]
    snap = MicrostructureWhaleFeatureExtractor().extract_from_candles_and_depth("BTC-USD", candles)
    assert snap.execution_permission == "none"
    assert snap.symbol == "BTC-USD"
    assert snap.atr_14 > 0


def test_task2_whale_policy_trainer_and_predict():
    """Verify Triple-Barrier labeling (+1.5 ATR, -1.0 ATR, 60m), composite loss, EXP-001 walk-forward, and WhalePolicyModel.predict()."""
    trainer = WhalePolicyTrainer()
    obs = trainer.load_warehouse_observations(symbol="BTC-USD", num_bars=32)
    targets = trainer.generate_triple_barrier_targets(obs, upper_atr_mult=1.5, lower_atr_mult=1.0, vertical_minutes=60)
    assert len(targets) == 31
    for t in targets:
        assert t.execution_permission == "none"
        assert t.upper_take_profit_price > t.entry_price > t.lower_stop_loss_price
        assert (t.expiration_time - t.entry_time).total_seconds() == 3600.0

    model, report = trainer.train_and_evaluate(symbol="BTC-USD", observations=obs)
    assert report.execution_permission == "none"
    assert report.embargo_days == 5
    assert report.causal_walk_forward_verified is True
    assert report.oos_sharpe_ratio > 1.80
    assert report.oos_max_drawdown_fraction < 0.032
    assert report.oos_brier_score < 0.180
    assert report.promoted is True
    assert report.loss_report.total_composite_loss > 0

    sig = model.predict(
        symbol="BTC-USD",
        spot_price=68450.0,
        atr_14=550.0,
        vpin=0.38,
        ofi_z=2.4,
        hawkes_ratio=0.92,
    )
    assert isinstance(sig, StrategySignal)
    assert sig.execution_permission == "none"
    assert sig.symbol == "BTC-USD"
    assert sig.direction == "BUY"
    assert 0.55 <= sig.conviction <= 0.96
    assert sig.target_entry_price == pytest.approx(68450.0)
    assert sig.suggested_stop_loss == pytest.approx(67900.0)
    assert sig.suggested_take_profit == pytest.approx(69275.0)
    assert sig.execution_tactic in ("ALMGREN_CHRISS", "LIMIT_POC", "IOC")
    assert sig.telemetry["vpin"] == pytest.approx(0.38)
    assert sig.telemetry["ofi_z"] == pytest.approx(2.4)
    assert sig.telemetry["hawkes_ratio"] == pytest.approx(0.92)


def test_control_plane_whale_signal_intake_and_prop_rejections():
    """Verify ActionableControlPlaneEngine.ingest_whale_policy_signal sizes within 0.50%-0.75% risk,
    attaches ATR brackets, routes to connector, and deterministically rejects all 5 prop violations.
    """
    engine = ActionableControlPlaneEngine()
    engine.flatten_all_positions(reason="test_clean_slate")
    connector = CcxtPerpConnector()

    model = WhalePolicyModel()
    signal = model.predict(
        symbol="BTC-USD",
        spot_price=68450.0,
        atr_14=1025.0,
        vpin=0.38,
        ofi_z=2.4,
        hawkes_ratio=0.92,
    )

    # 1. Valid signal intake -> sized within 0.50%-0.75% equity risk, approved & routed to connector
    intake = engine.ingest_whale_policy_signal(
        signal,
        track="competition",
        risk_fraction_target=Decimal("0.0060"),
        data_age_ms=12.5,
        execution_connector=connector,
    )
    assert intake.execution_permission == "none"
    assert intake.decision.control_plane_decision == "authorized_and_executed"
    assert 0.0050 <= intake.risk_fraction_of_equity <= 0.0075
    assert intake.connector_receipt is not None
    assert intake.connector_receipt["status"] == "FILLED"
    assert "ccxt_perp" in intake.connector_receipt["connector_id"]

    # 2. Reject when market data staleness > 500ms on competition track
    stale_intake = engine.ingest_whale_policy_signal(
        signal,
        track="competition",
        data_age_ms=640.0,
    )
    assert stale_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("data_stale_competition_500ms" in v for v in stale_intake.decision.violations)

    # 3. Reject when per-trade risk exceeds 0.75% of account balance
    oversized_intake = engine.ingest_whale_policy_signal(
        signal,
        track="competition",
        desired_notional_usd=Decimal("150000"),
        data_age_ms=10.0,
    )
    assert oversized_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("per_trade_risk_exceeded" in v for v in oversized_intake.decision.violations)

    # 4. Reject when single-day profit consistency gate (> 35%) is violated
    engine_cons = ActionableControlPlaneEngine()
    engine_cons.flatten_all_positions(reason="reset")
    engine_cons.best_day_profit_usd = Decimal("1500")
    engine_cons.total_cumulative_profit_usd = Decimal("3000")  # 50% > 35%
    cons_intake = engine_cons.ingest_whale_policy_signal(signal, track="competition", data_age_ms=10.0)
    assert cons_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("competition_consistency_rule_breached" in v for v in cons_intake.decision.violations)

    # 5. Reject when 4.0% daily loss circuit breaker is breached
    engine_daily = ActionableControlPlaneEngine()
    engine_daily.flatten_all_positions(reason="reset")
    engine_daily.start_of_day_equity_usd = Decimal("100000")
    engine_daily.current_equity_usd = Decimal("95800")  # -4.2% daily loss
    daily_intake = engine_daily.ingest_whale_policy_signal(signal, track="competition", data_age_ms=10.0)
    assert daily_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("daily_loss_circuit_breaker" in v for v in daily_intake.decision.violations)

    # 6. Reject when 8.0% max trailing drawdown floor is breached
    engine_dd = ActionableControlPlaneEngine()
    engine_dd.flatten_all_positions(reason="reset")
    engine_dd.high_water_mark_usd = Decimal("110000")
    engine_dd.start_of_day_equity_usd = Decimal("102000")
    engine_dd.current_equity_usd = Decimal("100500")  # > 8.6% below HWM
    dd_intake = engine_dd.ingest_whale_policy_signal(signal, track="competition", data_age_ms=10.0)
    assert dd_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("max_drawdown_breached" in v for v in dd_intake.decision.violations)


def test_whale_policy_api_endpoints():
    """Verify /api/ml/whale-policy/train, /api/ml/whale-policy/predict, and /api/control/ingest-whale-signal."""
    from fastapi.testclient import TestClient
    from atlas.api.app import app

    client = TestClient(app)

    res_train = client.post("/api/ml/whale-policy/train", json={"symbol": "BTC-USD"})
    assert res_train.status_code == 200
    train_data = res_train.json()
    assert train_data["execution_permission"] == "none"
    assert train_data["evaluation_report"]["promoted"] is True
    assert train_data["latest_signal"]["execution_permission"] == "none"

    res_pred = client.get("/api/ml/whale-policy/predict?symbol=BTC-USD")
    assert res_pred.status_code == 200
    pred_data = res_pred.json()
    assert pred_data["execution_permission"] == "none"
    assert pred_data["signal"]["execution_permission"] == "none"

    res_ingest = client.post("/api/control/ingest-whale-signal", json={"symbol": "BTC-USD", "data_age_ms": 8.4})
    assert res_ingest.status_code == 200
    ingest_data = res_ingest.json()
    assert ingest_data["execution_permission"] == "none"
    assert ingest_data["intake_report"]["execution_permission"] == "none"

