"""Cross-analyst reconciliation: surface agreement, disagreement and gaps.

Reconciliation never averages opinions into a fake consensus.  It records the
conflicts and missing evidence so that the debate, research manager and risk
reviewers can address them explicitly.
"""

from __future__ import annotations

from collections import defaultdict

from .contracts import AnalystReport, EvidenceSnapshot, ReconciliationConflict, ReconciliationReport


def _evidence_ids(report: AnalystReport) -> list[str]:
    return [e.source_id for e in report.supporting_evidence + report.contradicting_evidence]


def reconcile(reports: list[AnalystReport], snapshot: EvidenceSnapshot) -> ReconciliationReport:
    ok = [r for r in reports if r.status == "ok"]
    unavailable = [r for r in reports if r.status in ("unavailable", "error")]
    not_applicable = [r for r in reports if r.status == "not_applicable"]

    agreements: list[str] = []
    contradictions: list[ReconciliationConflict] = []
    missing: list[str] = []
    conflicting_timestamps: list[str] = []
    data_quality: list[str] = []
    horizons: list[str] = []
    assumption_differences: list[str] = []
    strategy_conflicts: list[str] = []

    by_stance: dict[str, list[str]] = defaultdict(list)
    for r in ok:
        by_stance[r.stance].append(r.analyst_type)
        if r.horizon and r.horizon != "unspecified":
            horizons.append(f"{r.analyst_type}:{r.horizon}")
        missing.extend(r.missing_data)
    for stance in ("bullish", "bearish", "neutral", "mixed"):
        if len(by_stance.get(stance, [])) >= 2:
            agreements.append(f"{stance}: {', '.join(sorted(by_stance[stance]))}")

    by_horizon: dict[str, list[AnalystReport]] = defaultdict(list)
    for r in ok:
        by_horizon[r.horizon].append(r)
    for horizon, group in by_horizon.items():
        stances = {r.stance for r in group}
        if "bullish" in stances and "bearish" in stances:
            bull = [r.analyst_type for r in group if r.stance == "bullish"]
            bear = [r.analyst_type for r in group if r.stance == "bearish"]
            contradictions.append(ReconciliationConflict(
                topic=f"stance_conflict:{horizon}",
                detail=f"{', '.join(bull)} bullish while {', '.join(bear)} bearish on the same horizon",
                analyst_types=bull + bear,
                evidence_ids=sorted({e for r in group if r.stance in ("bullish", "bearish") for e in _evidence_ids(r)}),
            ))

    tech = next((r for r in ok if r.analyst_type == "technical"), None)
    strat = next((r for r in ok if r.analyst_type == "strategy_research"), None)
    if tech and strat and tech.stance != strat.stance and {tech.stance, strat.stance} & {"bullish", "bearish"}:
        detail = f"technical is {tech.stance} while strategy research is {strat.stance}"
        strategy_conflicts.append(detail)
        contradictions.append(ReconciliationConflict(
            topic="technical_vs_strategy",
            detail=detail,
            analyst_types=["technical", "strategy_research"],
            evidence_ids=sorted(set(_evidence_ids(tech) + _evidence_ids(strat))),
        ))

    seen_sources: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for r in reports:
        for e in r.supporting_evidence + r.contradicting_evidence:
            seen_sources[e.source_type].add((e.source_id, e.source_hash or ""))
            if e.available_at > snapshot.as_of:
                conflicting_timestamps.append(f"{e.source_id} available_at is after as_of")
    for source_type, values in seen_sources.items():
        ids = {sid for sid, _ in values}
        hashes = {h for _, h in values if h}
        if len(ids) > 1 and len(hashes) > 1 and ":" in next(iter(ids)):
            conflicting_timestamps.append(f"{source_type}: multiple immutable snapshots observed in this run")

    if snapshot.prompt_injection_flags:
        data_quality.append("prompt_injection_patterns_in_untrusted_text")
    for r in unavailable:
        data_quality.append(f"{r.analyst_type} {r.status}: {r.thesis[:180]}")
    if snapshot.freshness.get("stale"):
        data_quality.append("market_data_stale_at_as_of")
    if snapshot.missing_data:
        missing.extend(snapshot.missing_data)

    for r in reports:
        for assumption in r.assumptions:
            assumption_differences.append(f"{r.analyst_type}: {assumption}")

    insufficient = not ok or all(r.stance == "insufficient_evidence" for r in ok)
    notes = [
        f"{len(ok)} of {len(reports)} analysts returned usable output.",
        f"{len(not_applicable)} not applicable and {len(unavailable)} unavailable.",
        "Disagreement is preserved; no majority vote is used.",
    ]
    if not ok:
        missing.append("no_usable_analyst_reports")

    return ReconciliationReport(
        agreements=agreements,
        contradictions=contradictions,
        missing_information=sorted(set(missing)),
        conflicting_timestamps=sorted(set(conflicting_timestamps)),
        data_quality_issues=sorted(set(data_quality)),
        horizon_differences=sorted(set(horizons)),
        assumption_differences=sorted(set(assumption_differences)),
        strategy_interpretation_conflicts=strategy_conflicts,
        prompt_injection_flags=list(snapshot.prompt_injection_flags),
        insufficient_evidence=insufficient,
        notes=notes,
    )


__all__ = ["reconcile"]
