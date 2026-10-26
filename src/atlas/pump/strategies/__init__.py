"""Causal Strategy Engine for Pump.fun & PumpSwap tokens.

Implements all 8 research candidate detectors:
1. `launch_momentum`
2. `launch_pullback_continuation`
3. `bonding_curve_momentum`
4. `post_graduation_momentum`
5. `liquidity_sweep_reversal`
6. `whale_flow_research`
7. `momentum_exhaustion`
8. `creator_risk_avoidance`

All strategies emit standard ATLAS candidate objects (`PumpStrategyCandidate`) with `execution_permission="none"`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from ..features import PumpFeatureSnapshot
from ..token_risk import TokenSafetyReport
from ..tokens import PumpTokenRecord, TokenLifecycleState
from ..wallet_intelligence import WalletTradeSample

STRATEGY_NAMES = (
    "launch_momentum",
    "launch_pullback_continuation",
    "bonding_curve_momentum",
    "post_graduation_momentum",
    "liquidity_sweep_reversal",
    "whale_flow_research",
    "momentum_exhaustion",
    "creator_risk_avoidance",
)


@dataclass(frozen=True)
class PumpStrategyCandidate:
    """Standard ATLAS research candidate emitted by a Pump.fun / Solana strategy detector."""
    candidate_id: str
    mint: str
    symbol: str
    strategy: str
    direction: str  # "long" | "exit_or_avoid" | "veto"
    actionable_research_entry: bool
    as_of_ts: float
    slot: int
    venue: str
    entry_price_quote: float
    stop_price_quote: float
    target_price_quote: float
    reward_risk_ratio: float
    signal_strength: float  # [0.0 .. 1.0]
    rationale: tuple[str, ...] = field(default_factory=tuple)
    risk_veto: bool = False
    execution_permission: str = "none"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_strategy_candidates(
    token: PumpTokenRecord,
    snapshot: PumpFeatureSnapshot,
    safety: TokenSafetyReport,
    trades: Sequence[WalletTradeSample] = (),
) -> list[PumpStrategyCandidate]:
    """Run all 8 causal strategy detectors at `snapshot.as_of_ts`."""
    f = snapshot.values
    px = max(1e-12, float(token.price_quote))
    as_of = snapshot.as_of_ts
    slot = snapshot.slot
    venue = token.active_venue
    candidates: list[PumpStrategyCandidate] = []

    # 8. Creator-Risk Avoidance (always runs first so its veto/down-rank is explicit)
    creator_risk_reasons: list[str] = []
    if safety.safety_status == "rejected":
        creator_risk_reasons.extend(safety.hard_reject_reasons)
    if f["creator_holding_pct"] >= 15.0:
        creator_risk_reasons.append(f"creator_holding_pct={f['creator_holding_pct']:.1f}%")
    if f["heuristic_cluster_pct"] >= 30.0:
        creator_risk_reasons.append(f"heuristic_cluster_pct={f['heuristic_cluster_pct']:.1f}%")
    if creator_risk_reasons:
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:creator_risk_avoidance:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="creator_risk_avoidance",
                direction="veto",
                actionable_research_entry=False,
                as_of_ts=as_of,
                slot=slot,
                venue=venue,
                entry_price_quote=px,
                stop_price_quote=px,
                target_price_quote=px,
                reward_risk_ratio=0.0,
                signal_strength=min(1.0, round(f["composite_risk_score"] / 100.0, 4)),
                rationale=tuple(creator_risk_reasons),
                risk_veto=True,
            )
        )

    hard_veto = safety.safety_status == "rejected" or not token.is_tradable()

    # 1. Launch Momentum
    if (
        0.5 <= f["age_minutes"] <= 45.0
        and f["return_5m"] >= 0.08
        and f["volume_sol_5m"] >= 3.0
        and f["unique_buyers_5m"] >= 4
        and f["tx_freq_per_min_5m"] >= 1.0
        and f["order_flow_imbalance_5m"] >= 0.20
    ):
        strength = min(1.0, 0.45 + 0.25 * min(1.0, f["return_5m"] / 0.25) + 0.30 * f["order_flow_imbalance_5m"])
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:launch_momentum:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="launch_momentum",
                direction="long",
                actionable_research_entry=not hard_veto,
                as_of_ts=as_of,
                slot=slot,
                venue=venue,
                entry_price_quote=px,
                stop_price_quote=round(px * 0.88, 12),
                target_price_quote=round(px * 1.28, 12),
                reward_risk_ratio=round(0.28 / 0.12, 2),
                signal_strength=round(strength, 4),
                rationale=(
                    f"5m return +{f['return_5m']*100:.1f}%, vol {f['volume_sol_5m']:.1f} SOL",
                    f"unique_buyers_5m={int(f['unique_buyers_5m'])}, ofi={f['order_flow_imbalance_5m']:.2f}",
                ),
                risk_veto=hard_veto,
            )
        )

    # 2. Launch Pullback Continuation
    if (
        f["return_15m"] >= 0.12
        and 0.28 <= f["retracement_ratio_15m"] <= 0.65
        and f["return_5m"] > 0.01
        and f["order_flow_imbalance_5m"] >= 0.10
    ):
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:launch_pullback_continuation:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="launch_pullback_continuation",
                direction="long",
                actionable_research_entry=not hard_veto,
                as_of_ts=as_of,
                slot=slot,
                venue=venue,
                entry_price_quote=px,
                stop_price_quote=round(px * 0.90, 12),
                target_price_quote=round(px * 1.24, 12),
                reward_risk_ratio=2.4,
                signal_strength=round(min(1.0, 0.55 + f["order_flow_imbalance_5m"] * 0.4), 4),
                rationale=(
                    f"15m impulse +{f['return_15m']*100:.1f}% with {f['retracement_ratio_15m']*100:.0f}% pullback",
                    f"5m reclaim +{f['return_5m']*100:.1f}% and positive buyer flow",
                ),
                risk_veto=hard_veto,
            )
        )

    # 3. Bonding-Curve Momentum
    if (
        token.lifecycle_state == TokenLifecycleState.CURVE_ACTIVE
        and 45.0 <= f["curve_progress_pct"] <= 92.0
        and f["order_flow_imbalance_5m"] >= 0.15
        and f["effective_liquidity_sol"] >= 15.0
    ):
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:bonding_curve_momentum:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="bonding_curve_momentum",
                direction="long",
                actionable_research_entry=not hard_veto,
                as_of_ts=as_of,
                slot=slot,
                venue="bonding_curve",
                entry_price_quote=px,
                stop_price_quote=round(px * 0.90, 12),
                target_price_quote=round(px * 1.22, 12),
                reward_risk_ratio=2.2,
                signal_strength=round(min(1.0, f["curve_progress_pct"] / 100.0), 4),
                rationale=(
                    f"Curve progress {f['curve_progress_pct']:.1f}% with {f['effective_liquidity_sol']:.1f} SOL effective virtual reserves",
                    f"Net buyer imbalance {f['order_flow_imbalance_5m']:.2f}",
                ),
                risk_veto=hard_veto,
            )
        )

    # 4. Post-Graduation Momentum
    if (
        token.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE
        and f["effective_liquidity_sol"] >= 25.0
        and f["return_5m"] >= 0.03
        and f["order_flow_imbalance_5m"] >= 0.10
    ):
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:post_graduation_momentum:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="post_graduation_momentum",
                direction="long",
                actionable_research_entry=not hard_veto,
                as_of_ts=as_of,
                slot=slot,
                venue="pumpswap",
                entry_price_quote=px,
                stop_price_quote=round(px * 0.91, 12),
                target_price_quote=round(px * 1.20, 12),
                reward_risk_ratio=round(0.20 / 0.09, 2),
                signal_strength=round(min(1.0, 0.5 + f["order_flow_imbalance_5m"] * 0.5), 4),
                rationale=(
                    f"Graduated PumpSwap pool active ({f['effective_liquidity_sol']:.1f} SOL effective quote reserves)",
                    f"Post-migration 5m return +{f['return_5m']*100:.1f}%",
                ),
                risk_veto=hard_veto,
            )
        )

    # 5. Liquidity-Sweep Reversal (Swing Failure Pattern on causal trade history)
    causal_trades = [t for t in trades if t.event_time <= as_of and t.price_quote > 0]
    if len(causal_trades) >= 6:
        prior = causal_trades[:-2]
        recent = causal_trades[-2:]
        swing_low = min(t.price_quote for t in prior)
        swept = min(t.price_quote for t in recent) < swing_low * 0.998
        reclaimed = causal_trades[-1].price_quote > swing_low
        if swept and reclaimed and f["order_flow_imbalance_5m"] >= 0.0:
            candidates.append(
                PumpStrategyCandidate(
                    candidate_id=f"{token.mint[:8]}:liquidity_sweep_reversal:{slot}",
                    mint=token.mint,
                    symbol=token.symbol,
                    strategy="liquidity_sweep_reversal",
                    direction="long",
                    actionable_research_entry=not hard_veto,
                    as_of_ts=as_of,
                    slot=slot,
                    venue=venue,
                    entry_price_quote=px,
                    stop_price_quote=round(min(t.price_quote for t in recent) * 0.98, 12),
                    target_price_quote=round(px * 1.18, 12),
                    reward_risk_ratio=2.1,
                    signal_strength=0.64,
                    rationale=(
                        f"Swept prior swing low {swing_low:.9f} and reclaimed at {px:.9f}",
                        "Adapted from ATLAS Swing Failure Pattern (SFP) detector",
                    ),
                    risk_veto=hard_veto,
                )
            )

    # 6. Whale-Flow Research
    if f["whale_net_flow_sol"] >= 5.0 and f["creator_holding_pct"] < 15.0:
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:whale_flow_research:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="whale_flow_research",
                direction="long",
                actionable_research_entry=not hard_veto,
                as_of_ts=as_of,
                slot=slot,
                venue=venue,
                entry_price_quote=px,
                stop_price_quote=round(px * 0.90, 12),
                target_price_quote=round(px * 1.22, 12),
                reward_risk_ratio=2.2,
                signal_strength=round(min(1.0, 0.45 + f["whale_net_flow_sol"] / 25.0), 4),
                rationale=(
                    f"Net whale inflow +{f['whale_net_flow_sol']:.2f} SOL with low creator holding ({f['creator_holding_pct']:.1f}%)",
                ),
                risk_veto=hard_veto,
            )
        )

    # 7. Momentum Exhaustion
    if (
        f["realized_vol_15m"] >= 0.05
        and f["order_flow_imbalance_5m"] <= -0.20
        and f["unique_sellers_5m"] > f["unique_buyers_5m"]
    ):
        candidates.append(
            PumpStrategyCandidate(
                candidate_id=f"{token.mint[:8]}:momentum_exhaustion:{slot}",
                mint=token.mint,
                symbol=token.symbol,
                strategy="momentum_exhaustion",
                direction="exit_or_avoid",
                actionable_research_entry=False,
                as_of_ts=as_of,
                slot=slot,
                venue=venue,
                entry_price_quote=px,
                stop_price_quote=px,
                target_price_quote=round(px * 0.80, 12),
                reward_risk_ratio=0.0,
                signal_strength=round(min(1.0, 0.5 + abs(f["order_flow_imbalance_5m"]) * 0.5), 4),
                rationale=(
                    f"Falling buyer participation (sellers={int(f['unique_sellers_5m'])} > buyers={int(f['unique_buyers_5m'])})",
                    f"Elevated 15m vol ({f['realized_vol_15m']:.3f}) with negative OFI ({f['order_flow_imbalance_5m']:.2f})",
                ),
                risk_veto=True,
            )
        )

    return candidates

