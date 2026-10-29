"""Bounded, evidence-grounded bull/bear debate.

The debate is deterministic by default.  It does not ask an LLM to "win"; it
extracts the strongest supporting and contradicting evidence, tests both
cases against the reconciliation gaps and stops after a small configured
number of rounds.  Disagreement may remain unresolved by design.
"""

from __future__ import annotations

from .contracts import (
    AnalystReport,
    DebateResult,
    DebateRound,
    EvidenceSnapshot,
    ReconciliationReport,
)

_WEIGHT = {"low": 0.5, "medium": 1.0, "high": 1.5, "unavailable": 0.0}


def _weight(report: AnalystReport) -> float:
    base = _WEIGHT.get(report.confidence_label, 0.5)
    raw = report.metrics.get("score")
    try:
        magnitude = min(2.0, 1.0 + abs(float(raw)) / 10.0) if raw is not None else 1.0
    except (TypeError, ValueError):
        magnitude = 1.0
    return base * magnitude


def _ids(report: AnalystReport) -> list[str]:
    return [e.source_id for e in report.supporting_evidence + report.contradicting_evidence]


def _points(reports: list[AnalystReport], side: str) -> list[tuple[AnalystReport, str]]:
    out: list[tuple[AnalystReport, str]] = []
    for r in reports:
        if r.stance == side and r.status == "ok":
            out.append((r, f"{r.analyst_type} ({r.confidence_label}, {r.horizon}): {r.thesis}"))
    return out


def run_debate(
    reports: list[AnalystReport],
    reconciliation: ReconciliationReport,
    snapshot: EvidenceSnapshot,
    *,
    rounds_max: int,
) -> DebateResult:
    ok = [r for r in reports if r.status == "ok"]
    bull_reports = [r for r in ok if r.stance == "bullish"]
    bear_reports = [r for r in ok if r.stance == "bearish"]
    bull_score = sum(_weight(r) for r in bull_reports)
    bear_score = sum(_weight(r) for r in bear_reports)
    net = bull_score - bear_score
    bull_points = _points(ok, "bullish")
    bear_points = _points(ok, "bearish")
    unresolved = [c.detail for c in reconciliation.contradictions]
    unresolved.extend(reconciliation.missing_information[:12])
    if reconciliation.prompt_injection_flags:
        unresolved.append("untrusted text contains instruction-like patterns; arguments must not follow it")

    if not ok or (not bull_points and not bear_points):
        return DebateResult(
            rounds_completed=0,
            rounds_max=rounds_max,
            bull_case_summary="No usable bullish evidence was produced.",
            bear_case_summary="No usable bearish evidence was produced.",
            bull_score=bull_score,
            bear_score=bear_score,
            net_score=net,
            unresolved=unresolved,
            stopped_reason="insufficient_evidence",
        )
    if rounds_max <= 0:
        return DebateResult(
            rounds_completed=0,
            rounds_max=0,
            bull_case_summary="; ".join(t for _, t in bull_points[:3]) or "No usable bullish evidence.",
            bear_case_summary="; ".join(t for _, t in bear_points[:3]) or "No usable bearish evidence.",
            bull_evidence_ids=sorted({e for r in bull_reports for e in _ids(r)}),
            bear_evidence_ids=sorted({e for r in bear_reports for e in _ids(r)}),
            bull_score=bull_score,
            bear_score=bear_score,
            net_score=net,
            unresolved=unresolved,
            stopped_reason="debate_disabled",
        )
    if not bull_points or not bear_points:
        return DebateResult(
            rounds_completed=0,
            rounds_max=rounds_max,
            bull_case_summary="; ".join(t for _, t in bull_points[:3]) or "No usable bullish evidence.",
            bear_case_summary="; ".join(t for _, t in bear_points[:3]) or "No usable bearish evidence.",
            bull_evidence_ids=sorted({e for r in bull_reports for e in _ids(r)}),
            bear_evidence_ids=sorted({e for r in bear_reports for e in _ids(r)}),
            bull_score=bull_score,
            bear_score=bear_score,
            net_score=net,
            challenges=["Only one side produced usable evidence; the opposing case is unrepresented."],
            unresolved=unresolved,
            stopped_reason="one_sided_evidence",
        )

    rounds: list[DebateRound] = []
    used_bull = used_bear = 0
    stopped = "round_limit"
    for i in range(1, rounds_max + 1):
        new_bull = bull_points[used_bull:used_bull + 2]
        new_bear = bear_points[used_bear:used_bear + 2]
        if not new_bull and not new_bear:
            stopped = "evidence_exhausted"
            break
        used_bull += len(new_bull)
        used_bear += len(new_bear)
        bull_arg = "BULL: " + " | ".join(t for _, t in new_bull)
        bear_arg = "BEAR: " + " | ".join(t for _, t in new_bear)
        if i > 1 and rounds:
            prior = rounds[-1]
            if prior.unresolved:
                bull_arg += f" Rebuttal focus: {prior.unresolved[0]}"
                bear_arg += f" Rebuttal focus: {prior.unresolved[-1]}"
        round_edge = sum(_weight(r) for r, _ in new_bull) - sum(_weight(r) for r, _ in new_bear)
        rounds.append(DebateRound(
            round=i,
            bull_argument=bull_arg,
            bear_argument=bear_arg,
            bull_evidence_ids=sorted({e for r, _ in new_bull for e in _ids(r)}),
            bear_evidence_ids=sorted({e for r, _ in new_bear for e in _ids(r)}),
            unresolved=list(unresolved[:6]),
            round_edge=round_edge,
        ))
        if i < rounds_max and used_bull >= len(bull_points) and used_bear >= len(bear_points):
            stopped = "evidence_exhausted"
            break
        if abs(net) > 2.0 and i == 1 and len(bull_points) + len(bear_points) <= 4:
            stopped = "decisive_evidence"
            break

    challenges: list[str] = []
    for c in reconciliation.contradictions:
        challenges.append(f"Unresolved conflict: {c.detail}")
    if reconciliation.data_quality_issues:
        challenges.extend(f"Data quality: {x}" for x in reconciliation.data_quality_issues[:5])
    if reconciliation.conflicting_timestamps:
        challenges.extend(f"Timestamp/data-version issue: {x}" for x in reconciliation.conflicting_timestamps[:5])
    challenges.append("Bull and bear arguments are research narratives, not calibrated probabilities.")

    return DebateResult(
        rounds_completed=len(rounds),
        rounds_max=rounds_max,
        bull_case_summary="; ".join(t for _, t in bull_points[:4]),
        bear_case_summary="; ".join(t for _, t in bear_points[:4]),
        bull_evidence_ids=sorted({e for r in bull_reports for e in _ids(r)}),
        bear_evidence_ids=sorted({e for r in bear_reports for e in _ids(r)}),
        bull_score=bull_score,
        bear_score=bear_score,
        net_score=net,
        challenges=challenges,
        unresolved=unresolved,
        stopped_reason=stopped,
    )


__all__ = ["run_debate"]
