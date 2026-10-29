"""Multi-perspective risk reviewers.

Aggressive, conservative and neutral reviewers see the same frozen evidence and
candidate, then emit separate verdicts.  They are advisory.  Even a unanimous
"supports" verdict cannot authorize an order.
"""

from __future__ import annotations

from .contracts import (
    EvidenceSnapshot,
    PortfolioContext,
    ReconciliationReport,
    ResearchDecision,
    RiskReview,
    TradeProposal,
)


def _common_concerns(
    proposal: TradeProposal,
    reconciliation: ReconciliationReport,
    snapshot: EvidenceSnapshot,
) -> list[str]:
    concerns = list(proposal.rejection_reasons)
    if reconciliation.contradictions:
        concerns.extend(f"unresolved: {c.detail}" for c in reconciliation.contradictions[:5])
    if reconciliation.prompt_injection_flags:
        concerns.append("untrusted text contains instruction-like patterns")
    if reconciliation.missing_information:
        concerns.append(f"missing evidence: {', '.join(reconciliation.missing_information[:8])}")
    if reconciliation.conflicting_timestamps:
        concerns.append("source timestamps or immutable versions conflict")
    if proposal.reward_risk is not None and proposal.reward_risk < 1.5:
        concerns.append(f"reward:risk {proposal.reward_risk:.2f} is below 1.5")
    if proposal.stop_distance_bps is None:
        concerns.append("no observed stop distance is available")
    elif proposal.stop_distance_bps <= 0:
        concerns.append("stop distance is not positive")
    if snapshot.session and snapshot.session.get("is_tradable") is False:
        concerns.append("venue is not tradable at as_of")
    if snapshot.freshness.get("stale"):
        concerns.append("market data is stale at as_of")
    liq = snapshot.liquidity or {}
    try:
        if float(liq.get("relative_volume_20_vs_100")) < 0.7:
            concerns.append("relative volume is below 0.7x its baseline")
    except (TypeError, ValueError):
        pass
    return list(dict.fromkeys(concerns))


def review(
    proposal: TradeProposal,
    decision: ResearchDecision,
    reconciliation: ReconciliationReport,
    snapshot: EvidenceSnapshot,
    portfolio: PortfolioContext | None,
) -> list[RiskReview]:
    concerns = _common_concerns(proposal, reconciliation, snapshot)
    favorable: list[str] = []
    if decision.confidence_label == "medium":
        favorable.append("research manager confidence is medium")
    if proposal.reward_risk is not None and proposal.reward_risk >= 2.0:
        favorable.append(f"reward:risk {proposal.reward_risk:.2f}")
    if decision.outcome in ("BULLISH_CASE_STRONGER", "BEARISH_CASE_STRONGER"):
        favorable.append(f"directional research view: {decision.outcome}")
    if portfolio is not None:
        favorable.append("portfolio context was supplied for this review")

    candidate = proposal.action in ("BUY_CANDIDATE", "SELL_CANDIDATE")
    severe = any(
        phrase in c
        for c in concerns
        for phrase in ("no observed stop", "not tradable", "instruction-like", "stop distance is not positive")
    )
    high = severe or bool(reconciliation.contradictions) or decision.confidence_label == "low"
    low_confidence = decision.confidence_label in ("low", "unavailable")

    aggressive_verdict = "supports_candidate" if candidate and not severe and not low_confidence else (
        "objects" if severe else "concerns_raised"
    )
    conservative_verdict = "objects" if candidate and (severe or high or concerns) else (
        "concerns_raised" if concerns else "supports_candidate"
    )
    if not candidate:
        neutral_verdict = "concerns_raised"
    elif conservative_verdict == "objects" or aggressive_verdict == "objects":
        neutral_verdict = "concerns_raised"
    else:
        neutral_verdict = "supports_candidate"

    ids = list(decision.evidence_ids)
    return [
        RiskReview(
            perspective="aggressive",
            verdict=aggressive_verdict,  # type: ignore[arg-type]
            concerns=concerns if aggressive_verdict != "supports_candidate" else concerns[:2],
            favorable_factors=favorable,
            evidence_ids=ids,
            severity="high" if severe else "medium" if concerns else "low",
        ),
        RiskReview(
            perspective="conservative",
            verdict=conservative_verdict,  # type: ignore[arg-type]
            concerns=concerns,
            favorable_factors=favorable[:2],
            evidence_ids=ids,
            severity="critical" if severe else "high" if high else "medium" if concerns else "low",
        ),
        RiskReview(
            perspective="neutral",
            verdict=neutral_verdict,  # type: ignore[arg-type]
            concerns=concerns[:6],
            favorable_factors=favorable,
            evidence_ids=ids,
            severity="high" if severe else "medium" if concerns else "low",
        ),
    ]


__all__ = ["review"]
