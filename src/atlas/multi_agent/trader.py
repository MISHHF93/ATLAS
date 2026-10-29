"""Trader node: translate a research view into a reviewable candidate.

The trader may propose an action and observed levels.  It never sizes or
submits an order; ``notional_usd`` is the caller's review notional and the
deterministic control plane remains the sole authority.
"""

from __future__ import annotations

from .contracts import EvidenceSnapshot, ResearchDecision, TradeProposal


def _levels(snapshot: EvidenceSnapshot, side: str) -> dict[str, float | str | None]:
    levels = snapshot.trade_levels or {}
    tech = snapshot.technicals or {}
    atr = tech.get("atr14")
    close = tech.get("close") or snapshot.last_close
    expected = "long" if side == "buy" else "short"
    if levels.get("side") == expected and levels.get("entry") is not None and levels.get("stop") is not None:
        return {
            "entry": float(levels["entry"]),
            "stop": float(levels["stop"]),
            "target": float(levels["target"]) if levels.get("target") is not None else None,
            "entry_ref": levels.get("entry_ref"),
            "stop_ref": levels.get("stop_ref"),
            "target_ref": levels.get("target_ref"),
        }
    if close is None or not atr:
        return {"entry": close, "stop": None, "target": None, "entry_ref": "last_close", "stop_ref": None, "target_ref": None}
    entry = float(close)
    risk = float(atr)
    if side == "buy":
        stop, target = entry - risk, entry + 2.0 * risk
    else:
        stop, target = entry + risk, entry - 2.0 * risk
    return {"entry": entry, "stop": stop, "target": target, "entry_ref": "last_close",
            "stop_ref": "1x ATR14 fallback", "target_ref": "2R fallback"}


def propose(
    decision: ResearchDecision,
    snapshot: EvidenceSnapshot,
    *,
    run_id: str,
    notional_usd: float,
    strategy_id: str | None = None,
) -> TradeProposal:
    outcome = decision.outcome
    if outcome in ("INSUFFICIENT_EVIDENCE", "ABSTAIN"):
        return TradeProposal(
            run_id=run_id,
            instrument_id=snapshot.instrument_id,
            action="ABSTAIN" if outcome == "ABSTAIN" else "HOLD",
            supporting_evidence_ids=decision.evidence_ids,
            rejection_reasons=[decision.abstention_reason or "research did not establish a usable case"],
        )
    if outcome == "MIXED_EVIDENCE":
        return TradeProposal(
            run_id=run_id,
            instrument_id=snapshot.instrument_id,
            action="HOLD",
            supporting_evidence_ids=decision.evidence_ids,
            rejection_reasons=["analyst evidence is mixed; no directional candidate is asserted"],
        )

    side = "buy" if outcome == "BULLISH_CASE_STRONGER" else "sell"
    lv = _levels(snapshot, side)
    entry = lv.get("entry")
    stop = lv.get("stop")
    target = lv.get("target")
    stop_bps = None
    rr = None
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and entry:
        stop_bps = abs(float(entry) - float(stop)) / float(entry) * 1e4
        if isinstance(target, (int, float)):
            risk = abs(float(entry) - float(stop))
            rr = abs(float(target) - float(entry)) / risk if risk else None

    missing_levels = []
    if not isinstance(stop, (int, float)):
        missing_levels.append("stop_reference_unavailable")
    if not isinstance(target, (int, float)):
        missing_levels.append("target_reference_unavailable")
    if snapshot.session and snapshot.session.get("is_tradable") is False:
        missing_levels.append("venue_not_tradable_at_as_of")

    return TradeProposal(
        run_id=run_id,
        instrument_id=snapshot.instrument_id,
        action="BUY_CANDIDATE" if side == "buy" else "SELL_CANDIDATE",
        side=side,  # type: ignore[arg-type]
        strategy_id=strategy_id,
        entry_condition=str(lv.get("entry_ref") or "observed level"),
        stop_reference=str(lv.get("stop_ref") or "unavailable"),
        target_reference=str(lv.get("target_ref") or "unavailable"),
        supporting_evidence_ids=decision.evidence_ids,
        rejection_reasons=missing_levels,
        notional_usd=notional_usd,
        stop_distance_bps=stop_bps,
        entry_price=float(entry) if isinstance(entry, (int, float)) else None,
        stop_price=float(stop) if isinstance(stop, (int, float)) else None,
        target_price=float(target) if isinstance(target, (int, float)) else None,
        reward_risk=rr,
        max_holding_horizon="intraday" if snapshot.timeframe in ("1m", "5m", "15m") else "swing",
        proposed_sizing_method="deterministic control plane only; research does not size orders",
    )


__all__ = ["propose"]
