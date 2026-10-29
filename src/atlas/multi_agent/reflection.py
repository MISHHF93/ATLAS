"""Post-hoc reflection.  Reflections never mutate the original decision."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .contracts import ReflectionRecord, ResearchRunState


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_reflection(
    state: ResearchRunState,
    *,
    outcome_price: float,
    outcome_as_of: datetime | None = None,
    benchmark_return: float | None = None,
    now: datetime | None = None,
) -> ReflectionRecord:
    if state.status != "completed":
        raise ValueError("run_must_be_completed_before_reflection")
    if outcome_price <= 0:
        raise ValueError("outcome_price_must_be_positive")
    if state.snapshot is None or state.research_decision is None:
        raise ValueError("run_has_no_completed_research_state")
    when = _utc(outcome_as_of or now)
    if when < state.as_of:
        raise ValueError("outcome_as_of_before_run_as_of")

    outcome = state.research_decision.outcome
    predicted = "up" if outcome == "BULLISH_CASE_STRONGER" else "down" if outcome == "BEARISH_CASE_STRONGER" else "none"
    reference_price = None
    if state.trade_proposal and state.trade_proposal.entry_price:
        reference_price = state.trade_proposal.entry_price
    if reference_price is None:
        reference_price = state.snapshot.last_close
    if reference_price is None or reference_price <= 0:
        raise ValueError("no_observed_reference_price_for_reflection")

    if state.trade_proposal and state.trade_proposal.side == "sell":
        realized = (reference_price - outcome_price) / reference_price
    else:
        realized = (outcome_price - reference_price) / reference_price

    directional_correct = None
    if predicted == "up":
        directional_correct = realized > 0
    elif predicted == "down":
        directional_correct = realized < 0

    if predicted == "none":
        abstention = "good_abstention" if abs(realized) < 0.01 else "missed_opportunity"
    else:
        abstention = "not_applicable"

    unsupported: list[str] = []
    for report in state.analyst_reports:
        if report.status == "ok" and report.confidence_label in ("low", "unavailable"):
            unsupported.append(f"{report.analyst_type} had low-confidence evidence")
    if state.reconciliation is not None and state.reconciliation.contradictions:
        unsupported.extend(f"unresolved contradiction: {c.detail}" for c in state.reconciliation.contradictions[:5])

    lessons: list[str] = []
    if directional_correct is True:
        lessons.append("The directional research view was consistent with the observed move; this is one observation, not calibration.")
    elif directional_correct is False:
        lessons.append("The directional research view was inconsistent with the observed move; review the thesis and evidence gaps.")
    if abstention == "missed_opportunity":
        lessons.append("Abstention missed a material move; check whether missing evidence was recoverable.")
    if state.deterministic_decision and state.deterministic_decision.outcome == "PAPER_REVIEW_AUTHORIZED":
        lessons.append("The deterministic control plane authorized a paper review; execution outcome is still out of scope.")

    return ReflectionRecord(
        reflection_id=f"refl-{uuid.uuid4().hex[:12]}",
        run_id=state.run_id,
        instrument_id=state.instrument_id,
        as_of=state.as_of,
        recommendation=outcome,  # type: ignore[arg-type]
        proposal_action=state.trade_proposal.action if state.trade_proposal else None,
        outcome_price=float(outcome_price),
        outcome_as_of=when,
        realized_return=realized,
        benchmark_return=benchmark_return,
        predicted_direction=predicted,  # type: ignore[arg-type]
        directional_correct=directional_correct,
        abstention_quality=abstention,  # type: ignore[arg-type]
        unsupported_assumptions=list(dict.fromkeys(unsupported))[:20],
        lessons=lessons,
        original_decision_hash=state.original_decision_hash,
        created_at=_utc(now),
    )


__all__ = ["build_reflection"]
