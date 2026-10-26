"""Comprehensive tests for ATLAS Pump Intelligence — Solana Token Discovery, Risk, ML, and Paper Execution."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.pump import (
    MINT_ALPHA_CURVE,
    MINT_ALPHA_RUG,
    MINT_GRAD_SWAP,
    MINT_MIGRATING,
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    STRATEGY_NAMES,
    TOKEN_2022_PROGRAM_ID,
    USDC_MINT,
    WSOL_MINT,
    BondingCurveState,
    DedicatedTradingWalletGuard,
    HistoricalTokenSample,
    IndexedChainEvent,
    LookaheadBiasError,
    MigrationTracker,
    PumpDeterministicRiskEngine,
    PumpExecutionAdapter,
    PumpIntelligenceEngine,
    PumpMonitoringService,
    PumpPortfolioBook,
    PumpRiskLimits,
    PumpSwapPoolState,
    PumpTokenDiscoveryService,
    ReplayFrame,
    SolanaRPCIndexer,
    TokenLifecycleState,
    WalletSecurityError,
    WalletTradeSample,
    analyze_wallet_intelligence,
    assert_mint_identifier,
    build_pump_feature_snapshot,
    decode_bonding_curve_account,
    decode_pumpswap_pool_account,
    detect_strategy_candidates,
    encode_bonding_curve_account,
    encode_pumpswap_pool_account,
    estimate_solana_tx_fee,
    evaluate_liquidity_and_impact,
    evaluate_models_vs_baselines,
    evaluate_token_safety,
    predict_pump_outcomes,
    quote_curve_buy_exact_quote_in,
    quote_curve_sell,
    quote_multi_hop,
    quote_pumpswap,
    rank_candidates_by_ev,
    run_event_driven_replay,
    transition_lifecycle,
)
from atlas.pump.tokens import LAMPORTS_PER_SOL


# ---------------------------------------------------------------------------
# 1. Token Discovery & Mint-Address Identity (Never Symbol Alone)
# ---------------------------------------------------------------------------


def test_token_discovery_mint_identity_and_symbol_collision():
    svc = PumpTokenDiscoveryService()
    with pytest.raises(ValueError, match="never by symbol alone"):
        assert_mint_identifier("ALPHA")
    with pytest.raises(ValueError, match="never by symbol alone"):
        svc.get_by_mint("ALPHA")

    # Discover two distinct mints that share the exact same ticker symbol "ALPHA"
    t1 = svc.discover_launch(
        mint=MINT_ALPHA_CURVE,
        symbol="ALPHA",
        name="Organic Alpha",
        creation_tx="5Sig1111111111111111111111111111111111111111",
        creation_slot=100,
        creation_timestamp=1_700_000_000.0,
        creator_wallet="CreatorWaLLeTGood11111111111111111111111111",
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
    )
    t2 = svc.discover_launch(
        mint=MINT_ALPHA_RUG,
        symbol="ALPHA",
        name="Copycat Alpha",
        creation_tx="5Sig2222222222222222222222222222222222222222",
        creation_slot=105,
        creation_timestamp=1_700_000_030.0,
        creator_wallet="CreatorWaLLeTRug444444444444444444444444444",
        bonding_curve_address="BondingCurveRug4444444444444444444444444444",
    )
    assert t1.mint != t2.mint
    assert svc.get_by_mint(MINT_ALPHA_CURVE).name == "Organic Alpha"
    assert svc.get_by_mint(MINT_ALPHA_RUG).name == "Copycat Alpha"
    collisions = svc.find_symbol_collisions("ALPHA")
    assert len(collisions) == 2

    # Unrecognized/deep custom create_v2 quote-mint (depth > MAX_QUOTE_DEPTH) is marked UNSUPPORTED
    t_deep = svc.discover_launch(
        mint="PumpMintDeepQuote55555555555555555555555555",
        symbol="DEEPQ",
        name="Deep Quote Chain",
        creation_tx="5SigDeep55555555555555555555555555555555555",
        creation_slot=110,
        creation_timestamp=1_700_000_060.0,
        creator_wallet="CreatorWaLLeTGood11111111111111111111111111",
        bonding_curve_address="BondingCurveDeep555555555555555555555555555",
        quote_mint="CustomQuoteMint5555555555555555555555555555",
    )
    assert t_deep.lifecycle_state == TokenLifecycleState.UNSUPPORTED


# ---------------------------------------------------------------------------
# 2 & 3. Bonding-Curve & PumpSwap Binary / JSON Decoding
# ---------------------------------------------------------------------------


def test_bonding_curve_binary_and_json_roundtrip():
    raw = encode_bonding_curve_account(
        virtual_token_reserves=800_000_000_000_000,
        virtual_quote_reserves=45 * LAMPORTS_PER_SOL,
        real_token_reserves=520_000_000_000_000,
        real_quote_reserves=15 * LAMPORTS_PER_SOL,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        unswept_protocol_fees=int(0.2 * LAMPORTS_PER_SOL),
        unswept_creator_fees=int(0.05 * LAMPORTS_PER_SOL),
    )
    state = decode_bonding_curve_account(
        raw,
        mint=MINT_ALPHA_CURVE,
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
        creator="CreatorWaLLeTGood11111111111111111111111111",
        slot=300_001,
    )
    assert state.virtual_token_reserves == 800_000_000_000_000
    assert state.real_quote_reserves == 15 * LAMPORTS_PER_SOL
    assert state.unswept_protocol_fees == int(0.2 * LAMPORTS_PER_SOL)
    assert state.complete is False

    # Also verify dict/JSON decoding
    from_dict = decode_bonding_curve_account(
        state.as_dict(),
        mint=MINT_ALPHA_CURVE,
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
    )
    assert from_dict.virtual_token_reserves == state.virtual_token_reserves


def test_pumpswap_binary_and_json_roundtrip_with_negative_virtual_reserves():
    raw = encode_pumpswap_pool_account(
        base_vault_amount=206_900_000 * (10**6),
        quote_vault_amount=90 * LAMPORTS_PER_SOL,
        virtual_quote_reserves=-2 * LAMPORTS_PER_SOL,  # Negative signed offset
        protocol_fee_bps=5,
        lp_fee_bps=20,
        coin_creator_fee_bps=5,
        lp_burned=True,
    )
    pool = decode_pumpswap_pool_account(
        raw,
        pool_address="PumpSwapPooLGrad222222222222222222222222222",
        base_mint=MINT_GRAD_SWAP,
        quote_mint=WSOL_MINT,
    )
    assert pool.virtual_quote_reserves == -2 * LAMPORTS_PER_SOL
    assert pool.effective_quote_reserves == 88 * LAMPORTS_PER_SOL
    assert pool.lp_burned is True


# ---------------------------------------------------------------------------
# 4, 5, 6. Quote Calculation, Fee Calculation, and Signed Virtual Reserves
# ---------------------------------------------------------------------------


def test_quotes_fees_and_signed_virtual_reserves():
    # Bonding curve with unswept fees reducing effective virtual quote reserves
    curve_clean = BondingCurveState(
        mint=MINT_ALPHA_CURVE,
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
        virtual_token_reserves=700_000_000 * (10**6),
        virtual_quote_reserves=50 * LAMPORTS_PER_SOL,
        real_token_reserves=450_000_000 * (10**6),
        real_quote_reserves=20 * LAMPORTS_PER_SOL,
        unswept_protocol_fees=0,
        unswept_creator_fees=0,
    )
    curve_unswept = BondingCurveState(
        mint=MINT_ALPHA_CURVE,
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
        virtual_token_reserves=700_000_000 * (10**6),
        virtual_quote_reserves=50 * LAMPORTS_PER_SOL,
        real_token_reserves=450_000_000 * (10**6),
        real_quote_reserves=20 * LAMPORTS_PER_SOL,
        unswept_protocol_fees=int(2.0 * LAMPORTS_PER_SOL),
        unswept_creator_fees=int(0.5 * LAMPORTS_PER_SOL),
        signed_virtual_quote_adjustment=-int(0.5 * LAMPORTS_PER_SOL),
    )
    assert curve_unswept.effective_virtual_quote_reserves < curve_clean.effective_virtual_quote_reserves
    assert curve_unswept.signed_virtual_quote_reserves_offset == -int(3.0 * LAMPORTS_PER_SOL)

    buy_q = quote_curve_buy_exact_quote_in(curve_unswept, LAMPORTS_PER_SOL)
    assert buy_q.protocol_fee_raw > 0
    assert buy_q.creator_fee_raw > 0
    assert buy_q.total_fee_raw == buy_q.protocol_fee_raw + buy_q.creator_fee_raw
    assert buy_q.tokens_out_raw > 0

    sell_q = quote_curve_sell(curve_unswept, buy_q.tokens_out_raw)
    assert sell_q.quote_out_raw < LAMPORTS_PER_SOL  # Round-trip fees + spread

    # PumpSwap pool with negative virtual_quote_reserves
    pool = PumpSwapPoolState(
        pool_address="PumpSwapPooLGrad222222222222222222222222222",
        base_mint=MINT_GRAD_SWAP,
        quote_mint=WSOL_MINT,
        base_vault_amount=206_900_000 * (10**6),
        quote_vault_amount=92 * LAMPORTS_PER_SOL,
        virtual_quote_reserves=-2 * LAMPORTS_PER_SOL,
    )
    ps_buy = quote_pumpswap(pool, side="buy", amount_in_raw=LAMPORTS_PER_SOL)
    assert ps_buy.protocol_fee_raw + ps_buy.lp_fee_raw + ps_buy.creator_fee_raw == ps_buy.total_fee_raw
    assert ps_buy.amount_out_raw > 0

    # Multi-hop route (TOKEN -> USDC -> WSOL)
    pool_hop1 = PumpSwapPoolState(
        pool_address="PumpSwapPooLHop1111111111111111111111111111",
        base_mint=MINT_GRAD_SWAP,
        quote_mint=USDC_MINT,
        base_vault_amount=200_000_000 * (10**6),
        quote_vault_amount=50_000 * (10**6),
        quote_decimals=6,
    )
    pool_hop2 = PumpSwapPoolState(
        pool_address="PumpSwapPooLHop2222222222222222222222222222",
        base_mint=USDC_MINT,
        quote_mint=WSOL_MINT,
        base_vault_amount=50_000 * (10**6),
        quote_vault_amount=300 * LAMPORTS_PER_SOL,
        base_decimals=6,
        quote_decimals=9,
    )
    mh = quote_multi_hop([("pumpswap", pool_hop1, "sell"), ("pumpswap", pool_hop2, "sell")], initial_amount_in_raw=1_000_000 * (10**6))
    assert len(mh.hops) == 2
    assert mh.final_amount_out_raw > 0

    # Solana transaction fee formula: base_fee = 5000 * signatures, priority = ceil(CU * micro_lamports / 1e6)
    fee_est = estimate_solana_tx_fee(signatures=2, compute_unit_limit=200_000, micro_lamports_per_cu=25_000)
    assert fee_est.base_fee_lamports == 10_000
    assert fee_est.priority_fee_lamports == 5_000
    assert fee_est.total_fee_lamports == 15_000


# ---------------------------------------------------------------------------
# 7. Migration Detection & Synthetic Migration Crossover
# ---------------------------------------------------------------------------


def test_migration_tracker_and_synthetic_crossover():
    # Final curve buy exceeding real_token_reserves crosses over into synthetic migration
    nearly_complete_curve = BondingCurveState(
        mint=MINT_MIGRATING,
        bonding_curve_address="BondingCurveMig3333333333333333333333333333",
        virtual_token_reserves=280_500_000 * (10**6),
        virtual_quote_reserves=114 * LAMPORTS_PER_SOL,
        real_token_reserves=500_000 * (10**6),  # Only 500k tokens left on curve
        real_quote_reserves=84 * LAMPORTS_PER_SOL,
        slot=110,
        event_time=1_700_000_010.0,
    )
    crossover_quote = quote_curve_buy_exact_quote_in(nearly_complete_curve, 5 * LAMPORTS_PER_SOL)
    assert crossover_quote.crosses_graduation is True
    assert crossover_quote.synthetic_migration_tokens_raw > 0
    assert crossover_quote.curve_tokens_filled_raw == nearly_complete_curve.real_token_reserves
    assert "CompleteEvent" in crossover_quote.emitted_events
    assert "PostCompleteBuyEvent" in crossover_quote.emitted_events

    # Causal lifecycle state machine transitions
    svc = PumpTokenDiscoveryService()
    tok = svc.discover_launch(
        mint=MINT_MIGRATING,
        symbol="MIGR8",
        name="Migrating Token",
        creation_tx="5SigMigCreate3333333333333333333333333333333",
        creation_slot=100,
        creation_timestamp=1_700_000_000.0,
        creator_wallet="CreatorWaLLeTMig333333333333333333333333333",
        bonding_curve_address="BondingCurveMig3333333333333333333333333333",
    )
    assert tok.lifecycle_state == TokenLifecycleState.DISCOVERED
    tracker = MigrationTracker()

    # Curve active
    tracker.on_curve_update(tok, nearly_complete_curve, tx_signature="5SigCurveActive")
    assert tok.lifecycle_state == TokenLifecycleState.CURVE_ACTIVE

    # Curve completes -> MIGRATION_PENDING
    completed_curve = BondingCurveState(
        mint=MINT_MIGRATING,
        bonding_curve_address="BondingCurveMig3333333333333333333333333333",
        virtual_token_reserves=279_900_000 * (10**6),
        virtual_quote_reserves=115 * LAMPORTS_PER_SOL,
        real_token_reserves=0,
        real_quote_reserves=85 * LAMPORTS_PER_SOL,
        complete=True,
        slot=120,
        event_time=1_700_000_050.0,
    )
    ev_complete = tracker.on_curve_update(tok, completed_curve, tx_signature="5SigCurveDone")
    assert ev_complete is not None
    assert tok.lifecycle_state == TokenLifecycleState.MIGRATION_PENDING

    # Pool active -> PUMPSWAP_ACTIVE
    pool = PumpSwapPoolState(
        pool_address="PumpSwapPooLMig3333333333333333333333333333",
        base_mint=MINT_MIGRATING,
        quote_mint=WSOL_MINT,
        base_vault_amount=206_900_000 * (10**6),
        quote_vault_amount=85 * LAMPORTS_PER_SOL,
        slot=125,
        event_time=1_700_000_060.0,
    )
    ev_pool = tracker.on_pumpswap_pool_active(tok, pool, tx_signature="5SigPooLLive")
    assert ev_pool.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE
    assert tok.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE

    # Invalid backwards transition is rejected
    with pytest.raises(ValueError, match="Illegal lifecycle transition"):
        transition_lifecycle(tok, TokenLifecycleState.CURVE_ACTIVE, slot=130, event_time=1_700_000_070.0, reason="backwards")


# ---------------------------------------------------------------------------
# 8. Token-Risk Screening (Verified Facts vs Heuristic Risk Scores)
# ---------------------------------------------------------------------------


def test_token_safety_distinguishes_facts_from_heuristics_and_rejects_rug():
    engine = PumpIntelligenceEngine()
    alpha_bundle = engine.evaluate_token_pipeline(MINT_ALPHA_CURVE)
    rug_bundle = engine.evaluate_token_pipeline(MINT_ALPHA_RUG)

    assert alpha_bundle["token_safety"]["safety_status"] == "passed"
    assert alpha_bundle["token_safety"]["safe_guaranteed"] is False
    assert "verified_on_chain_facts" in alpha_bundle["token_safety"]
    assert "heuristic_risk_scores" in alpha_bundle["token_safety"]
    assert alpha_bundle["wallet_intelligence"]["heuristic_indicators"]["cluster_coordination_proven"] is False

    assert rug_bundle["token_safety"]["safety_status"] == "rejected"
    reasons = rug_bundle["token_safety"]["hard_reject_reasons"]
    assert "mint_authority_active" in reasons
    assert "freeze_authority_active" in reasons
    assert any("restricted_token_extensions" in r for r in reasons)
    assert any("creator_concentration" in r for r in reasons)


# ---------------------------------------------------------------------------
# 9, 10, 11. Strategy Causality, ML Point-in-Time Guard, Calibration & EV Ranking
# ---------------------------------------------------------------------------


def test_strategies_ml_point_in_time_guard_and_ev_ranking():
    engine = PumpIntelligenceEngine()
    token = engine.discovery.get_by_mint(MINT_ALPHA_CURVE)
    curve = engine.discovery.curve_for(MINT_ALPHA_CURVE)
    liq = evaluate_liquidity_and_impact(token, order_size_sol=0.5, curve=curve)
    wallet = analyze_wallet_intelligence(
        mint=MINT_ALPHA_CURVE,
        creator_wallet=token.creator_wallet,
        holders=engine._holders[MINT_ALPHA_CURVE],
        trades=engine._trades[MINT_ALPHA_CURVE],
    )
    safety = evaluate_token_safety(token, liquidity_profile=liq, wallet_report=wallet)

    # Future trade timestamp must trigger LookaheadBiasError
    future_trade = WalletTradeSample(
        signature="sig_future",
        slot=999_999_999,
        event_time=engine.clock() + 3600.0,
        wallet="FutureTrader1111111111111111111111111111111",
        side="buy",
        quote_amount_sol=1.0,
        token_amount=1_000_000.0,
        price_quote=curve.price_quote_per_token,
    )
    with pytest.raises(LookaheadBiasError, match="event_time .* > as_of_ts"):
        build_pump_feature_snapshot(
            token,
            as_of_ts=engine.clock(),
            trades=[future_trade],
            liquidity_profile=liq,
            safety_report=safety,
            wallet_report=wallet,
            curve=curve,
        )

    # Valid causal feature snapshot + all 8 strategies + 9-target ML forecast + EV ranking
    snap = build_pump_feature_snapshot(
        token,
        as_of_ts=engine.clock(),
        trades=engine._trades[MINT_ALPHA_CURVE],
        liquidity_profile=liq,
        safety_report=safety,
        wallet_report=wallet,
        curve=curve,
    )
    candidates = detect_strategy_candidates(token, snap, safety, trades=engine._trades[MINT_ALPHA_CURVE])
    assert len(STRATEGY_NAMES) == 8
    assert len(candidates) >= 3
    for c in candidates:
        assert c.strategy in STRATEGY_NAMES
        assert c.execution_permission == "none"

    forecast = predict_pump_outcomes(snap, liq, safety)
    assert forecast.execution_permission == "none"
    assert 0.0 < forecast.prob_positive_return < 1.0
    assert 0.0 < forecast.prob_target_before_stop < 1.0
    assert 0.0 < forecast.prob_severe_drawdown < 1.0
    assert 0.0 < forecast.migration_completion_prob < 1.0

    ranked = rank_candidates_by_ev([(c, forecast, liq) for c in candidates])
    assert len(ranked) == len(candidates)
    assert all(r.execution_permission == "none" for r in ranked)

    # Survivorship-bias-free dataset validation vs baselines
    rug_safety = evaluate_token_safety(
        engine.discovery.get_by_mint(MINT_ALPHA_RUG),
        liquidity_profile=liq,
        wallet_report=wallet,
        apply_lifecycle_rejection=False,
    )
    samples = [
        HistoricalTokenSample(
            mint=f"SampLeMint{i + 1:2d}111111111111111111111111111111".replace(" ", "1"),
            status="graduated" if i % 3 == 0 else ("failed_inactive" if i % 2 == 1 else "active_curve"),
            snapshot=snap,
            liquidity=liq,
            safety=safety if i % 2 == 0 else rug_safety,
            realized_net_return_bps=320.0 if i % 2 == 0 else -420.0,
            hit_target_before_stop=(i % 2 == 0),
        )
        for i in range(10)
    ]
    eval_res = evaluate_models_vs_baselines(samples)
    assert eval_res["includes_failed_and_inactive"] is True
    assert "take_all_baseline" in eval_res
    assert "calibrated_ml_ev_filter" in eval_res


# ---------------------------------------------------------------------------
# 12, 13, 14, 15, 16, 17. Execution, Tx Simulation, Slippage, Limits, Risk & Wallet Guard
# ---------------------------------------------------------------------------


def test_execution_simulation_slippage_spending_limits_risk_and_wallet_guard():
    engine = PumpIntelligenceEngine()
    tok = engine.discovery.get_by_mint(MINT_ALPHA_CURVE)
    curve = engine.discovery.curve_for(MINT_ALPHA_CURVE)

    # 1. Wallet security guard blocks LLM/AI/plugin signing requests, unapproved programs, overspending, and scrubs secrets
    guard = DedicatedTradingWalletGuard(max_sol_per_tx=1.5, max_daily_sol_spend=3.0)
    valid_env = engine.execution.build_and_simulate_transaction(
        client_order_id="test_env_1",
        token=tok,
        side="buy",
        size_sol=0.2,
        slippage_bps=150.0,
        curve=curve,
    )
    approved_risk = engine.risk_engine.evaluate_order(
        token=tok,
        side="buy",
        size_sol=0.2,
        slippage_bps=150.0,
        liquidity_profile=evaluate_liquidity_and_impact(tok, order_size_sol=0.2, curve=curve),
        safety_report=evaluate_token_safety(
            tok,
            liquidity_profile=evaluate_liquidity_and_impact(tok, order_size_sol=0.2, curve=curve),
            wallet_report=analyze_wallet_intelligence(mint=MINT_ALPHA_CURVE, creator_wallet=tok.creator_wallet, holders=engine._holders[MINT_ALPHA_CURVE], trades=engine._trades[MINT_ALPHA_CURVE]),
        ),
        portfolio=engine.portfolio,
        data_age_seconds=1.0,
    )

    with pytest.raises(WalletSecurityError, match="forbidden origin"):
        guard.validate_transaction_for_signing(valid_env, origin="llm", risk_decision=approved_risk)

    bad_prog_env = {**valid_env, "program_ids": ("UnapprovedProgram11111111111111111111111111",)}
    with pytest.raises(WalletSecurityError, match="unapproved program IDs"):
        guard.validate_transaction_for_signing(bad_prog_env, origin="execution_adapter", risk_decision=approved_risk)

    overspend_env = {**valid_env, "quote_spend_sol": 2.0}
    with pytest.raises(WalletSecurityError, match="Spending limit exceeded"):
        guard.validate_transaction_for_signing(overspend_env, origin="execution_adapter", risk_decision=approved_risk)

    scrubbed = guard.scrub_telemetry({"tx": "ok", "private_key": "SECRET_KEY_BYTES", "nested": {"secret_key": "123"}})
    assert scrubbed["private_key"] == "[REDACTED_WALLET_SECRET]"
    assert scrubbed["nested"]["secret_key"] == "[REDACTED_WALLET_SECRET]"

    # 2. Live execution mode is strictly refused by deterministic risk engine
    live_attempt = engine.execute_end_to_end_order(
        client_order_id="ord_live_1",
        mint=MINT_ALPHA_CURVE,
        side="buy",
        size_sol=0.25,
        requested_mode="live",
    )
    assert live_attempt["status"] == "rejected_by_risk_control"
    assert "live_execution_refused:paper_only_default" in live_attempt["risk_decision"]["reject_reasons"]

    # 3. Risk-rejected token (MINT_ALPHA_RUG) is blocked by deterministic risk control
    rug_attempt = engine.execute_end_to_end_order(
        client_order_id="ord_rug_1",
        mint=MINT_ALPHA_RUG,
        side="buy",
        size_sol=0.25,
    )
    assert rug_attempt["status"] == "rejected_by_risk_control"

    # 4. Migration-pending token is blocked during migration freeze
    mig_attempt = engine.execute_end_to_end_order(
        client_order_id="ord_mig_1",
        mint=MINT_MIGRATING,
        side="buy",
        size_sol=0.25,
    )
    assert mig_attempt["status"] == "rejected_by_risk_control"
    assert "token_tradable" in mig_attempt["risk_decision"]["reject_reasons"]

    # 5. Tight slippage rejection on paper execution
    slip_reject = engine.execution.execute_paper_order(
        client_order_id="ord_slip_reject_1",
        token=tok,
        side="buy",
        size_sol=1.0,
        slippage_bps=1.0,  # 1 bps is tighter than curve fee + impact (125+ bps)
        risk_decision=approved_risk,
        portfolio=engine.portfolio,
        curve=curve,
    )
    assert slip_reject.status == "rejected"
    assert slip_reject.account_count == 17

    # 6. Valid paper buy + sell cycle on MINT_ALPHA_CURVE
    buy_res = engine.execute_end_to_end_order(
        client_order_id="ord_alpha_buy_1",
        mint=MINT_ALPHA_CURVE,
        side="buy",
        size_sol=0.4,
        slippage_bps=250.0,
    )
    assert buy_res["status"] == "confirmed"
    positions_by_mint = {p["mint"]: p for p in buy_res["portfolio"]["positions"]}
    assert MINT_ALPHA_CURVE in positions_by_mint
    pos_info = positions_by_mint[MINT_ALPHA_CURVE]
    # Liquidation mark is strictly less than cost basis immediately after buy due to round-trip fees & exit impact
    assert pos_info["realizable_exit_value_sol"] < pos_info["cost_basis_sol"]

    # Duplicate client_order_id is idempotently returned without double-spending
    dup_res = engine.execute_end_to_end_order(
        client_order_id="ord_alpha_buy_1",
        mint=MINT_ALPHA_CURVE,
        side="buy",
        size_sol=0.4,
        slippage_bps=250.0,
    )
    assert dup_res["order"]["tx_signature"] == buy_res["order"]["tx_signature"]

    sell_res = engine.execute_end_to_end_order(
        client_order_id="ord_alpha_sell_1",
        mint=MINT_ALPHA_CURVE,
        side="sell",
        size_sol=0.4,
        slippage_bps=250.0,
    )
    assert sell_res["status"] == "confirmed"
    assert len(sell_res["portfolio"]["positions"]) == 0


# ---------------------------------------------------------------------------
# 18 & 19. Confirmation Monitoring, Reorg Rollback, Portfolio & Replay
# ---------------------------------------------------------------------------


def test_indexer_reorg_rollback_confirmation_monitoring_and_event_replay():
    # 1. SolanaRPCIndexer deduplication, slot ordering, confirmation advancement, and reorg rollback
    indexer = SolanaRPCIndexer()
    ev1 = IndexedChainEvent(
        signature="sig_slot_100",
        slot=100,
        tx_index=1,
        instruction_index=0,
        event_type="curve_trade",
        mint=MINT_ALPHA_CURVE,
        program_id=PUMP_PROGRAM_ID,
        event_time=1_700_000_000.0,
        receipt_time=1_700_000_000.2,
        confirmation="processed",
        block_hash="hash_100_a",
    )
    assert indexer.ingest_event(ev1) is True
    assert indexer.ingest_event(ev1) is False  # Deduplicated

    # Advance confirmation processed -> confirmed -> finalized (deduped return=False, upgraded in place)
    ev1_conf = IndexedChainEvent(
        signature="sig_slot_100",
        slot=100,
        tx_index=1,
        instruction_index=0,
        event_type="curve_trade",
        mint=MINT_ALPHA_CURVE,
        program_id=PUMP_PROGRAM_ID,
        event_time=1_700_000_000.0,
        receipt_time=1_700_000_000.5,
        confirmation="finalized",
        block_hash="hash_100_a",
    )
    assert indexer.ingest_event(ev1_conf) is False
    assert indexer.events_for_mint(MINT_ALPHA_CURVE)[0].confirmation == "finalized"

    # Ingest unfinalized fork event at slot 102, then trigger reorg with competing block_hash
    ev_fork_a = IndexedChainEvent(
        signature="sig_slot_102_fork_a",
        slot=102,
        tx_index=0,
        instruction_index=0,
        event_type="curve_trade",
        mint=MINT_ALPHA_CURVE,
        program_id=PUMP_PROGRAM_ID,
        event_time=1_700_000_002.0,
        receipt_time=1_700_000_002.1,
        confirmation="confirmed",
        block_hash="hash_102_fork_a",
    )
    ev_fork_b = IndexedChainEvent(
        signature="sig_slot_102_fork_b",
        slot=102,
        tx_index=0,
        instruction_index=0,
        event_type="curve_trade",
        mint=MINT_ALPHA_CURVE,
        program_id=PUMP_PROGRAM_ID,
        event_time=1_700_000_002.0,
        receipt_time=1_700_000_002.3,
        confirmation="confirmed",
        block_hash="hash_102_fork_b",
    )
    indexer.ingest_event(ev_fork_a)
    indexer.ingest_event(ev_fork_b)
    sigs = [e.signature for e in indexer.events_for_mint(MINT_ALPHA_CURVE)]
    assert "sig_slot_102_fork_a" not in sigs
    assert "sig_slot_102_fork_b" in sigs

    # 2. Event-driven replay marks positions and exits via curve/pool quotes (never last trade price)
    engine = PumpIntelligenceEngine()
    c_start = engine.discovery.curve_for(MINT_ALPHA_CURVE)
    c_mid = BondingCurveState(
        mint=MINT_ALPHA_CURVE,
        bonding_curve_address=c_start.bonding_curve_address,
        virtual_token_reserves=int(c_start.virtual_token_reserves * 0.90),
        virtual_quote_reserves=int(c_start.virtual_quote_reserves * 1.12),
        real_token_reserves=int(c_start.real_token_reserves * 0.88),
        real_quote_reserves=int(c_start.real_quote_reserves * 1.15),
        creator=c_start.creator,
    )
    frames = [
        ReplayFrame(
            mint=MINT_ALPHA_CURVE,
            symbol="ALPHA",
            slot=1,
            event_time=1_700_000_000.0,
            venue="bonding_curve",
            last_trade_price_sol=c_start.price_quote_per_token,
            curve=c_start,
            signal_action="buy",
        ),
        ReplayFrame(
            mint=MINT_ALPHA_CURVE,
            symbol="ALPHA",
            slot=2,
            event_time=1_700_000_030.0,
            venue="bonding_curve",
            last_trade_price_sol=c_mid.price_quote_per_token,
            curve=c_mid,
            signal_action="sell",
        ),
    ]
    replay_res = run_event_driven_replay(frames, order_size_sol=0.5)
    assert replay_res.attempted_trades == 2
    assert replay_res.completed_round_trips == 1
    assert replay_res.marked_at_last_trade_price is False


# ---------------------------------------------------------------------------
# FastAPI /api/pump/* Endpoints & AI Node Registration
# ---------------------------------------------------------------------------


def test_pump_fastapi_endpoints_and_ai_node_registration():
    client = TestClient(app)

    # AI node lists pump_intelligence component with execution_permission: none
    ai_status = client.get("/api/ai/status")
    assert ai_status.status_code == 200
    comps = {c["name"]: c for c in ai_status.json()["components"]}
    assert "pump_intelligence" in comps

    # Workbench snapshot
    wb = client.get("/api/pump/workbench")
    assert wb.status_code == 200
    wb_data = wb.json()
    assert wb_data["execution_permission"] == "none"
    assert len(wb_data["tokens"]) >= 4

    # Single token detail by mint works; bare symbol returns 400
    bad_sym = client.get("/api/pump/tokens/ALPHA")
    assert bad_sym.status_code == 400

    good_mint = client.get(f"/api/pump/tokens/{MINT_ALPHA_CURVE}")
    assert good_mint.status_code == 200
    assert good_mint.json()["token"]["mint"] == MINT_ALPHA_CURVE

    # Quote endpoint
    q_resp = client.post(
        "/api/pump/quote",
        json={"mint": MINT_GRAD_SWAP, "side": "buy", "size_sol": 0.5, "slippage_bps": 150.0},
    )
    assert q_resp.status_code == 200
    assert q_resp.json()["venue"] == "pumpswap"

    # Paper order endpoint
    ord_resp = client.post(
        "/api/pump/paper-order",
        json={
            "client_order_id": "api_test_ord_1",
            "mint": MINT_GRAD_SWAP,
            "side": "buy",
            "size_sol": 0.3,
            "slippage_bps": 200.0,
            "requested_mode": "paper",
        },
    )
    assert ord_resp.status_code == 200
    assert ord_resp.json()["status"] == "confirmed"

    # Replay endpoint
    rep_resp = client.post("/api/pump/replay")
    assert rep_resp.status_code == 200
    assert rep_resp.json()["completed_round_trips"] >= 1
    assert rep_resp.json()["marked_at_last_trade_price"] is False


def test_transaction_monitoring_and_performance_summary():
    mon = PumpMonitoringService()
    tx = mon.track_submission(
        signature="5SigMon111111111111111111111111111111111111",
        client_order_id="mon_ord_1",
        mint=MINT_ALPHA_CURVE,
        side="buy",
        slot=300_100,
        ts=1_700_000_000.0,
        initial_confirmation="processed",
    )
    assert tx.reconciled is False
    tx_conf = mon.update_confirmation("5SigMon111111111111111111111111111111111111", confirmation_level="confirmed", slot=300_101)
    assert tx_conf.reconciled is True
    assert tx_conf.confirmed_slot == 300_101
    tx_fin = mon.update_confirmation("5SigMon111111111111111111111111111111111111", confirmation_level="finalized", slot=300_132)
    assert tx_fin.finalized_slot == 300_132

    mon.record_outcome(
        mint=MINT_ALPHA_CURVE,
        strategy="launch_momentum",
        predicted_prob_win=0.62,
        predicted_net_ev_bps=85.0,
        realized_net_pnl_bps=110.0,
        won=True,
        ts=1_700_000_900.0,
    )
    perf = mon.performance_summary()
    assert perf["recorded_outcomes"] == 1
    assert perf["win_rate"] == 1.0
    assert "launch_momentum" in perf["by_strategy"]


