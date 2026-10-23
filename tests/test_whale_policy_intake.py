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

    # 5. Unified Extractor (strict causal inputs: observed Top-5 depth + tick event times)
    candles = [
        {"open": 68000.0 + i * 50, "high": 68120.0 + i * 50, "low": 67950.0 + i * 50, "close": 68080.0 + i * 50, "volume": 1200.0 + i * 80}
        for i in range(16)
    ]
    depth_books = [
        BookLevelSnapshot(level=k, bid_price=68080.0 - 40.0 * k, bid_size=120.0 * k, ask_price=68080.0 + 40.0 * k, ask_size=95.0 * k)
        for k in range(1, 6)
    ]
    event_times = [1.2, 2.8, 4.1, 5.0, 5.6, 5.9, 6.05]
    snap = MicrostructureWhaleFeatureExtractor().extract_from_candles_and_depth(
        "BTC-USD",
        candles,
        prev_book=depth_books,
        curr_book=depth_books,
        event_times_sec=event_times,
        eval_time_sec=6.5,
    )
    assert snap.execution_permission == "none"
    assert snap.symbol == "BTC-USD"
    assert snap.atr_14 > 0

    closed_only = MicrostructureWhaleFeatureExtractor().extract_from_candles("BTC-USD", candles)
    assert closed_only.execution_permission == "none"
    assert closed_only.data_origin == "candles_only"
    assert closed_only.atr_14 > 0
    assert closed_only.ofi_data_status == "not_observed"

    with pytest.raises(ValueError):
        MicrostructureWhaleFeatureExtractor().extract_from_candles_and_depth(
            "BTC-USD", candles, prev_book=depth_books, curr_book=depth_books, event_times_sec=[]
        )


def test_task2_whale_policy_trainer_and_predict():
    """Verify Triple-Barrier labeling (+1.5 ATR, -1.0 ATR, 60m), composite loss, EXP-001 walk-forward, and WhalePolicyModel.predict()."""
    trainer = WhalePolicyTrainer()
    obs = trainer.load_warehouse_observations(symbol="BTC-USD", num_bars=32)
    targets = trainer.generate_triple_barrier_targets(obs, upper_atr_mult=1.5, lower_atr_mult=1.0, vertical_minutes=60)
    assert len(targets) == 30
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


def test_chart_reader_scores_stream_for_both_tracks():
    """The model reads ring-buffer bars for an open-market name and still scores the competition book."""
    from datetime import datetime, timedelta, timezone

    from atlas.marketdata.live_stream import LiveMarketDataGateway
    from atlas.models.chart_reader import read_market_charts

    gateway = LiveMarketDataGateway(demo_mode=True)
    now = datetime.now(timezone.utc)
    for idx in range(8):
        stamp = now - timedelta(seconds=8 - idx)
        gateway.ingest_tick(
            symbol="NVDA",
            price=142.0 + idx * 0.15,
            size=20.0 + idx,
            side="buy" if idx % 2 == 0 else "sell",
            exchange_timestamp=stamp,
            system_receipt_timestamp=stamp + timedelta(milliseconds=5),
        )
    report = read_market_charts(gateway, WhalePolicyModel(), symbol="NVDA", bucket_seconds=900)
    assert report["execution_permission"] == "none"
    active = report["active"]
    assert active["symbol"] == "NVDA"
    assert active["track"] == "open_market"
    assert active["chart_source"] == "stream_ring_buffer"
    assert active["bars_read"] >= 4
    assert active["signal"]["execution_permission"] == "none"
    assert len(active["horizons"]) == 3
    assert [row["symbol"] for row in report["competition"]] == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert "SPY" in [row["symbol"] for row in report["open_market"]]
    assert all(row["execution_permission"] == "none" for row in report["competition"])
    assert all(row["track"] == "competition" for row in report["competition"])
    assert all(row["track"] == "open_market" for row in report["open_market"])
    moment = active["whale_moment"]
    assert moment["status"] == "locked"
    assert moment["action"] in ("BUY", "SELL")
    assert moment["scenario_id"] in ("WSDM-01", "WSDM-02", "WSDM-03", "WSDM-04", "WSDM-05")
    assert moment["execution_permission"] == "none"
    assert moment["inputs"] == "candle_close_versus_open"
    lock = active["bar_lock"]
    assert lock["execution_permission"] == "none"
    assert lock["may_propose_order"] is False
    assert lock["stance"] == "abstain"
    assert lock["action"] in ("BUY", "SELL")
    assert lock["method"] == "causal_swing"
    assert lock["decision_timestamp"] == active["candles"][-1]["timestamp"]
    assert lock["window_timestamps"][-1] == lock["decision_timestamp"]
    assert 1 <= len(lock["window_timestamps"]) <= 24
    stamps = [row["timestamp"] for row in active["candles"]]
    assert all(stamp in stamps for stamp in lock["window_timestamps"])
    assert stamps.index(lock["window_timestamps"][0]) <= stamps.index(lock["decision_timestamp"])
    if lock["action"] == "BUY":
        assert lock["invalidation_price"] < active["candles"][-1]["close"]
        assert lock["objective_price"] > active["candles"][-1]["close"]
    if lock["action"] == "SELL":
        assert lock["invalidation_price"] > active["candles"][-1]["close"]
        assert lock["objective_price"] < active["candles"][-1]["close"]
    assert "order_id" not in lock
    assert "conviction" not in moment
    assert "calibrated_probability" not in moment
    assert moment["recommendation"]["stance"] == "abstain"
    assert moment["recommendation"]["may_propose_order"] is False
    assert moment["recommendation"]["execution_permission"] == "none"
    assert "almgren_chriss_slices" not in moment
    others = [row for row in report["competition"] + report["open_market"] if row["symbol"] != "NVDA"]
    assert others
    assert all("whale_moment" not in row for row in others)


def test_chart_read_abstains_until_evidence_and_a_paper_session_both_exist():
    """A lined-up label is still not an order. Missing evidence abstains first."""
    from atlas.models.chart_reader import decide_trade_stance

    lined_up = {
        "status": "locked",
        "action": "BUY",
        "inputs": "observed_book",
        "execution_permission": "none",
    }
    clean = decide_trade_stance(
        whale_moment=lined_up,
        direction="BUY",
        feed_origin="coinbase_exchange_public",
        ofi_observed=True,
        hawkes_observed=True,
        bars_read=48,
        paper_armed=False,
    )
    assert clean["stance"] == "abstain"
    assert clean["reasons"] == ["paper_session_not_armed"]
    assert clean["may_propose_order"] is False
    assert clean["execution_permission"] == "none"

    review = decide_trade_stance(
        whale_moment=lined_up,
        direction="BUY",
        feed_origin="coinbase_exchange_public",
        ofi_observed=True,
        hawkes_observed=True,
        bars_read=48,
        paper_armed=True,
    )
    assert review["stance"] == "paper_review"
    assert review["may_propose_order"] is False
    assert review["execution_permission"] == "none"

    weak = decide_trade_stance(
        whale_moment={"status": "locked", "action": "SELL", "inputs": "candle_close_versus_open"},
        direction="BUY",
        feed_origin="labeled_synthetic_fixture",
        ofi_observed=False,
        hawkes_observed=False,
        bars_read=12,
    )
    assert weak["stance"] == "abstain"
    assert weak["may_propose_order"] is False
    assert "side_reconstructed_from_candle_bodies" in weak["reasons"]
    assert "policy_direction_disagrees" in weak["reasons"]
    assert "tape_is_not_a_public_print" in weak["reasons"]
    assert "hawkes_unobserved" in weak["reasons"]
    assert "Must not trade." in weak["summary"]


def test_causal_lock_stops_at_the_opposing_bar_and_prices_that_swing():
    """The shaded run ends at the first earlier bar that closes the other way. The line is beyond that swing."""
    from atlas.models.chart_reader import causal_bar_lock

    bars = []
    price = 100.0
    for index, move in enumerate((1, 1, 1, 1, -1, 1, 1, 1)):
        open_px = price
        close_px = price + move
        bars.append(
            {
                "timestamp": f"2026-10-22T12:00:{index:02d}+00:00",
                "open": open_px,
                "high": max(open_px, close_px) + 0.2,
                "low": min(open_px, close_px) - 0.2,
                "close": close_px,
                "volume": 10,
            }
        )
        price = close_px
    buy = causal_bar_lock(bars, action="BUY")
    assert buy["method"] == "causal_swing"
    assert buy["window_timestamps"] == [bar["timestamp"] for bar in bars[-3:]]
    assert buy["invalidation_price"] < min(bar["low"] for bar in bars[-3:])
    assert buy["objective_price"] > bars[-1]["close"]
    assert buy["may_propose_order"] is False
    assert buy["execution_permission"] == "none"
    sell = causal_bar_lock(bars, action="SELL")
    assert sell["window_timestamps"] == [bars[-1]["timestamp"]]
    assert sell["invalidation_price"] > bars[-1]["high"]
    assert sell["objective_price"] < bars[-1]["close"]


def test_whale_moment_names_documented_buy_and_sell_and_withholds_a_short_tape():
    """Rising candles name a buy. Falling candles name a sell. A short tape stays withheld."""
    from atlas.models.chart_reader import whale_moment_from_candles

    bull = [
        {"open": 68100 + i * 35, "high": 68160 + i * 35, "low": 68070 + i * 35, "close": 68135 + i * 35, "volume": 150 + i * 25}
        for i in range(10)
    ]
    bear = [
        {"open": 68400 - i * 40, "high": 68430 - i * 40, "low": 68330 - i * 40, "close": 68355 - i * 40, "volume": 160 + i * 30}
        for i in range(10)
    ]
    buy = whale_moment_from_candles("BTC-USD", bull)
    sell = whale_moment_from_candles("BTC-USD", bear)
    assert buy["status"] == "locked"
    assert buy["action"] == "BUY"
    assert buy["scenario_id"] == "WSDM-01"
    assert sell["status"] == "locked"
    assert sell["action"] == "SELL"
    assert sell["scenario_id"] == "WSDM-02"
    assert buy["execution_permission"] == "none"
    assert sell["execution_permission"] == "none"
    assert "conviction" not in buy and "calibrated_probability" not in sell
    assert "live book" in buy["trigger_summary"]
    assert "liquidation print" in sell["trigger_summary"]
    short = whale_moment_from_candles("BTC-USD", bull[:3])
    assert short == {"status": "withheld", "reason": "fewer_than_four_bars", "execution_permission": "none"}


def test_chart_read_endpoint_covers_competition_and_open_market():
    from fastapi.testclient import TestClient
    from atlas.api.app import app

    client = TestClient(app)
    response = client.get("/api/ml/chart-read?symbol=BTC-USD&bucket_seconds=60")
    assert response.status_code == 200
    body = response.json()
    assert body["execution_permission"] == "none"
    assert body["active"]["symbol"] == "BTC-USD"
    assert body["active"]["track"] == "competition"
    assert body["active"]["signal"]["execution_permission"] == "none"
    moment = body["active"]["whale_moment"]
    assert moment["status"] == "locked"
    assert moment["action"] in ("BUY", "SELL")
    assert moment["scenario_id"] in ("WSDM-01", "WSDM-02", "WSDM-03", "WSDM-04", "WSDM-05")
    assert moment["execution_permission"] == "none"
    assert "conviction" not in moment
    assert moment["recommendation"]["may_propose_order"] is False
    assert moment["recommendation"]["stance"] == "abstain"
    assert moment["recommendation"]["execution_permission"] == "none"
    assert {row["symbol"] for row in body["competition"]} == {"BTC-USD", "ETH-USD", "SOL-USD"}
    assert {row["symbol"] for row in body["open_market"]} >= {"SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA"}
    link = body["training"]
    assert link["chart_linked"] is True
    assert link["cadence_seconds"] == 900
    assert link["orders_submitted"] == 0
    assert link["execution_permission"] == "none"
    assert set(link["tracks"]) == {"competition", "open_market"}
    lock = body["active"]["bar_lock"]
    assert lock["execution_permission"] == "none"
    assert lock["may_propose_order"] is False
    assert lock["stance"] == "abstain"
    assert lock["method"] == "causal_swing"
    assert lock["decision_timestamp"] == body["active"]["candles"][-1]["timestamp"]
    assert lock["window_timestamps"][-1] == lock["decision_timestamp"]
    assert lock["window_timestamps"][0] in {row["timestamp"] for row in body["active"]["candles"]}
    close = body["active"]["candles"][-1]["close"]
    if lock["action"] == "BUY":
        assert lock["invalidation_price"] < close
        assert lock["objective_price"] > close
    if lock["action"] == "SELL":
        assert lock["invalidation_price"] > close
        assert lock["objective_price"] < close
    assert "order_id" not in lock
    assert isinstance(link["autonomous"], bool)
    assert isinstance(link["notice"], str)
    assert "served_model" not in link
    assert "submit_order" not in response.text


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


def test_audit_deduplication_and_control_gateway():
    """Verify zero AI imports in src/atlas/control/, canonical microstructure delegation,
    and ControlPlaneExecutionGateway routing across competition and open_market tracks.
    """
    from pathlib import Path
    from atlas.control.gateway import ControlPlaneExecutionGateway
    from atlas.whale_saas_az import (
        compute_almgren_chriss_schedule,
        compute_hawkes_intensity,
        compute_kyles_lambda,
    )

    # 1. Verify zero LLM/AI imports inside src/atlas/control/
    for fname in ("engine.py", "rules.py", "gateway.py"):
        src_text = Path(f"src/atlas/control/{fname}").read_text(encoding="utf-8")
        assert "from atlas.ai" not in src_text
        assert "import atlas.ai" not in src_text

    # 2. Verify deduplicated microstructure & Almgren-Chriss delegation
    kyle_res = compute_kyles_lambda([1.2, 2.4, -0.8, 3.1], [100.0, 180.0, -60.0, 220.0])
    assert kyle_res["execution_permission"] == "none"
    assert kyle_res["lambda_coeff"] > 0

    ac_res = compute_almgren_chriss_schedule(total_shares=5000.0, horizon_steps=5, kappa=0.45)
    assert ac_res["execution_permission"] == "none"
    assert len(ac_res["child_order_slices"]) == 5

    hawkes_res = compute_hawkes_intensity([0.1, 0.2, 0.4, 0.8])
    assert hawkes_res["execution_permission"] == "none"
    assert hawkes_res["current_intensity_lambda"] > 0.50

    # 3. Verify ControlPlaneExecutionGateway across competition & open_market tracks
    gw = ControlPlaneExecutionGateway()
    gw.control_engine.flatten_all_positions(reason="gateway_test_clean")

    model = WhalePolicyModel()
    btc_sig = model.predict(
        symbol="BTC-USD",
        spot_price=68450.0,
        atr_14=1025.0,
        vpin=0.38,
        ofi_z=2.4,
        hawkes_ratio=0.92,
    )
    btc_rep = gw.evaluate_and_dispatch_signal(btc_sig, track="competition", data_age_ms=8.0)
    assert btc_rep.decision.control_plane_decision == "authorized_and_executed"
    assert btc_rep.connector_receipt is not None
    assert "ccxt_perp" in btc_rep.connector_receipt["connector_id"]

    spy_sig = model.predict(
        symbol="SPY",
        spot_price=584.20,
        atr_14=6.50,
        vpin=0.36,
        ofi_z=2.2,
        hawkes_ratio=0.90,
    )
    spy_rep = gw.evaluate_and_dispatch_signal(spy_sig, track="open_market", data_age_ms=12.0)
    assert spy_rep.decision.control_plane_decision == "authorized_and_executed"
    assert spy_rep.connector_receipt is not None
    assert spy_rep.connector_receipt["connector_id"] == "alpaca_equities_dma"


def test_visual_automation_scan_endpoint() -> None:
    from fastapi.testclient import TestClient
    from atlas.api.app import app

    client = TestClient(app)
    res_get = client.get("/api/automation/visual-scan?symbol=NVDA")
    assert res_get.status_code == 503
    data_get = res_get.json()["detail"]
    assert data_get["status"] == "retired"
    assert data_get["execution_permission"] == "none"
    assert data_get["replacement"] == "/api/research/vertical-slice"

    res_post = client.post(
        "/api/automation/visual-scan",
        json={"symbol": "BTC-USD", "trigger_dispatch": True},
    )
    assert res_post.status_code == 503
    data_post = res_post.json()["detail"]
    assert data_post == data_get
    assert "automation_coverage_pct" not in res_post.text

    res_qm = client.get("/api/measurements/institutional?symbol=BTC-USD")
    assert res_qm.status_code == 200
    data_qm = res_qm.json()
    assert data_qm["status"] == "ok"
    assert data_qm["execution_permission"] == "none"
    assert len(data_qm["measurements"]) == 8
    assert 0.25 <= data_qm["hurst_exponent"] <= 0.85
    assert data_qm["latency_percentiles_ms"] is None
    carry = next(row for row in data_qm["measurements"] if row["id"] == "QM-07")
    latency = next(row for row in data_qm["measurements"] if row["id"] == "QM-08")
    assert carry["status"] == "unobserved"
    assert latency["status"] == "unobserved"
    assert "APR" not in carry["value"]

    docs = client.get("/api/docs")
    assert docs.status_code == 200
    paths = {row["path"] for row in docs.json()["documents"]}
    assert "docs/architecture/EXECUTION_PLAN.md" in paths
    assert "docs/roadmap/range_garden.md" in paths
    assert "docs/roadmap/reserve_yield.md" in paths
    assert "docs/roadmap/tab7_whale_signal_decision_matrix.csv" in paths
    assert docs.json()["execution_permission"] == "none"




