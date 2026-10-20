"""Unit and integration tests for ATLAS Institutional Expansion & Autonomous Execution Engine.

Covers:
1. Microstructure & Whale Order Flow math accuracy (Kyle's Lambda, VPIN volume-synchronized
   buckets, Multi-Level OFI queue reinforcement, and Hawkes self-exciting intensity with causal filtering).
2. Almgren-Chriss Optimal Execution Schedule monotonicity, inventory liquidation boundary (x_T = 0),
   and child-slice conservation (sum(n_j) == X).
3. Autonomous Self-Training Loop ("Anti-Gravity" module): Triple-Barrier labeling, Prop-Aligned
   Objective Loss L(theta), and Purged/Embargoed Walk-Forward splits (proving zero lookahead leakage).
4. Deterministic Control-Plane Prop Rulebook Enforcement & VPIN flow toxicity stop-widening /
   adverse-selection quote pause.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.execution.tactics import compute_almgren_chriss_trajectory
from atlas.features.toxicity import (
    BookLevelSnapshot,
    compute_hawkes_intensity,
    compute_multilevel_ofi,
    compute_volume_synchronized_vpin,
    estimate_kyles_lambda,
)
from atlas.models.continuous import (
    build_purged_embargoed_splits,
    compute_prop_aligned_loss,
    label_triple_barrier_samples,
    run_autonomous_self_training_cycle,
)
from atlas.models.schemas import Observation


def _build_synthetic_observations(count: int = 36) -> tuple[Observation, ...]:
    base_time = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    obs: list[Observation] = []
    price = 100.0
    for i in range(count):
        # Deterministic wave + drift to trigger upper, lower, and vertical barriers
        step_ret = 0.0045 if i % 4 in (0, 1) else -0.0032
        price = round(price * (1.0 + step_ret), 4)
        ts = base_time + timedelta(hours=i)
        obs.append(
            Observation(
                event_time=ts - timedelta(minutes=1),
                available_at=ts,
                value=price,
            )
        )
    return tuple(obs)


def test_kyles_lambda_ols_and_execution_permission() -> None:
    # Exact linear relation Delta P_t = 0.005 * Q_t
    signed_q = [-200.0, -100.0, 50.0, 100.0, 250.0, 400.0]
    delta_p = [0.005 * q for q in signed_q]

    res = estimate_kyles_lambda(delta_p, signed_q, spike_threshold=0.003)
    assert res.execution_permission == "none"
    assert pytest.approx(res.lambda_impact, rel=1e-6) == 0.005
    assert pytest.approx(res.r_squared, rel=1e-6) == 1.0
    assert pytest.approx(res.residual_volatility_eta, abs=1e-8) == 0.0
    assert res.informed_spike_detected is True


def test_vpin_volume_synchronized_bucketing() -> None:
    # Strongly one-sided positive price deltas across 500 units of volume (5 buckets of V=100)
    price_deltas = [0.50, 0.65, 0.55, 0.70, 0.60]
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0]

    rep = compute_volume_synchronized_vpin(
        price_deltas,
        volumes,
        bucket_volume=100.0,
        max_buckets=5,
        toxicity_threshold=0.45,
    )
    assert rep.execution_permission == "none"
    assert rep.num_buckets_n == 5
    assert len(rep.buckets) == 5
    assert rep.vpin > 0.45
    assert rep.toxicity_alert is True
    assert rep.recommended_routing == "a_book_exhaust"
    for b in rep.buckets:
        assert pytest.approx(b.buy_volume + b.sell_volume, rel=1e-5) == 100.0


def test_multilevel_ofi_depth_weighted_imbalance() -> None:
    prev_book = (
        BookLevelSnapshot(level=1, bid_price=100.0, bid_size=10.0, ask_price=100.5, ask_size=12.0),
        BookLevelSnapshot(level=2, bid_price=99.5, bid_size=20.0, ask_price=101.0, ask_size=20.0),
        BookLevelSnapshot(level=3, bid_price=99.0, bid_size=30.0, ask_price=101.5, ask_size=25.0),
    )
    # Bid queues reinforce at same or higher price; ask queues deplete
    curr_book = (
        BookLevelSnapshot(level=1, bid_price=100.0, bid_size=35.0, ask_price=100.5, ask_size=4.0),
        BookLevelSnapshot(level=2, bid_price=99.5, bid_size=40.0, ask_price=101.0, ask_size=10.0),
        BookLevelSnapshot(level=3, bid_price=99.0, bid_size=45.0, ask_price=101.5, ask_size=15.0),
    )

    ofi = compute_multilevel_ofi(prev_book, curr_book, decay_lambda=0.65)
    assert ofi.execution_permission == "none"
    assert ofi.ofi_raw > 0.0
    assert ofi.ofi_normalized > 0.05
    assert ofi.dominant_pressure == "buy"
    assert len(ofi.level_contributions) == 3
    assert pytest.approx(sum(ofi.weights), abs=1e-4) == 1.0


def test_hawkes_self_exciting_intensity_causal_filtering() -> None:
    # Include future event at t=15.0 which MUST be ignored when evaluating at t=10.0
    events = [9.1, 9.4, 9.7, 9.9, 15.0]
    rep = compute_hawkes_intensity(
        events,
        eval_time_sec=10.0,
        mu_0=0.5,
        alpha=0.95,
        beta=1.10,
        clustering_threshold=1.5,
    )
    assert rep.execution_permission == "none"
    assert rep.event_count == 4  # Future event t=15.0 strictly excluded
    assert rep.intensity_lambda_t > 2.5
    assert rep.iceberg_clustering_detected is True
    assert rep.stationarity_valid is True


def test_almgren_chriss_monotonicity_and_terminal_liquidation() -> None:
    sched = compute_almgren_chriss_trajectory(
        initial_inventory=10_000.0,
        num_steps=8,
        total_time_T=1.0,
        risk_aversion_lambda=2e-5,
        volatility_sigma=0.025,
        temporary_impact_eta=2.0e-6,
        permanent_impact_gamma=1.0e-6,
    )
    assert sched.execution_permission == "none"
    assert sched.is_strictly_monotonic is True
    assert sched.terminal_inventory_zero is True
    assert sched.remaining_inventory_trajectory[-1] == 0.0
    assert pytest.approx(sum(sched.child_order_slices), rel=1e-5) == 10_000.0
    # Under positive risk aversion, early slices are larger than late slices (front-loaded liquidation)
    assert sched.child_order_slices[0] > sched.child_order_slices[-1]


def test_self_training_triple_barrier_and_purged_embargoed_splits() -> None:
    obs = _build_synthetic_observations(40)
    samples = label_triple_barrier_samples(
        obs,
        atr_window=5,
        barrier_multiplier_k=1.1,
        vertical_horizon_bars=3,
    )
    assert len(samples) > 20
    assert all(s.execution_permission == "none" for s in samples)
    assert all(s.label in (-1, 0, 1) for s in samples)
    assert all(s.barrier_touch_index > s.sample_index for s in samples)

    splits = build_purged_embargoed_splits(samples, num_folds=3, purge_bars=2, embargo_bars=2)
    assert len(splits) == 3
    sample_by_idx = {s.sample_index: s for s in samples}
    for fold in splits:
        assert fold.execution_permission == "none"
        assert fold.zero_leakage_verified is True
        first_test_obs = min(fold.test_sample_indices)
        # Prove zero lookahead leakage: every training sample's barrier_touch_index < first_test_obs - purge_bars
        for tr_idx in fold.train_sample_indices:
            assert sample_by_idx[tr_idx].barrier_touch_index < first_test_obs - 2


def test_prop_aligned_loss_and_autonomous_self_training_cycle() -> None:
    healthy_returns = [0.0025, 0.0018, -0.0010, 0.0030, 0.0022]
    healthy_pos = [1.0, 1.0, 0.5, 1.0, 1.0]
    loss_healthy = compute_prop_aligned_loss(healthy_returns, healthy_pos)
    assert loss_healthy.execution_permission == "none"
    assert loss_healthy.rule_breach_indicator_rate == 0.0
    assert loss_healthy.sharpe_ratio > 0.0

    # Simulate a daily loss breach (-5% single step > 4% daily limit)
    breach_returns = [-0.055, -0.030, -0.015, -0.010, -0.005]
    breach_pos = [1.0, 1.0, 1.0, 1.0, 1.0]
    loss_breach = compute_prop_aligned_loss(breach_returns, breach_pos)
    assert loss_breach.rule_breach_indicator_rate > 0.0
    assert loss_breach.expected_loss > loss_healthy.expected_loss

    obs = _build_synthetic_observations(36)
    gate_report = run_autonomous_self_training_cycle(obs, purge_bars=1, embargo_bars=1)
    assert gate_report.execution_permission == "none"
    assert gate_report.autonomous_self_promotion_blocked is True
    assert all(f.zero_leakage_verified for f in gate_report.purged_folds)


def test_control_plane_vpin_toxicity_stop_widening_and_pause() -> None:
    engine = ActionableControlPlaneEngine()
    now = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)

    # 1. Elevated VPIN (0.55 >= 0.45 widening threshold) with tight stop (30 bps < 25 * 1.50 = 37.5 bps) -> REJECTED
    tight_toxic_req = ActionableOrderRequest(
        track="competition",
        instrument_id="comp:btc-perp:v1",
        side="buy",
        notional_usd=Decimal("10000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("30"),
        holding_horizon_seconds=3600,
        vpin_toxicity=0.55,
    )
    decision_tight = engine.submit_order(tight_toxic_req, now=now)
    assert decision_tight.control_plane_decision == "rejected_by_control_plane"
    assert decision_tight.rule_evaluation.vpin_widened_stop_active is True
    assert any("vpin_widened_stop_violation" in v for v in decision_tight.violations)

    # 2. Same VPIN (0.55) with widened stop (45 bps >= 37.5 bps) -> AUTHORIZED
    wide_toxic_req = ActionableOrderRequest(
        track="competition",
        instrument_id="comp:btc-perp:v1",
        side="buy",
        notional_usd=Decimal("10000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("45"),
        holding_horizon_seconds=3600,
        vpin_toxicity=0.55,
    )
    decision_wide = engine.submit_order(wide_toxic_req, now=now)
    assert decision_wide.control_plane_decision == "authorized_and_executed"
    assert decision_wide.rule_evaluation.vpin_widened_stop_active is True

    # 3. Extreme VPIN (0.82 >= 0.70 pause threshold) -> ADVERSE SELECTION QUOTE PAUSE REJECTION
    extreme_toxic_req = ActionableOrderRequest(
        track="competition",
        instrument_id="comp:btc-perp:v1",
        side="buy",
        notional_usd=Decimal("10000"),
        stop_kind="atr",
        stop_distance_bps=Decimal("120"),
        holding_horizon_seconds=3600,
        vpin_toxicity=0.82,
    )
    decision_pause = engine.submit_order(extreme_toxic_req, now=now)
    assert decision_pause.control_plane_decision == "rejected_by_control_plane"
    assert decision_pause.rule_evaluation.adverse_selection_pause_active is True
    assert any("vpin_adverse_selection_pause" in v for v in decision_pause.violations)


def test_master_roadmap_excel_wf01_to_wf08_and_az_subsystems() -> None:
    """Verify every target subsystem path from the 7-tab Excel Master Roadmap exists and executes."""
    import importlib
    from pathlib import Path

    from atlas.calibration import platt_scale_probability
    from atlas.execution.rl_agent import evaluate_rl_execution_policy
    from atlas.hardware import run_vectorized_backtest
    from atlas.journal import append_chained_audit_entry
    from atlas.liquidity.impact import estimate_l2_market_impact
    from atlas.marketdata.crypto import evaluate_crypto_perp_domain
    from atlas.marketdata.equities import evaluate_us_equity_domain
    from atlas.marketdata.futures import evaluate_cme_futures_domain
    from atlas.marketdata.fx import evaluate_fx_cfd_domain
    from atlas.marketdata.synthetics import evaluate_synthetic_index_domain
    from atlas.microstructure.orderbook import compute_book_shannon_entropy
    from atlas.microstructure.predatory import evaluate_predatory_liquidation
    from atlas.models.microstructure_gbdt import predict_microstructure_spread_gbdt
    from atlas.portfolio import compute_portfolio_allocation
    from atlas.profile import check_rbac_boundary
    from atlas.regime.hawkes_detector import compute_hawkes_intensity as hawkes_det
    from atlas.sync import compute_cross_asset_delta_hedge
    from atlas.telemetry import evaluate_pipeline_telemetry
    from atlas.volatility import compute_atr_dynamic_sizing
    from atlas.warehouse import filter_observations_point_in_time
    from atlas.whale_saas_az import build_master_roadmap_state

    repo_root = Path(__file__).resolve().parents[1]
    state = build_master_roadmap_state("SPY", 0)
    assert len(state["roadmap_az"]) == 26
    for row in state["roadmap_az"]:
        assert row["status"] == "Implemented"
        assert (repo_root / row["path"]).exists(), f"Missing A-Z path: {row['path']}"

    for wf in state["whale_execution_ml"]:
        assert (repo_root / wf["subsystem"]).exists(), f"Missing WF path: {wf['subsystem']}"

    # WF-01..WF-08 & A-Z module checks
    book = (
        BookLevelSnapshot(level=1, bid_price=100.0, bid_size=15.0, ask_price=100.2, ask_size=15.0),
        BookLevelSnapshot(level=2, bid_price=99.8, bid_size=25.0, ask_price=100.4, ask_size=25.0),
    )
    l2_imp = estimate_l2_market_impact(book, order_quantity=25.0, side="buy")
    assert l2_imp.execution_permission == "none"
    assert l2_imp.levels_swept == 2

    entropy = compute_book_shannon_entropy(book)
    assert entropy > 0.0

    gbdt_pred = predict_microstructure_spread_gbdt(
        ofi_normalized=0.72,
        vpin=0.52,
        depth_levels=[15.0, 25.0, 30.0],
        l1_spread_bps=1.2,
        l2_spread_bps=2.5,
    )
    assert gbdt_pred.execution_permission == "none"
    assert gbdt_pred.cancel_passive_resting_orders is True

    pred_liq = evaluate_predatory_liquidation(350_000.0, 5_000_000.0, side="sell")
    assert pred_liq.execution_permission == "none"
    assert pred_liq.predatory_liquidation_alert is True

    rl_adv = evaluate_rl_execution_policy(ofi_normalized=0.30, spread_bps=1.5, inventory_fraction=0.70, vpin=0.25)
    assert rl_adv.execution_permission == "none"
    assert rl_adv.recommended_action == "almgren_chriss_twap_slice"

    # Global Multi-Domain Architecture (5 domains)
    assert evaluate_us_equity_domain("SPY").execution_permission == "none"
    assert evaluate_cme_futures_domain("ESZ6").execution_permission == "none"
    assert evaluate_crypto_perp_domain("BTC-PERP").execution_permission == "none"
    assert evaluate_fx_cfd_domain("EUR/USD", vpin_toxicity=0.55).dealing_desk_routing == "a_book_lp_exhaust"
    assert evaluate_synthetic_index_domain("VOL-75").execution_permission == "none"

    # A-Z Subsystems
    port = compute_portfolio_allocation(["SPY", "NVDA", "BTC-USD"], [0.12, 0.24, 0.30], [0.15, 0.35, 0.55])
    assert port.execution_permission == "none"
    assert pytest.approx(sum(port.risk_parity_weights), abs=1e-4) == 1.0

    obs = _build_synthetic_observations(10)
    kept, pit_rep = filter_observations_point_in_time(obs, as_of=obs[5].available_at)
    assert len(kept) == 6
    assert pit_rep.zero_lookahead_verified is True

    vec_bt = run_vectorized_backtest([0.01, -0.005, 0.012, 0.008], [1.0, 0.5, 1.0, 1.0])
    assert vec_bt.execution_permission == "none"

    audit_entry = append_chained_audit_entry(1, "order_checked", "SPY 100 shares")
    assert len(audit_entry.entry_sha256) == 64
    assert 0.0 < platt_scale_probability(0.8) < 1.0
    assert evaluate_pipeline_telemetry("databento_l2").health_status == "healthy"
    assert check_rbac_boundary("external_operator", "authorize_order").allowed is False
    assert compute_atr_dynamic_sizing("SPY").execution_permission == "none"
    assert compute_cross_asset_delta_hedge("NVDA", "BTC-USD").correlation_gate_passed is True
    assert hawkes_det([1.0, 1.2], eval_time_sec=1.5).execution_permission == "none"

    yield_mod = importlib.import_module("atlas.yield")
    basis_rep = yield_mod.evaluate_basis_funding_arbitrage("BTC-PERP")
    assert basis_rep.execution_permission == "none"

