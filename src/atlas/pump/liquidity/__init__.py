"""Liquidity, Solana base + priority fee calculation, price-impact modeling, and exit simulation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from ..bonding_curve import BondingCurveState, quote_curve_buy_exact_quote_in, quote_curve_sell
from ..pumpswap import PumpSwapPoolState, quote_pumpswap
from ..tokens import LAMPORTS_PER_SOL, PumpTokenRecord, TokenLifecycleState

# Official Solana fee constants (https://solana.com/docs/core/fees)
BASE_FEE_LAMPORTS_PER_SIGNATURE = 5_000
MICRO_LAMPORTS_PER_LAMPORT = 1_000_000
DEFAULT_SWAP_COMPUTE_UNITS = 120_000
DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS_PER_CU = 25_000


@dataclass(frozen=True)
class SolanaFeeEstimate:
    signatures: int
    compute_unit_limit: int
    micro_lamports_per_cu: int
    base_fee_lamports: int
    priority_fee_lamports: int
    total_fee_lamports: int
    total_fee_sol: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_solana_tx_fee(
    *,
    signatures: int = 1,
    compute_unit_limit: int = DEFAULT_SWAP_COMPUTE_UNITS,
    micro_lamports_per_cu: int = DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS_PER_CU,
) -> SolanaFeeEstimate:
    """Compute exact Solana transaction fee: base fee (5,000 lamports/sig) + priority fee (ceil(CU * price / 1e6))."""
    sigs = max(1, int(signatures))
    cu = max(1, int(compute_unit_limit))
    price = max(0, int(micro_lamports_per_cu))
    base_lamports = sigs * BASE_FEE_LAMPORTS_PER_SIGNATURE
    prio_lamports = math.ceil((cu * price) / MICRO_LAMPORTS_PER_LAMPORT)
    total = base_lamports + prio_lamports
    return SolanaFeeEstimate(
        signatures=sigs,
        compute_unit_limit=cu,
        micro_lamports_per_cu=price,
        base_fee_lamports=base_lamports,
        priority_fee_lamports=prio_lamports,
        total_fee_lamports=total,
        total_fee_sol=round(total / LAMPORTS_PER_SOL, 9),
    )


@dataclass(frozen=True)
class LiquidityAndImpactProfile:
    mint: str
    active_venue: str
    effective_liquidity_sol: float
    order_size_sol: float
    buy_tokens_out_raw: int
    sell_quote_out_sol: float
    buy_price_impact_bps: float
    sell_price_impact_bps: float
    round_trip_cost_bps: float
    solana_fee_sol: float
    sell_simulation_passed: bool
    max_safe_order_sol: float
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_liquidity_and_impact(
    token: PumpTokenRecord,
    *,
    order_size_sol: float = 0.5,
    curve: BondingCurveState | None = None,
    pool: PumpSwapPoolState | None = None,
    max_allowed_impact_bps: float = 250.0,
    micro_lamports_per_cu: int = DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS_PER_CU,
) -> LiquidityAndImpactProfile:
    """Model round-trip buy + exit liquidity, price impact, and Solana network fees on the active venue."""
    fee_est = estimate_solana_tx_fee(micro_lamports_per_cu=micro_lamports_per_cu)
    order_lamports = max(1, int(round(order_size_sol * LAMPORTS_PER_SOL)))

    if token.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE and pool is not None:
        eff_liq_sol = pool.effective_quote_reserves / LAMPORTS_PER_SOL
        if eff_liq_sol <= 0 or pool.effective_base_reserves <= 0:
            return LiquidityAndImpactProfile(
                mint=token.mint, active_venue="pumpswap", effective_liquidity_sol=0.0, order_size_sol=order_size_sol,
                buy_tokens_out_raw=0, sell_quote_out_sol=0.0, buy_price_impact_bps=10_000.0,
                sell_price_impact_bps=10_000.0, round_trip_cost_bps=10_000.0, solana_fee_sol=fee_est.total_fee_sol * 2,
                sell_simulation_passed=False, max_safe_order_sol=0.0, notes="Pool has zero effective liquidity",
            )
        buy_q = quote_pumpswap(pool, "buy", order_lamports)
        if buy_q.amount_out_raw <= 0:
            return LiquidityAndImpactProfile(
                mint=token.mint, active_venue="pumpswap", effective_liquidity_sol=eff_liq_sol, order_size_sol=order_size_sol,
                buy_tokens_out_raw=0, sell_quote_out_sol=0.0, buy_price_impact_bps=10_000.0,
                sell_price_impact_bps=10_000.0, round_trip_cost_bps=10_000.0, solana_fee_sol=fee_est.total_fee_sol * 2,
                sell_simulation_passed=False, max_safe_order_sol=0.0, notes="Buy quote returned 0 tokens",
            )
        sell_q = quote_pumpswap(pool, "sell", buy_q.amount_out_raw)
        sell_sol = sell_q.amount_out_raw / LAMPORTS_PER_SOL
        rt_loss_sol = max(0.0, order_size_sol - sell_sol + (fee_est.total_fee_sol * 2))
        rt_bps = (rt_loss_sol / order_size_sol) * 10_000.0 if order_size_sol > 0 else 0.0
        max_safe = eff_liq_sol * (max_allowed_impact_bps / 20_000.0)
        return LiquidityAndImpactProfile(
            mint=token.mint,
            active_venue="pumpswap",
            effective_liquidity_sol=round(eff_liq_sol, 6),
            order_size_sol=order_size_sol,
            buy_tokens_out_raw=buy_q.amount_out_raw,
            sell_quote_out_sol=round(sell_sol, 6),
            buy_price_impact_bps=buy_q.price_impact_bps,
            sell_price_impact_bps=sell_q.price_impact_bps,
            round_trip_cost_bps=round(rt_bps, 2),
            solana_fee_sol=round(fee_est.total_fee_sol * 2, 9),
            sell_simulation_passed=sell_q.amount_out_raw > 0 and sell_q.price_impact_bps <= max_allowed_impact_bps * 2,
            max_safe_order_sol=round(max_safe, 4),
        )

    if curve is not None and not curve.complete:
        eff_liq_sol = curve.effective_virtual_quote_reserves / LAMPORTS_PER_SOL
        real_liq_sol = curve.real_quote_reserves / LAMPORTS_PER_SOL
        buy_q = quote_curve_buy_exact_quote_in(curve, order_lamports)
        if buy_q.tokens_out_raw <= 0:
            return LiquidityAndImpactProfile(
                mint=token.mint, active_venue="bonding_curve", effective_liquidity_sol=eff_liq_sol,
                order_size_sol=order_size_sol, buy_tokens_out_raw=0, sell_quote_out_sol=0.0,
                buy_price_impact_bps=10_000.0, sell_price_impact_bps=10_000.0, round_trip_cost_bps=10_000.0,
                solana_fee_sol=fee_est.total_fee_sol * 2, sell_simulation_passed=False, max_safe_order_sol=0.0,
                notes="Curve buy quote returned 0 tokens",
            )
        # Simulate post-buy curve state to verify exit liquidity
        sim_curve = BondingCurveState(
            mint=curve.mint,
            bonding_curve_address=curve.bonding_curve_address,
            virtual_token_reserves=max(1, curve.virtual_token_reserves - buy_q.curve_tokens_filled_raw),
            virtual_quote_reserves=curve.virtual_quote_reserves + order_lamports,
            real_token_reserves=max(0, curve.real_token_reserves - buy_q.curve_tokens_filled_raw),
            real_quote_reserves=curve.real_quote_reserves + order_lamports - buy_q.total_fee_raw,
            unswept_protocol_fees=curve.unswept_protocol_fees + buy_q.protocol_fee_raw,
            unswept_creator_fees=curve.unswept_creator_fees + buy_q.creator_fee_raw,
            signed_virtual_quote_adjustment=curve.signed_virtual_quote_adjustment,
            complete=False,
        )
        sell_q = quote_curve_sell(sim_curve, buy_q.tokens_out_raw)
        sell_sol = sell_q.quote_out_raw / LAMPORTS_PER_SOL
        rt_loss_sol = max(0.0, order_size_sol - sell_sol + (fee_est.total_fee_sol * 2))
        rt_bps = (rt_loss_sol / order_size_sol) * 10_000.0 if order_size_sol > 0 else 0.0
        max_safe = eff_liq_sol * (max_allowed_impact_bps / 20_000.0)
        return LiquidityAndImpactProfile(
            mint=token.mint,
            active_venue="bonding_curve",
            effective_liquidity_sol=round(eff_liq_sol, 6),
            order_size_sol=order_size_sol,
            buy_tokens_out_raw=buy_q.tokens_out_raw,
            sell_quote_out_sol=round(sell_sol, 6),
            buy_price_impact_bps=buy_q.price_impact_bps,
            sell_price_impact_bps=sell_q.price_impact_bps,
            round_trip_cost_bps=round(rt_bps, 2),
            solana_fee_sol=round(fee_est.total_fee_sol * 2, 9),
            sell_simulation_passed=sell_q.quote_out_raw > 0 and real_liq_sol + order_size_sol > 0,
            max_safe_order_sol=round(max_safe, 4),
        )

    return LiquidityAndImpactProfile(
        mint=token.mint,
        active_venue=token.active_venue,
        effective_liquidity_sol=0.0,
        order_size_sol=order_size_sol,
        buy_tokens_out_raw=0,
        sell_quote_out_sol=0.0,
        buy_price_impact_bps=10_000.0,
        sell_price_impact_bps=10_000.0,
        round_trip_cost_bps=10_000.0,
        solana_fee_sol=round(fee_est.total_fee_sol * 2, 9),
        sell_simulation_passed=False,
        max_safe_order_sol=0.0,
        notes="No active bonding curve or PumpSwap pool state available",
    )

