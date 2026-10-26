"""Point-in-time (PIT) causal feature engineering for Pump.fun & PumpSwap tokens.

Every feature carries its exact observation timestamp (`feature_timestamps`), and
`build_pump_feature_snapshot` raises `LookaheadBiasError` if any input event or
feature timestamp is strictly greater than `as_of_ts`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..bonding_curve import BondingCurveState
from ..liquidity import LiquidityAndImpactProfile
from ..pumpswap import PumpSwapPoolState
from ..token_risk import TokenSafetyReport
from ..tokens import PumpTokenRecord
from ..wallet_intelligence import WalletIntelligenceReport, WalletTradeSample


class LookaheadBiasError(RuntimeError):
    """Raised when an event or feature timestamp is later than the point-in-time `as_of_ts`."""


@dataclass(frozen=True)
class PumpFeatureSnapshot:
    mint: str
    as_of_ts: float
    slot: int
    values: dict[str, float]
    timestamps: dict[str, float]
    data_quality_flags: tuple[str, ...] = ()
    execution_permission: str = "none"

    def __post_init__(self) -> None:
        for name, ts in self.timestamps.items():
            if float(ts) > float(self.as_of_ts) + 1e-6:
                raise LookaheadBiasError(
                    f"Lookahead bias detected on {self.mint}: feature {name!r} timestamp {ts} > as_of_ts {self.as_of_ts}"
                )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_pump_feature_snapshot(
    token: PumpTokenRecord,
    *,
    as_of_ts: float,
    trades: Sequence[WalletTradeSample],
    liquidity_profile: LiquidityAndImpactProfile,
    safety_report: TokenSafetyReport,
    wallet_report: WalletIntelligenceReport,
    curve: BondingCurveState | None = None,
    pool: PumpSwapPoolState | None = None,
    max_stale_seconds: float = 60.0,
) -> PumpFeatureSnapshot:
    """Compute a strictly causal point-in-time feature vector from closed trades at or before `as_of_ts`."""
    if token.creation_timestamp > as_of_ts + 1e-6:
        raise LookaheadBiasError(
            f"Token {token.mint} creation_timestamp {token.creation_timestamp} > as_of_ts {as_of_ts}"
        )
    for t in trades:
        if t.event_time > as_of_ts + 1e-6:
            raise LookaheadBiasError(
                f"Trade {t.signature} on {token.mint} has event_time {t.event_time} > as_of_ts {as_of_ts}"
            )
    if curve is not None and curve.event_time > as_of_ts + 1e-6:
        raise LookaheadBiasError(f"Curve state event_time {curve.event_time} > as_of_ts {as_of_ts}")
    if pool is not None and pool.event_time > as_of_ts + 1e-6:
        raise LookaheadBiasError(f"Pool state event_time {pool.event_time} > as_of_ts {as_of_ts}")

    ordered = sorted(trades, key=lambda x: (x.event_time, x.slot))
    last_event_ts = max(
        [token.creation_timestamp, *(t.event_time for t in ordered)]
        + ([curve.event_time] if curve and curve.event_time > 0 else [])
        + ([pool.event_time] if pool and pool.event_time > 0 else [])
    )

    flags: list[str] = []
    if as_of_ts - last_event_ts > max_stale_seconds:
        flags.append("stale_data")
    if token.data_provenance == "unavailable":
        flags.append("data_unavailable")
    if not liquidity_profile.sell_simulation_passed:
        flags.append("sell_simulation_failed")

    # Windowed trade activity (last 5m and 15m up to as_of_ts)
    w5m = [t for t in ordered if t.event_time >= as_of_ts - 300.0]
    w15m = [t for t in ordered if t.event_time >= as_of_ts - 900.0]

    buy_sol_5m = sum(t.quote_amount_sol for t in w5m if t.side == "buy")
    sell_sol_5m = sum(t.quote_amount_sol for t in w5m if t.side == "sell")
    tot_sol_5m = buy_sol_5m + sell_sol_5m
    order_flow_imbalance_5m = (buy_sol_5m - sell_sol_5m) / tot_sol_5m if tot_sol_5m > 0 else 0.0

    unique_buyers_5m = len({t.wallet for t in w5m if t.side == "buy"})
    unique_sellers_5m = len({t.wallet for t in w5m if t.side == "sell"})
    tx_freq_per_min_5m = len(w5m) / 5.0

    # Price return & realized volatility over causal window
    if len(w15m) >= 2 and w15m[0].price_quote > 0:
        ret_15m = (w15m[-1].price_quote / w15m[0].price_quote) - 1.0
    else:
        ret_15m = 0.0
    if len(w5m) >= 2 and w5m[0].price_quote > 0:
        ret_5m = (w5m[-1].price_quote / w5m[0].price_quote) - 1.0
    else:
        ret_5m = 0.0

    log_rets = []
    for a, b in zip(w15m, w15m[1:]):
        if a.price_quote > 0 and b.price_quote > 0:
            log_rets.append(math.log(b.price_quote / a.price_quote))
    realized_vol_15m = (
        math.sqrt(sum(r * r for r in log_rets) / len(log_rets))
        if log_rets
        else 0.0
    )

    # Pullback / impulse geometry
    prices_15m = [t.price_quote for t in w15m if t.price_quote > 0]
    if len(prices_15m) >= 3:
        lo_px = min(prices_15m)
        hi_px = max(prices_15m)
        cur_px = prices_15m[-1]
        impulse_range = max(1e-12, hi_px - lo_px)
        retracement_ratio = (hi_px - cur_px) / impulse_range if hi_px > lo_px else 0.0
    else:
        retracement_ratio = 0.0

    signed_offset_ratio = 0.0
    if pool is not None and pool.quote_vault_amount > 0:
        signed_offset_ratio = pool.virtual_quote_reserves / pool.quote_vault_amount
    elif curve is not None and curve.virtual_quote_reserves > 0:
        signed_offset_ratio = curve.signed_virtual_quote_reserves_offset / curve.virtual_quote_reserves

    values = {
        "age_minutes": round((as_of_ts - token.creation_timestamp) / 60.0, 4),
        "curve_progress_pct": round(float(token.curve_progress_pct), 4),
        "is_graduated": 1.0 if token.lifecycle_state.value == "PUMPSWAP_ACTIVE" else 0.0,
        "return_5m": round(ret_5m, 6),
        "return_15m": round(ret_15m, 6),
        "realized_vol_15m": round(realized_vol_15m, 6),
        "retracement_ratio_15m": round(retracement_ratio, 4),
        "volume_sol_5m": round(tot_sol_5m, 4),
        "order_flow_imbalance_5m": round(order_flow_imbalance_5m, 4),
        "unique_buyers_5m": float(unique_buyers_5m),
        "unique_sellers_5m": float(unique_sellers_5m),
        "tx_freq_per_min_5m": round(tx_freq_per_min_5m, 4),
        "whale_net_flow_sol": float(wallet_report.whale_activity.get("whale_net_flow_sol", 0.0)),
        "creator_holding_pct": float(safety_report.verified_on_chain_facts.get("creator_holding_pct", 0.0)),
        "top10_holder_pct": float(safety_report.verified_on_chain_facts.get("top10_holder_pct", 0.0)),
        "heuristic_cluster_pct": float(safety_report.heuristic_risk_scores.get("suspicious_cluster_pct", 0.0)),
        "composite_risk_score": float(safety_report.heuristic_risk_scores.get("composite_risk_score", 0.0)),
        "effective_liquidity_sol": float(liquidity_profile.effective_liquidity_sol),
        "round_trip_cost_bps": float(liquidity_profile.round_trip_cost_bps),
        "sell_price_impact_bps": float(liquidity_profile.sell_price_impact_bps),
        "signed_reserve_offset_ratio": round(signed_offset_ratio, 6),
    }
    timestamps = {k: float(last_event_ts) for k in values}

    return PumpFeatureSnapshot(
        mint=token.mint,
        as_of_ts=float(as_of_ts),
        slot=int(token.last_slot),
        values=values,
        timestamps=timestamps,
        data_quality_flags=tuple(flags),
    )

