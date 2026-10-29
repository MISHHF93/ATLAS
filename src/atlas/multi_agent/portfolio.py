"""Portfolio review: deterministic account-level constraints before the final gate."""

from __future__ import annotations

from .contracts import PortfolioContext, PortfolioReview, RiskReview, TradeProposal


def _equity(context: PortfolioContext) -> float:
    positions = sum(
        (p.notional_usd if p.notional_usd is not None else p.quantity * p.average_price)
        for p in context.positions
    )
    return context.cash + positions


def review(proposal: TradeProposal, context: PortfolioContext | None,
           risk_reviews: list[RiskReview] | None = None) -> PortfolioReview:
    if proposal.action not in ("BUY_CANDIDATE", "SELL_CANDIDATE") or proposal.side is None:
        return PortfolioReview(
            outcome="ABSTAIN",
            reasons=["no actionable candidate was proposed"],
            constraints=[],
            portfolio_context_available=context is not None,
            evidence_ids=proposal.supporting_evidence_ids,
        )

    reviews = list(risk_reviews or [])
    objectors = [r for r in reviews if r.verdict == "objects"]
    if len(objectors) >= 2:
        return PortfolioReview(
            outcome="REJECT_RESEARCH_PROPOSAL",
            reasons=[f"{r.perspective} objects: {'; '.join(r.concerns[:3])}" for r in objectors],
            constraints=["multiple independent risk perspectives objected"],
            portfolio_context_available=context is not None,
            evidence_ids=proposal.supporting_evidence_ids,
        )
    if any(r.severity == "critical" for r in reviews):
        return PortfolioReview(
            outcome="REQUEST_MORE_EVIDENCE",
            reasons=["a critical risk concern must be resolved before a deterministic preview"],
            constraints=["critical risk concern"],
            portfolio_context_available=context is not None,
            evidence_ids=proposal.supporting_evidence_ids,
        )

    if context is None:
        return PortfolioReview(
            outcome="RECOMMEND_FOR_RISK_REVIEW",
            reasons=["portfolio context was not supplied; account limits could not be checked here"],
            constraints=["deterministic control plane enforces account limits at preview time"]
            + [f"{r.perspective} objected; preserved as a dissent" for r in objectors],
            portfolio_context_available=False,
            evidence_ids=proposal.supporting_evidence_ids,
        )

    equity = _equity(context)
    notional = float(proposal.notional_usd or 0.0)
    reasons: list[str] = []
    constraints = [
        f"max_position_pct={context.max_position_pct:.2%}",
        f"max_portfolio_risk_pct={context.max_portfolio_risk_pct:.2%}",
    ]
    constraints.extend(f"{r.perspective} objected; preserved as a dissent" for r in objectors)
    if equity <= 0:
        reasons.append("portfolio equity is zero or negative")
    else:
        max_notional = equity * context.max_position_pct
        if notional > max_notional:
            reasons.append(f"notional {notional:.2f} exceeds {context.max_position_pct:.2%} of equity ({max_notional:.2f})")
        same = sum(
            (p.notional_usd if p.notional_usd is not None else p.quantity * p.average_price)
            for p in context.positions
            if p.instrument_id.upper() == proposal.instrument_id.upper()
        )
        if same + notional > max_notional:
            reasons.append(f"existing {proposal.instrument_id} exposure {same:.2f} plus candidate exceeds position cap")
        if context.daily_loss_used_usd > equity * context.max_portfolio_risk_pct:
            reasons.append("daily loss budget is already exhausted")
    if proposal.stop_distance_bps is None:
        reasons.append("candidate has no bounded stop, so portfolio risk cannot be bounded")

    if reasons:
        return PortfolioReview(
            outcome="REJECT_RESEARCH_PROPOSAL",
            reasons=reasons,
            constraints=constraints,
            portfolio_context_available=True,
            evidence_ids=proposal.supporting_evidence_ids,
        )
    return PortfolioReview(
        outcome="RECOMMEND_FOR_RISK_REVIEW",
        reasons=["candidate fits the supplied position and daily-loss limits"],
        constraints=constraints,
        portfolio_context_available=True,
        evidence_ids=proposal.supporting_evidence_ids,
    )


__all__ = ["review"]
