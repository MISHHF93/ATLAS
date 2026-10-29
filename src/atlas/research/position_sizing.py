"""Dynamic Position-Sizing Research & Deterministic Control-Plane Constraint Cascade.

Implements Sections 13 and 14 of the ATLAS Complete Research-to-Execution
Intelligence Integration specification, incorporating mathematical methods from
tradermonty/claude-trading-skills with conservative fractional Kelly caps,
ATR volatility scaling, contract multiplier alignment, and deterministic risk checks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import math
from typing import Any

from atlas.feeds.contracts import contract_for
from atlas.market.sessions import evaluate_candidate_market_gate

EXECUTION_PERMISSION = "none"


@dataclass
class SizingProposal:
    candidate_id: str
    account_id: str
    instrument_id: str
    track: str
    sizing_method: str
    account_equity_usd: float
    risk_fraction_requested: float
    risk_budget: float
    entry_price: float
    stop_price: float
    stop_distance: float
    stop_distance_bps: float
    atr_value: float | None
    atr_multiplier: float | None
    value_per_price_unit: float
    contract_multiplier: float
    tick_size: float
    estimated_costs: float
    raw_fixed_fractional_qty: float
    kelly_full_fraction: float | None
    kelly_fractional_cap: float | None
    volatility_adjustment: float
    liquidity_adjustment: float
    uncertainty_adjustment: float
    portfolio_adjustment: float
    proposed_quantity: float
    proposed_notional_usd: float
    binding_constraint: str
    constraint_evaluations: list[dict[str, Any]]
    market_gate: dict[str, Any]
    risk_engine_decision: dict[str, Any]
    execution_permission: str = EXECUTION_PERMISSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_dynamic_position_sizing(
    *,
    candidate_id: str = "cand-001",
    account_id: str = "paper-main",
    symbol: str = "GC",
    side: str = "buy",
    track: str = "competition",
    entry_price: float = 2750.0,
    stop_price: float | None = None,
    atr_value: float | None = 12.5,
    atr_multiplier: float = 1.5,
    account_equity_usd: float | None = None,
    risk_fraction: float = 0.005,
    win_probability: float | None = None,
    payoff_ratio_b: float | None = 2.0,
    calibration_ece: float = 0.04,
    spread_bps: float = 2.5,
    liquidity_score: float = 0.90,
    current_drawdown_pct: float = 0.5,
    correlated_exposure_usd: float = 0.0,
    sector_exposure_usd: float = 0.0,
    daily_loss_used_usd: float = 0.0,
    event_risk_active: bool = False,
    data_age_ms: float | None = None,
) -> dict[str, Any]:
    """Sections 13 & 14: Compute Fixed-Fractional, ATR-Based, and Uncertainty-Penalized Kelly sizing."""
    from atlas.api.app import control_engine
    from atlas.control.engine import ActionableOrderRequest

    sym = symbol.upper().strip()
    from atlas.research.control_snapshot import control_snapshot
    cp_state = control_snapshot()
    cp_acct = cp_state.get("account", {})
    equity = float(account_equity_usd if account_equity_usd is not None else cp_acct["current_equity_usd"])

    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    # 1. Stop Distance Calculation (Explicit stop_price or ATR * ATRMultiplier)
    if stop_price is not None and stop_price > 0 and abs(entry_price - stop_price) > 1e-9:
        stop_dist = abs(entry_price - stop_price)
        effective_stop = float(stop_price)
        method_used = "fixed_fractional_explicit_stop"
    elif atr_value is not None and atr_value > 0 and atr_multiplier > 0:
        stop_dist = float(atr_value) * float(atr_multiplier)
        effective_stop = entry_price - stop_dist if side == "buy" else entry_price + stop_dist
        method_used = "atr_based_volatility_stop"
    else:
        raise ValueError("Either a valid stop_price or positive atr_value + atr_multiplier is required.")

    stop_dist_bps = (stop_dist / entry_price) * 10_000.0

    # 2. Contract Specification Lookup (ValuePerPriceUnit, Multiplier, Tick Size, Round-Trip Cost)
    spec = contract_for(sym)
    contract_mult = float(spec.multiplier) if spec else 1.0
    tick_size = float(spec.tick_size) if spec else 0.01
    rt_cost_per_unit = float(spec.cost_per_contract_rt_usd) if spec else (entry_price * (spread_bps / 10_000.0))
    value_per_price_unit = contract_mult

    # 3. Kelly Research Calculation (f* = p - (1 - p) / b) with Quarter-Kelly & Uncertainty Penalty
    kelly_full: float | None = None
    kelly_capped: float | None = None
    if win_probability is not None and payoff_ratio_b is not None and payoff_ratio_b > 0:
        p = max(0.0, min(1.0, float(win_probability)))
        b = float(payoff_ratio_b)
        kelly_full = p - ((1.0 - p) / b)
        # Quarter-Kelly (0.25 * f*) penalized by calibration error and hard-capped at 1.0% equity
        uncertainty_haircut = max(0.2, 1.0 - min(0.8, calibration_ece * 5.0))
        kelly_capped = max(0.0, min(0.01, 0.25 * max(0.0, kelly_full) * uncertainty_haircut))

    # 4. Base Risk Budget (Strictest of requested risk_fraction, 1.0% hard cap, and Kelly cap if negative EV)
    max_trade_risk_frac = 0.005 if track == "competition" else 0.010
    effective_risk_frac = min(max(0.0, float(risk_fraction)), max_trade_risk_frac)
    if kelly_full is not None and kelly_full <= 0:
        effective_risk_frac = 0.0

    risk_budget_usd = equity * effective_risk_frac
    per_unit_risk_usd = (stop_dist * value_per_price_unit) + rt_cost_per_unit
    raw_qty = (risk_budget_usd / per_unit_risk_usd) if per_unit_risk_usd > 0 else 0.0

    # 5. Real Market Condition Adjustments (Section 14)
    atr_pct = ((atr_value or stop_dist) / entry_price) * 100.0
    vol_adj = 1.0 if atr_pct <= 2.0 else max(0.35, 2.0 / atr_pct)
    liq_adj = max(0.0, min(1.0, float(liquidity_score))) if spread_bps <= 15.0 else max(0.25, 15.0 / spread_bps)
    unc_adj = max(0.25, 1.0 - min(0.75, calibration_ece * 4.0))
    dd_adj = 1.0 if current_drawdown_pct <= 1.0 else max(0.25, 1.0 - (current_drawdown_pct / 5.0))
    event_adj = 0.5 if event_risk_active else 1.0
    port_adj = round(dd_adj * event_adj, 4)

    adjusted_qty = raw_qty * vol_adj * liq_adj * unc_adj * port_adj

    # 6. Portfolio Constraint Cascade (Strictest Constraint Prevails)
    unit_notional = entry_price * contract_mult
    max_pos_notional = equity * (0.20 if track == "competition" else 0.25)
    max_sector_notional = max(0.0, (equity * 0.35) - sector_exposure_usd)
    max_corr_notional = max(0.0, (equity * 0.40) - correlated_exposure_usd)
    max_daily_loss_rem = max(0.0, (equity * 0.02) - daily_loss_used_usd)

    constraints: list[ tuple[str, float, str] ] = [
        ("risk_budget_and_market_adjustments", adjusted_qty, f"Risk budget ${risk_budget_usd:.2f} with vol/liq/uncertainty adjustments"),
        ("max_position_notional_cap", max_pos_notional / max(1e-9, unit_notional), f"Max position notional ${max_pos_notional:.2f}"),
        ("max_sector_exposure_cap", max_sector_notional / max(1e-9, unit_notional), f"Remaining sector room ${max_sector_notional:.2f}"),
        ("max_correlated_exposure_cap", max_corr_notional / max(1e-9, unit_notional), f"Remaining correlated room ${max_corr_notional:.2f}"),
        ("daily_loss_remaining_room", max_daily_loss_rem / max(1e-9, per_unit_risk_usd), f"Remaining 2% daily loss room ${max_daily_loss_rem:.2f}"),
    ]
    if kelly_full is not None and kelly_full <= 0:
        constraints.append(("negative_expected_value_kelly_gate", 0.0, f"Kelly fraction {kelly_full:.4f} <= 0 (negative EV)"))
    if spread_bps > 35.0 or liquidity_score < 0.20:
        constraints.append(("minimum_liquidity_and_slippage_gate", 0.0, f"Spread {spread_bps} bps or liquidity {liquidity_score} violates threshold"))

    binding_name, min_qty, _ = min(constraints, key=lambda item: item[1])
    if kelly_full is not None and kelly_full <= 0:
        binding_name, min_qty = "negative_expected_value_kelly_gate", 0.0

    # Round down to whole contracts for futures, or 4 decimals for spot/equities
    if spec is not None:
        final_qty = float(max(0, math.floor(min_qty)))
        if final_qty == 0.0 and min_qty > 0 and binding_name == "risk_budget_and_market_adjustments":
            binding_name = "futures_whole_contract_lot_minimum"
    else:
        final_qty = round(max(0.0, min_qty), 4)

    final_notional = round(final_qty * unit_notional, 2)
    est_costs = round(final_qty * rt_cost_per_unit, 2)

    # 7. Market Status Gate (Section 21)
    market_gate = evaluate_candidate_market_gate(sym)

    # 8. Deterministic Control Plane Evaluation (Read-Only Dry Run on Throwaway Clone)
    req_notional = Decimal(f"{max(0.0, final_notional):.2f}")
    req_stop_bps = Decimal(f"{max(0.0, stop_dist_bps):.2f}")
    if final_qty <= 0:
        cp_decision = {
            "decision": "REJECTED",
            "reason": f"Proposed quantity is 0 due to binding constraint: {binding_name}",
            "approved_quantity": 0.0,
            "approved_notional_usd": 0.0,
        }
    elif data_age_ms is None:
        cp_decision = {
            "decision": "UNAVAILABLE",
            "reason": "data_age_ms not supplied; control-plane dry run requires a real market-data age",
            "approved_quantity": 0.0,
            "approved_notional_usd": 0.0,
        }
    else:
        order_req = ActionableOrderRequest(
            instrument_id=f"comp:{sym.lower()}:v1",
            track="competition" if track == "competition" else "open_market",
            side="buy" if side == "buy" else "sell",
            notional_usd=req_notional,
            stop_distance_bps=req_stop_bps,
            stop_kind="atr" if "atr" in method_used else "structure",
            data_age_ms=float(data_age_ms),
        )
        # preview_order = the exact rules submit_order applies, without booking anything (dry run only).
        report = control_engine.preview_order(order_req)
        ok = bool(report.compliance_passed)
        cp_decision = {
            "decision": "APPROVED" if ok else "REJECTED",
            "reason": "control-plane dry run passed" if ok else "; ".join(report.violations),
            "violations": list(report.violations),
            "rulebook_id": report.rulebook_id,
            "approved_quantity": final_qty if ok else 0.0,
            "approved_notional_usd": final_notional if ok else 0.0,
        }

    proposal = SizingProposal(
        candidate_id=candidate_id,
        account_id=account_id,
        instrument_id=sym,
        track=track,
        sizing_method=method_used,
        account_equity_usd=round(equity, 2),
        risk_fraction_requested=risk_fraction,
        risk_budget=round(risk_budget_usd, 2),
        entry_price=entry_price,
        stop_price=round(effective_stop, 6),
        stop_distance=round(stop_dist, 6),
        stop_distance_bps=round(stop_dist_bps, 2),
        atr_value=atr_value,
        atr_multiplier=atr_multiplier,
        value_per_price_unit=value_per_price_unit,
        contract_multiplier=contract_mult,
        tick_size=tick_size,
        estimated_costs=est_costs,
        raw_fixed_fractional_qty=round(raw_qty, 4),
        kelly_full_fraction=round(kelly_full, 4) if kelly_full is not None else None,
        kelly_fractional_cap=round(kelly_capped, 4) if kelly_capped is not None else None,
        volatility_adjustment=round(vol_adj, 4),
        liquidity_adjustment=round(liq_adj, 4),
        uncertainty_adjustment=round(unc_adj, 4),
        portfolio_adjustment=round(port_adj, 4),
        proposed_quantity=final_qty,
        proposed_notional_usd=final_notional,
        binding_constraint=binding_name,
        constraint_evaluations=[
            {"constraint": c_name, "max_quantity": round(c_qty, 4), "detail": c_desc}
            for c_name, c_qty, c_desc in constraints
        ],
        market_gate=market_gate,
        risk_engine_decision=cp_decision,
    )
    return proposal.to_dict()

