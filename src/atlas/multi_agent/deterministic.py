"""Final deterministic gate.

This is a dry-run only.  It builds an ``ActionableOrderRequest`` and calls
``ActionableControlPlaneEngine.preview_order``, the exact rule path used by
``submit_order``.  It never calls ``submit_order`` and never books a position.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import DeterministicDecision, PortfolioReview, ResearchDecision, TradeProposal


def gate(
    proposal: TradeProposal,
    research: ResearchDecision,
    portfolio_review: PortfolioReview,
    *,
    track: str,
    evaluation_time: datetime,
    control_engine: object | None = None,
    data_age_ms: float = 0.0,
) -> DeterministicDecision:
    if proposal.action not in ("BUY_CANDIDATE", "SELL_CANDIDATE") or proposal.side is None:
        return DeterministicDecision(
            outcome="NOT_APPLICABLE",
            authorized=False,
            notes=["research proposed no order candidate; nothing was sent to the control plane"],
        )
    if research.outcome in ("INSUFFICIENT_EVIDENCE", "ABSTAIN"):
        return DeterministicDecision(
            outcome="NOT_APPLICABLE",
            authorized=False,
            notes=["research abstained; no order preview was requested"],
        )
    if portfolio_review.outcome != "RECOMMEND_FOR_RISK_REVIEW":
        return DeterministicDecision(
            outcome="NOT_APPLICABLE",
            authorized=False,
            notes=[f"portfolio review outcome was {portfolio_review.outcome}; no order preview was requested"],
        )
    if proposal.stop_distance_bps is None or proposal.stop_distance_bps <= 0:
        return DeterministicDecision(
            outcome="REJECTED",
            authorized=False,
            violations=["missing_or_non_positive_stop_distance"],
            notes=["a bounded stop is required before the control plane is consulted"],
        )
    if proposal.notional_usd is None or proposal.notional_usd <= 0:
        return DeterministicDecision(
            outcome="REJECTED",
            authorized=False,
            violations=["missing_or_non_positive_notional"],
        )

    if evaluation_time.tzinfo is None:
        evaluation_time = evaluation_time.replace(tzinfo=timezone.utc)
    try:
        from atlas.control import ActionableControlPlaneEngine, ActionableOrderRequest

        engine = control_engine or ActionableControlPlaneEngine()
        request = ActionableOrderRequest(
            track=track,  # type: ignore[arg-type]
            instrument_id=proposal.instrument_id,
            side=proposal.side,
            notional_usd=proposal.notional_usd,
            stop_kind="structure",
            stop_distance_bps=proposal.stop_distance_bps,
            holding_horizon_seconds=14400 if proposal.max_holding_horizon == "intraday" else 86400,
            data_age_ms=max(0.0, float(data_age_ms)),
        )
        report = engine.preview_order(request, now=evaluation_time.astimezone(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        return DeterministicDecision(
            outcome="REJECTED",
            authorized=False,
            violations=[f"control_plane_error:{type(exc).__name__}"],
            notes=["the deterministic control plane could not be consulted; default deny"],
        )

    passed = bool(getattr(report, "compliance_passed", False))
    violations = list(getattr(report, "violations", ()) or ())
    return DeterministicDecision(
        outcome="PAPER_REVIEW_AUTHORIZED" if passed else "REJECTED",
        authorized=passed,
        violations=violations,
        submitted=False,
        notes=[
            "preview_order only; no order was submitted",
            "LLM/research output cannot override the control plane",
            "VPIN toxicity and live book depth were unavailable; the control plane received the request defaults",
            f"track={track}; evaluation_time={evaluation_time.isoformat()}",
        ],
    )


__all__ = ["gate"]
