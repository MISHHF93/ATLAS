"""Token Safety Engine for Pump.fun & Solana tokens.

Evaluates verified on-chain facts and heuristic risk indicators separately.
Never guarantees that any token is safe, and never claims heuristic clusters prove malicious coordination.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..liquidity import LiquidityAndImpactProfile
from ..tokens import PumpTokenRecord, TokenLifecycleState, transition_lifecycle
from ..wallet_intelligence import CLUSTER_DISCLAIMER, WalletIntelligenceReport

SAFETY_DISCLAIMER = (
    "No token is guaranteed safe. Passing on-chain authority and sell-simulation checks "
    "does not eliminate market volatility, liquidity withdrawal, or smart-contract risk."
)

# Dangerous Token-2022 extensions that can restrict exit, confiscate balances, or levy arbitrary transfer taxes
RESTRICTED_TOKEN_EXTENSIONS = frozenset({
    "PermanentDelegate",
    "TransferHook",
    "TransferFeeConfig",
    "DefaultAccountStateFrozen",
    "CloseMintAuthority",
    "NonTransferable",
})


@dataclass(frozen=True)
class TokenSafetyReport:
    mint: str
    symbol: str
    safety_status: str  # "passed" | "caution" | "rejected"
    safe_guaranteed: bool  # Always False
    verified_on_chain_facts: dict[str, Any]
    heuristic_risk_scores: dict[str, Any]
    hard_reject_reasons: tuple[str, ...] = ()
    caution_flags: tuple[str, ...] = ()
    safety_disclaimer: str = SAFETY_DISCLAIMER
    cluster_disclaimer: str = CLUSTER_DISCLAIMER

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_token_safety(
    token: PumpTokenRecord,
    *,
    liquidity_profile: LiquidityAndImpactProfile,
    wallet_report: WalletIntelligenceReport,
    tx_failure_rate_recent: float = 0.0,
    max_creator_holding_pct: float = 20.0,
    max_top10_holder_pct: float = 55.0,
    max_heuristic_cluster_pct: float = 35.0,
    min_effective_liquidity_sol: float = 5.0,
    max_sell_impact_bps: float = 500.0,
    max_tx_failure_rate: float = 0.25,
    apply_lifecycle_rejection: bool = True,
) -> TokenSafetyReport:
    """Screen a token across verified on-chain facts and heuristic risk indicators."""
    bad_extensions = sorted(set(token.token_extensions) & RESTRICTED_TOKEN_EXTENSIONS)
    vf = wallet_report.verified_on_chain_facts
    hi = wallet_report.heuristic_indicators

    creator_pct = float(vf.get("creator_holding_pct", token.creator_holding_pct))
    top10_pct = float(vf.get("top10_holder_pct", token.top10_holder_pct))
    cluster_pct = float(hi.get("suspicious_cluster_pct", 0.0))
    abandon_rate = float(hi.get("creator_prior_early_dump_rate", 0.0))

    hard_reasons: list[str] = []
    caution_flags: list[str] = []

    # 1. Verified on-chain authority & extension checks
    if token.mint_authority_active:
        hard_reasons.append("mint_authority_active")
    if token.freeze_authority_active:
        hard_reasons.append("freeze_authority_active")
    if bad_extensions:
        hard_reasons.append(f"restricted_token_extensions:{','.join(bad_extensions)}")

    # 2. Sell simulation & exit liquidity checks
    if not liquidity_profile.sell_simulation_passed:
        hard_reasons.append("sell_simulation_failed")
    if liquidity_profile.effective_liquidity_sol < min_effective_liquidity_sol:
        hard_reasons.append(
            f"insufficient_exit_liquidity:{liquidity_profile.effective_liquidity_sol:.2f}<{min_effective_liquidity_sol:.2f}SOL"
        )
    if liquidity_profile.sell_price_impact_bps > max_sell_impact_bps:
        hard_reasons.append(
            f"excessive_sell_price_impact:{liquidity_profile.sell_price_impact_bps:.0f}>{max_sell_impact_bps:.0f}bps"
        )
    if tx_failure_rate_recent > max_tx_failure_rate:
        hard_reasons.append(f"high_tx_failure_rate:{tx_failure_rate_recent:.2f}>{max_tx_failure_rate:.2f}")

    # 3. Concentration checks (hard reject on extreme concentration, caution on elevated)
    if creator_pct > max_creator_holding_pct:
        hard_reasons.append(f"creator_concentration:{creator_pct:.1f}%>{max_creator_holding_pct:.1f}%")
    elif creator_pct > max_creator_holding_pct * 0.6:
        caution_flags.append(f"elevated_creator_holding:{creator_pct:.1f}%")

    if top10_pct > max_top10_holder_pct:
        hard_reasons.append(f"top10_holder_concentration:{top10_pct:.1f}%>{max_top10_holder_pct:.1f}%")
    elif top10_pct > max_top10_holder_pct * 0.75:
        caution_flags.append(f"elevated_top10_concentration:{top10_pct:.1f}%")

    # 4. Heuristic indicators (caution or configurable threshold)
    if cluster_pct > max_heuristic_cluster_pct:
        caution_flags.append(f"heuristic_wallet_cluster:{cluster_pct:.1f}%>{max_heuristic_cluster_pct:.1f}%")
    if abandon_rate >= 0.5 and int(vf.get("creator_prior_launches", 0)) >= 2:
        caution_flags.append(f"creator_prior_early_dump_rate:{abandon_rate:.2f}")

    # Compute heuristic composite risk score [0..100]
    composite_risk = min(
        100.0,
        round(
            (40.0 if hard_reasons else 0.0)
            + min(25.0, creator_pct * 0.8)
            + min(20.0, max(0.0, top10_pct - 20.0) * 0.5)
            + min(15.0, cluster_pct * 0.4)
            + min(15.0, (liquidity_profile.sell_price_impact_bps / max(1.0, max_sell_impact_bps)) * 10.0)
            + min(10.0, abandon_rate * 15.0),
            2,
        ),
    )

    if hard_reasons:
        status = "rejected"
        if apply_lifecycle_rejection and token.lifecycle_state not in (
            TokenLifecycleState.UNSUPPORTED,
            TokenLifecycleState.RISK_REJECTED,
        ):
            transition_lifecycle(
                token,
                TokenLifecycleState.RISK_REJECTED,
                slot=token.last_slot,
                event_time=token.last_updated_ts,
                reason="; ".join(hard_reasons),
            )
    elif caution_flags:
        status = "caution"
    else:
        status = "passed"

    verified_facts = {
        "mint": token.mint,
        "token_program": token.token_program,
        "mint_authority_active": token.mint_authority_active,
        "freeze_authority_active": token.freeze_authority_active,
        "token_extensions": list(token.token_extensions),
        "restricted_extensions_found": bad_extensions,
        "creator_holding_pct": creator_pct,
        "top10_holder_pct": top10_pct,
        "effective_liquidity_sol": liquidity_profile.effective_liquidity_sol,
        "sell_simulation_passed": liquidity_profile.sell_simulation_passed,
        "sell_price_impact_bps": liquidity_profile.sell_price_impact_bps,
        "round_trip_cost_bps": liquidity_profile.round_trip_cost_bps,
        "tx_failure_rate_recent": round(tx_failure_rate_recent, 4),
    }

    heuristic_scores = {
        "suspicious_cluster_pct": cluster_pct,
        "creator_prior_early_dump_rate": abandon_rate,
        "composite_risk_score": composite_risk,
        "cluster_coordination_proven": False,
    }

    return TokenSafetyReport(
        mint=token.mint,
        symbol=token.symbol,
        safety_status=status,
        safe_guaranteed=False,
        verified_on_chain_facts=verified_facts,
        heuristic_risk_scores=heuristic_scores,
        hard_reject_reasons=tuple(hard_reasons),
        caution_flags=tuple(caution_flags),
    )

