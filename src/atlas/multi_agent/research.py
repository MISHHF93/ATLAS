"""Research manager: turn preserved analyst disagreement into one advisory view."""

from __future__ import annotations

from .contracts import (
    AnalystReport,
    DebateResult,
    ReconciliationReport,
    ResearchDecision,
    ResearchOutcome,
    EvidenceSnapshot,
)


def _top(reports: list[AnalystReport], stance: str) -> str:
    candidates = [r for r in reports if r.status == "ok" and r.stance == stance]
    candidates.sort(key=lambda r: (r.confidence_label == "high", r.confidence_label == "medium"), reverse=True)
    return candidates[0].thesis if candidates else ""


def decide(
    reports: list[AnalystReport],
    reconciliation: ReconciliationReport,
    debate: DebateResult,
    snapshot: EvidenceSnapshot,
    *,
    directional_threshold: float = 2.0,
) -> ResearchDecision:
    ok = [r for r in reports if r.status == "ok"]
    evidence_ids = sorted({e.source_id for r in ok for e in r.supporting_evidence + r.contradicting_evidence})
    if not ok or reconciliation.insufficient_evidence:
        return ResearchDecision(
            outcome="INSUFFICIENT_EVIDENCE",
            thesis="No analyst produced usable, point-in-time evidence. The run abstains rather than inventing a case.",
            unresolved=reconciliation.missing_information[:15],
            confidence_label="unavailable",
            evidence_ids=evidence_ids,
            abstention_reason="insufficient_evidence",
        )

    net = debate.net_score
    contradictions = len(reconciliation.contradictions)
    uncertain = bool(reconciliation.missing_information or reconciliation.prompt_injection_flags)
    outcome: ResearchOutcome
    if abs(net) >= directional_threshold:
        outcome = "BULLISH_CASE_STRONGER" if net > 0 else "BEARISH_CASE_STRONGER"
    elif abs(net) >= directional_threshold / 3:
        outcome = "BULLISH_CASE_STRONGER" if net > 0 else "BEARISH_CASE_STRONGER"
    else:
        outcome = "MIXED_EVIDENCE"

    if contradictions and abs(net) < directional_threshold:
        outcome = "MIXED_EVIDENCE"

    usable_high = sum(1 for r in ok if r.confidence_label == "high")
    usable_medium = sum(1 for r in ok if r.confidence_label == "medium")
    if contradictions or uncertain or outcome == "MIXED_EVIDENCE":
        confidence = "low"
    elif usable_high:
        confidence = "medium"
    elif usable_medium:
        confidence = "low"
    else:
        confidence = "low"

    thesis = (
        f"Net debated evidence {net:+.2f} (bull {debate.bull_score:.2f} vs bear {debate.bear_score:.2f}); "
        f"{len(ok)} usable analyst reports; {contradictions} unresolved contradiction(s). "
        f"Bull case: {debate.bull_case_summary or 'none'}. "
        f"Bear case: {debate.bear_case_summary or 'none'}."
    )
    unresolved = list(dict.fromkeys(debate.unresolved + reconciliation.missing_information))[:20]
    return ResearchDecision(
        outcome=outcome,
        thesis=thesis[:4000],
        strongest_bull=_top(reports, "bullish")[:2000],
        strongest_bear=_top(reports, "bearish")[:2000],
        unresolved=unresolved,
        confidence_label=confidence,  # type: ignore[arg-type]
        evidence_ids=evidence_ids,
        abstention_reason=None,
    )


__all__ = ["decide"]
