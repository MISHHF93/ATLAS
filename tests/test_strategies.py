"""Tests for the ATLAS Multi-Strategy Trading Engine, Autonomous Bot Orchestrator, and Connectors."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from atlas.connectors import (
    AlpacaEquitiesConnector,
    CCXTPerpConnector,
    DXtradePropConnector,
    UnifiedOrderPlacementRequest,
)
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.models.bot_orchestrator import BotOrchestrator
from atlas.models.schemas import Observation
from atlas.strategies import (
    ActorCriticPolicyStrategy,
    BasisArbitrageStrategy,
    CandleBar,
    MicrostructureMetrics,
    OpeningAuctionDriveStrategy,
    OrderBookDepthSnapshot,
    VpinAbsorptionStrategy,
    dispatch_signal_to_control_plane,
    evaluate_signal_against_rulebook,
)


def _sample_candles(symbol: str = "BTC-USD", base_price: float = 68400.0) -> list[CandleBar]:
    t0 = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
    return [
        CandleBar(
            symbol=symbol,
            timestamp=t0 + timedelta(minutes=5 * i),
            open=base_price + i * 2.0,
            high=base_price + i * 2.0 + 15.0,
            low=base_price + i * 2.0 - 15.0,
            close=base_price + i * 2.0 + 5.0,
            volume=1200.0 + i * 50.0,
        )
        for i in range(6)
    ]


def _sample_depth(symbol: str = "BTC-USD", poc_price: float = 68410.0) -> OrderBookDepthSnapshot:
    return OrderBookDepthSnapshot(
        symbol=symbol,
        timestamp=datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc),
        best_bid=poc_price - 2.5,
        best_ask=poc_price + 2.5,
        poc_price=poc_price,
        val_price=poc_price * 0.992,
        vah_price=poc_price * 1.012,
        bid_depth_top5=2400.0,
        ask_depth_top5=1500.0,
        spread_bps=1.2,
    )


def _sample_observations(count: int = 32) -> tuple[Observation, ...]:
    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    obs: list[Observation] = []
    price = 100.0
    for i in range(count):
        step_change = 0.45 if i % 3 != 0 else -0.20
        price = round(price + step_change, 4)
        ts = t0 + timedelta(days=i)
        obs.append(
            Observation(
                event_time=ts,
                available_at=ts,
                value=price,
            )
        )
    return tuple(obs)


def test_all_strategies_enforce_air_gap_execution_permission_none() -> None:
    candles_btc = _sample_candles("BTC-USD", 68400.0)
    depth_btc = _sample_depth("BTC-USD", 68410.0)

    # 1. STRAT_VPIN_ABSORB: VPIN > 0.35 and OFI > 2.0 sigma with consolidating price -> passive BUY at POC
    vpin_bot = VpinAbsorptionStrategy()
    sig_vpin = vpin_bot.generate_signal(
        candles_btc,
        depth_btc,
        MicrostructureMetrics(
            vpin=0.42,
            ofi_zscore=2.65,
            price_consolidation_score=0.78,
            atr_bps=95.0,
        ),
    )
    assert sig_vpin.strategy_id == "STRAT_VPIN_ABSORB"
    assert sig_vpin.direction == "BUY"
    assert sig_vpin.execution_tactic == "LIMIT"
    assert sig_vpin.reference_price == 68410.0
    assert sig_vpin.target_conviction > 0.50
    assert sig_vpin.execution_permission == "none"

    # 2. STRAT_BASIS_ARB: 8h funding divergence > 3.0 sigma -> dual-leg delta-neutral arbitrage
    arb_bot = BasisArbitrageStrategy()
    sig_arb_short = arb_bot.generate_signal(
        candles_btc,
        depth_btc,
        MicrostructureMetrics(
            spot_price=68300.0,
            perp_price=68480.0,
            funding_rate_8h=0.00085,
            funding_zscore=3.6,
            atr_bps=110.0,
        ),
    )
    assert sig_arb_short.strategy_id == "STRAT_BASIS_ARB"
    assert sig_arb_short.direction == "SELL"
    assert sig_arb_short.secondary_leg_direction == "BUY"
    assert sig_arb_short.secondary_leg_symbol == "BTC-USD-SPOT"
    assert sig_arb_short.execution_permission == "none"

    sig_arb_long = arb_bot.generate_signal(
        candles_btc,
        depth_btc,
        MicrostructureMetrics(
            spot_price=68450.0,
            perp_price=68250.0,
            funding_rate_8h=-0.00090,
            funding_zscore=-3.4,
            atr_bps=110.0,
        ),
    )
    assert sig_arb_long.direction == "BUY"
    assert sig_arb_long.secondary_leg_direction == "SELL"
    assert sig_arb_long.execution_permission == "none"

    # 3. STRAT_AUCTION_DRIVE: 09:25–09:30 ET opening auction imbalance on SPY/QQQ/NVDA with 10:15 ET exit
    auction_bot = OpeningAuctionDriveStrategy()
    candles_spy = _sample_candles("SPY", 584.0)
    depth_spy = _sample_depth("SPY", 584.20)
    sig_auction = auction_bot.generate_signal(
        candles_spy,
        depth_spy,
        MicrostructureMetrics(
            auction_imbalance_shares=85_000.0,
            auction_imbalance_zscore=2.45,
            auction_timestamp_et="09:28 ET",
            atr_bps=80.0,
        ),
    )
    assert sig_auction.strategy_id == "STRAT_AUCTION_DRIVE"
    assert sig_auction.symbol == "SPY"
    assert sig_auction.direction == "BUY"
    assert sig_auction.time_decay_exit_et == "10:15 ET"
    assert sig_auction.execution_permission == "none"

    # Past 10:15 ET -> HOLD
    sig_auction_expired = auction_bot.generate_signal(
        candles_spy,
        depth_spy,
        MicrostructureMetrics(
            auction_imbalance_shares=85_000.0,
            auction_imbalance_zscore=2.45,
            auction_timestamp_et="10:16 ET",
            atr_bps=80.0,
        ),
    )
    assert sig_auction_expired.direction == "HOLD"
    assert sig_auction_expired.execution_permission == "none"

    # 4. STRAT_RL_POLICY: Actor-Critic policy continuous state evaluation
    rl_bot = ActorCriticPolicyStrategy()
    sig_rl = rl_bot.generate_signal(
        candles_btc,
        depth_btc,
        MicrostructureMetrics(
            vpin=0.22,
            ofi_zscore=2.4,
            inventory_fraction=-0.15,
            state_vector=(1.5, 0.25, 0.12, -0.15, 0.85, 0.15),
            atr_bps=100.0,
        ),
    )
    assert sig_rl.strategy_id == "STRAT_RL_POLICY"
    assert sig_rl.direction == "BUY"
    assert 0.0 < sig_rl.target_conviction <= 1.0
    assert sig_rl.execution_permission == "none"


def test_control_plane_deterministically_enforces_prop_challenge_rules_on_strategy_signals() -> None:
    candles_btc = _sample_candles("BTC-USD", 68400.0)
    depth_btc = _sample_depth("BTC-USD", 68410.0)
    vpin_bot = VpinAbsorptionStrategy()
    signal = vpin_bot.generate_signal(
        candles_btc,
        depth_btc,
        MicrostructureMetrics(vpin=0.40, ofi_zscore=2.5, price_consolidation_score=0.80, atr_bps=100.0),
    )
    assert signal.execution_permission == "none"

    # Case A: Compliant order passes ActionableControlPlaneEngine
    engine_ok = ActionableControlPlaneEngine()
    decision_ok = dispatch_signal_to_control_plane(
        signal,
        engine_ok,
        target_track="competition",
        desired_notional_usd=Decimal("20000"),
        override_stop_distance_bps=Decimal("150"),
    )
    assert decision_ok.control_plane_decision == "authorized_and_executed"
    assert len(decision_ok.violations) == 0

    # Case B: Violating 0.75% per-trade risk cap (e.g., $45,000 notional * 250 bps stop = $1,125 > $763.87)
    engine_risk = ActionableControlPlaneEngine()
    decision_risk = dispatch_signal_to_control_plane(
        signal,
        engine_risk,
        target_track="competition",
        desired_notional_usd=Decimal("45000"),
        override_stop_distance_bps=Decimal("250"),
    )
    assert decision_risk.control_plane_decision == "rejected_by_control_plane"
    assert any("per_trade_risk_exceeded" in v for v in decision_risk.violations)

    # Case C: Violating 4.0% Daily Loss Circuit Breaker
    engine_daily = ActionableControlPlaneEngine()
    engine_daily.start_of_day_equity_usd = Decimal("104000")
    engine_daily.current_equity_usd = Decimal("99500")  # > 4.0% daily loss
    decision_daily = dispatch_signal_to_control_plane(
        signal,
        engine_daily,
        target_track="competition",
        desired_notional_usd=Decimal("15000"),
        override_stop_distance_bps=Decimal("100"),
    )
    assert decision_daily.control_plane_decision == "rejected_by_control_plane"
    assert any("daily_loss_circuit_breaker" in v for v in decision_daily.violations)

    # Case D: Violating 8.0% Max Trailing Drawdown Floor
    engine_dd = ActionableControlPlaneEngine()
    engine_dd.high_water_mark_usd = Decimal("108000")
    engine_dd.start_of_day_equity_usd = Decimal("100000")
    engine_dd.current_equity_usd = Decimal("99000")  # 8.33% trailing drawdown from HWM
    decision_dd = dispatch_signal_to_control_plane(
        signal,
        engine_dd,
        target_track="competition",
        desired_notional_usd=Decimal("15000"),
        override_stop_distance_bps=Decimal("100"),
    )
    assert decision_dd.control_plane_decision == "rejected_by_control_plane"
    assert any("max_drawdown_breached:trailing" in v for v in decision_dd.violations)

    # Case E: Violating <= 35% Single-Day Profit Consistency Gate
    engine_cons = ActionableControlPlaneEngine()
    engine_cons.best_day_profit_usd = Decimal("1800")
    engine_cons.total_cumulative_profit_usd = Decimal("3000")  # 60% > 35% consistency cap
    decision_cons = dispatch_signal_to_control_plane(
        signal,
        engine_cons,
        target_track="competition",
        desired_notional_usd=Decimal("15000"),
        override_stop_distance_bps=Decimal("100"),
    )
    assert decision_cons.control_plane_decision == "rejected_by_control_plane"
    assert any("competition_consistency_rule_breached" in v for v in decision_cons.violations)

    # Case F: Missing mandatory ATR / structural stop-loss bracket
    engine_stop = ActionableControlPlaneEngine()
    snap = engine_stop.get_state().account
    eval_no_stop = evaluate_signal_against_rulebook(
        signal.model_copy(update={"suggested_stop_loss": 0.0}),
        engine_stop.comp_rulebook,
        snap,
        desired_notional_usd=Decimal("15000"),
        stop_kind="none",
        override_stop_distance_bps=Decimal("0"),
    )
    assert eval_no_stop.compliance_passed is False
    assert any("stop_loss_missing" in v for v in eval_no_stop.violations)


def test_bot_orchestrator_purged_walk_forward_causality_and_promotion_gates() -> None:
    obs = _sample_observations(36)
    control_engine = ActionableControlPlaneEngine()
    orchestrator = BotOrchestrator(control_engine=control_engine)

    # 1. Verify EXP-001 5-day embargo purged walk-forward causality (zero future leakage)
    splits = orchestrator.build_exp001_purged_walk_forward_splits(obs, num_folds=3, embargo_days=5)
    assert len(splits) >= 2
    for fold in splits:
        assert fold.embargo_days == 5
        assert fold.causal_split_verified is True
        assert fold.train_end < fold.test_start
        assert max(fold.train_sample_indices) < min(fold.test_sample_indices)
        assert fold.execution_permission == "none"

    # 2. Degraded bot triggers EXP-001 re-training and promotes challenger when OOS MaxDD < 3.2% and Sharpe > 1.8
    telemetry, report_promoted = orchestrator.monitor_and_retrain_if_degraded(
        "STRAT_VPIN_ABSORB",
        live_sharpe=0.75,   # below 1.10 threshold
        live_sortino=0.95,  # below 1.40 threshold
        live_brier=0.26,    # above 0.22 threshold
        observations=obs,
        challenger_oos_returns=[0.0032, 0.0038, -0.0008, 0.0042, 0.0035, 0.0031, -0.0006, 0.0039, 0.0034, 0.0030],
    )
    assert telemetry.degraded is True
    assert report_promoted is not None
    assert report_promoted.experiment_id == "EXP-001"
    assert report_promoted.embargo_days == 5
    assert report_promoted.causal_walk_forward_verified is True
    assert report_promoted.oos_max_drawdown_fraction < 0.032
    assert report_promoted.oos_sharpe_ratio > 1.80
    assert report_promoted.promoted is True
    assert report_promoted.active_model_version == "vpin_absorb_gbdt:v2"
    assert report_promoted.execution_permission == "none"

    # 3. Challenger with excessive OOS drawdown (> 3.2%) or low Sharpe is NOT promoted
    report_rejected = orchestrator.run_retraining_and_evaluate_promotion(
        "STRAT_BASIS_ARB",
        observations=obs,
        challenger_oos_returns=[-0.020, -0.018, 0.005, -0.015, 0.002, -0.010],
    )
    assert report_rejected.promoted is False
    assert report_rejected.active_model_version == "basis_arb_kalman:v1"
    assert report_rejected.execution_permission == "none"


def test_unified_execution_connectors_and_control_plane_routing() -> None:
    alpaca = AlpacaEquitiesConnector()
    ccxt_perp = CCXTPerpConnector()
    dxtrade = DXtradePropConnector()

    assert alpaca.normalize_symbol("SPY/USD") == "SPY"
    assert ccxt_perp.normalize_symbol("BTC/USDT:USDT") == "BTC-USD"
    assert ccxt_perp.to_venue_symbol("BTC-USD") == "BTC/USDT:USDT"
    assert dxtrade.normalize_symbol("DX:BTCUSD.PROP") == "BTC-USD"
    assert dxtrade.to_venue_symbol("BTC-USD") == "DX:BTCUSD.PROP"

    engine = ActionableControlPlaneEngine()
    req_ok = UnifiedOrderPlacementRequest(
        client_order_id="cli-001",
        canonical_symbol="BTC-USD",
        venue_symbol="BTC/USDT:USDT",
        track="competition",
        side="BUY",
        order_type="ALMGREN_CHRISS",
        notional_usd=Decimal("20000"),
        limit_price=68410.0,
        stop_loss_bps=Decimal("120"),
        take_profit_bps=Decimal("240"),
        strategy_id="STRAT_VPIN_ABSORB",
    )
    cb_ok = ccxt_perp.place_order_via_control_plane(req_ok, engine)
    assert cb_ok.status == "FILLED"
    assert cb_ok.execution_permission == "none"
    assert len(ccxt_perp.get_position_blotter()) == 1

    # Order exceeding per-trade risk cap is rejected by control plane before hitting venue
    req_bad = UnifiedOrderPlacementRequest(
        client_order_id="cli-002",
        canonical_symbol="BTC-USD",
        venue_symbol="DX:BTCUSD.PROP",
        track="competition",
        side="BUY",
        order_type="MARKET",
        notional_usd=Decimal("48000"),
        stop_loss_bps=Decimal("300"),
        take_profit_bps=Decimal("500"),
        strategy_id="STRAT_RL_POLICY",
    )
    cb_bad = dxtrade.place_order_via_control_plane(req_bad, engine)
    assert cb_bad.status == "REJECTED_BY_CONTROL_PLANE"
    assert len(dxtrade.get_position_blotter()) == 0


def test_realtime_market_data_ingestion_and_live_ai_model_prediction() -> None:
    from fastapi.testclient import TestClient
    from atlas.api.app import app

    client = TestClient(app)

    # 1. Crypto live ingestion & AI prediction (BTC-USD)
    res_btc = client.get("/api/market/live-ai-prediction?symbol=BTC-USD&allow_network=false")
    assert res_btc.status_code == 200
    data_btc = res_btc.json()
    assert data_btc["symbol"] == "BTC-USD"
    assert data_btc["execution_permission"] == "none"
    assert data_btc["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert 0.50 <= float(data_btc["calibrated_probability"]) <= 1.0
    assert len(data_btc["horizon_forecasts"]) == 3
    for h in data_btc["horizon_forecasts"]:
        assert h["p10_price"] < h["p50_price"] < h["p90_price"]
    assert len(data_btc["strategy_signals"]) == 4
    for sig in data_btc["strategy_signals"]:
        assert sig["execution_permission"] == "none"
    assert int(data_btc["live_microstructure"]["ring_buffer_size"]) >= 6

    # 2. Equity live ingestion & AI prediction (SPY) via POST /api/research/live-predict
    res_spy = client.post(
        "/api/research/live-predict",
        json={"symbol": "SPY", "granularity": 900, "allow_network": False},
    )
    assert res_spy.status_code == 200
    data_spy = res_spy.json()
    assert data_spy["symbol"] == "SPY"
    assert data_spy["execution_permission"] == "none"
    assert len(data_spy["candles"]) >= 12
    assert len(data_spy["trading_factors"]) == 12
    assert data_spy["locked_whale_opportunity"]["opportunity_locked"] is True
    assert data_spy["locked_whale_opportunity"]["action"] in ("BUY", "SELL")
    assert data_spy["locked_whale_opportunity"]["scenario_id"] in (
        "WSDM-01",
        "WSDM-02",
        "WSDM-03",
        "WSDM-04",
        "WSDM-05",
    )
    assert data_spy["locked_whale_opportunity"]["execution_permission"] == "none"


def test_12_factor_whale_opportunity_ml_locks_buy_and_sell_opportunities() -> None:
    from atlas.models.whale_factor_ml import WhaleOpportunityFactorModel

    model = WhaleOpportunityFactorModel()

    # 1. Bullish Whale Accumulation candles -> locks onto BUY opportunity (WSDM-01)
    bull_candles = [
        {"open": 68100 + i * 35, "high": 68160 + i * 35, "low": 68070 + i * 35, "close": 68135 + i * 35, "volume": 150 + i * 25}
        for i in range(10)
    ]
    rep_buy = model.evaluate_live_opportunity(
        "BTC-USD",
        bull_candles,
        vpin_override=0.38,
        ofi_override=0.28,
    )
    assert rep_buy.execution_permission == "none"
    assert len(rep_buy.factors) == 12
    assert rep_buy.direction == "LONG"
    assert rep_buy.locked_opportunity.action == "BUY"
    assert rep_buy.locked_opportunity.scenario_id == "WSDM-01"
    assert rep_buy.locked_opportunity.stop_loss_price < rep_buy.locked_opportunity.entry_price < rep_buy.locked_opportunity.take_profit_price
    assert rep_buy.locked_opportunity.execution_permission == "none"

    # 2. Bearish Whale Distribution candles -> locks onto SELL opportunity (WSDM-02)
    bear_candles = [
        {"open": 68400 - i * 40, "high": 68430 - i * 40, "low": 68330 - i * 40, "close": 68355 - i * 40, "volume": 160 + i * 30}
        for i in range(10)
    ]
    rep_sell = model.evaluate_live_opportunity(
        "BTC-USD",
        bear_candles,
        vpin_override=0.41,
        ofi_override=-0.32,
    )
    assert rep_sell.execution_permission == "none"
    assert len(rep_sell.factors) == 12
    assert rep_sell.direction == "SHORT"
    assert rep_sell.locked_opportunity.action == "SELL"
    assert rep_sell.locked_opportunity.scenario_id == "WSDM-02"
    assert rep_sell.locked_opportunity.take_profit_price < rep_sell.locked_opportunity.entry_price < rep_sell.locked_opportunity.stop_loss_price
    assert rep_sell.locked_opportunity.execution_permission == "none"


