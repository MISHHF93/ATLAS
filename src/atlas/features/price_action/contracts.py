"""Shared strategy-candidate contract (unified schema), setup-type enum, NO_TRADE reasons and conflict resolution.

Reuses the existing ``Candidate`` (detectors.py) as the detector-level record; ``UnifiedCandidate`` is the
cross-family view that downstream ML / risk consume. Neither carries execution permission: only the deterministic
control plane (``ActionableControlPlaneEngine``) can authorize, reject or size an order.
Detectors exist only for the types marked ``implemented`` in ``SETUP_TYPES``; the rest are reserved names.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

from atlas.features.price_action.detectors import Candidate


class SetupType(str, Enum):
    OPENING_BOX_BREAKOUT = "OPENING_BOX_BREAKOUT"
    OPENING_BOX_RETEST = "OPENING_BOX_RETEST"
    BREAKOUT_BOX_RETEST = "BREAKOUT_BOX_RETEST"
    ANCHOR_BOX_REVERSAL = "ANCHOR_BOX_REVERSAL"
    EVENT_BOX_BREAKOUT = "EVENT_BOX_BREAKOUT"
    EVENT_BOX_REVERSAL = "EVENT_BOX_REVERSAL"
    SNAPBACK_CONTINUATION_LONG = "SNAPBACK_CONTINUATION_LONG"
    SNAPBACK_CONTINUATION_SHORT = "SNAPBACK_CONTINUATION_SHORT"
    GOLD_PREMARKET_ORB = "GOLD_PREMARKET_ORB"
    GOLD_OPENING_ORB = "GOLD_OPENING_ORB"
    GOLD_EARLY_BIRD = "GOLD_EARLY_BIRD"
    GOLD_RANGE_BREAKOUT = "GOLD_RANGE_BREAKOUT"
    GOLD_ORB_ALIGNMENT = "GOLD_ORB_ALIGNMENT"
    ASIAN_SESSION_CONTEXT = "ASIAN_SESSION_CONTEXT"
    SFP_REVERSAL_LONG = "SFP_REVERSAL_LONG"
    SFP_REVERSAL_SHORT = "SFP_REVERSAL_SHORT"
    ORB_BREAKOUT_LONG = "ORB_BREAKOUT_LONG"
    ORB_BREAKOUT_SHORT = "ORB_BREAKOUT_SHORT"
    ZONE_REJECTION_LONG = "ZONE_REJECTION_LONG"
    ZONE_REJECTION_SHORT = "ZONE_REJECTION_SHORT"
    MARKET_STRUCTURE_CONTINUATION = "MARKET_STRUCTURE_CONTINUATION"
    MARKET_STRUCTURE_REVERSAL = "MARKET_STRUCTURE_REVERSAL"
    NO_TRADE = "NO_TRADE"


# which types have a detector in this repo (honest status, used by docs/API)
IMPLEMENTED = {
    "SNAPBACK_CONTINUATION_LONG": "features/price_action/gold.py::SnapbackDetector (+ legacy orb_retest mapping)",
    "SNAPBACK_CONTINUATION_SHORT": "features/price_action/gold.py::SnapbackDetector (+ legacy orb_retest mapping)",
    "GOLD_OPENING_ORB": "features/price_action/gold.py (box + optional breakout entries)",
    "GOLD_PREMARKET_ORB": "features/price_action/gold.py (box only; needs <=5m bars)",
    "OPENING_BOX_BREAKOUT": "gold.py breakout entries (opening box)",
    "SFP_REVERSAL_LONG": "features/price_action/sfp.py",
    "SFP_REVERSAL_SHORT": "features/price_action/sfp.py",
    "ZONE_REJECTION_LONG": "mapping of prior_day_range_reversal / wick_reversal",
    "ZONE_REJECTION_SHORT": "mapping of prior_day_range_reversal / wick_reversal",
    "ASIAN_SESSION_CONTEXT": "levels.py Asian session high/low (context only, never a trade)",
    "NO_TRADE": "contracts.resolve",
}
SETUP_TYPES = {t.value: ("implemented" if t.value in IMPLEMENTED else "reserved") for t in SetupType}


class NoTradeReason(str, Enum):
    CONFLICTING_CANDIDATES = "CONFLICTING_CANDIDATES"          # opposite directions from the same event
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"                  # same event already produced an actionable candidate
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"                    # warm-up / missing bars / missing calendar
    STALE_DATA = "STALE_DATA"                                  # last bar older than allowed
    REWARD_BELOW_COST = "REWARD_BELOW_COST"                    # net-of-cost reward:risk under threshold
    NO_TARGET = "NO_TARGET"
    REENTRY_LIMIT = "REENTRY_LIMIT"
    HTF_CONFLICT = "HTF_CONFLICT"
    UNRESOLVED_INTERACTION = "UNRESOLVED_INTERACTION"
    MODEL_ABSTAINED = "MODEL_ABSTAINED"
    RISK_REJECTED = "RISK_REJECTED"


FAMILY = {"sfp_reversal": "sfp", "gold_snapback": "snapback", "gold_orb_breakout": "orb", "orb_retest": "snapback",
          "prior_day_range_reversal": "zone_rejection", "wick_reversal": "zone_rejection"}


def setup_type_for(c: Candidate) -> str:
    if c.features.get("setup_type"):
        return str(c.features["setup_type"])
    side = "LONG" if c.direction == "long" else "SHORT"
    return {"orb_retest": f"SNAPBACK_CONTINUATION_{side}", "sfp_reversal": f"SFP_REVERSAL_{side}",
            "gold_snapback": f"SNAPBACK_CONTINUATION_{side}", "gold_orb_breakout": "GOLD_OPENING_ORB",
            "prior_day_range_reversal": f"ZONE_REJECTION_{side}", "wick_reversal": f"ZONE_REJECTION_{side}"}.get(c.detector, "NO_TRADE")


@dataclass
class UnifiedCandidate:
    id: str
    setup_type: str
    family: str
    instrument: str
    direction: str                    # long | short | none
    reference_levels: list[dict[str, Any]]
    supporting_observations: list[str]
    event_id: str                     # the shared price-level event this candidate consumes (dedupe key)
    confirmation_ts: int
    entry_hypothesis: dict[str, Any]
    invalidation: dict[str, Any]
    targets: list[float]
    expected_holding_seconds: int
    required_data: list[str]
    est_costs: dict[str, Any]
    expiration_ts: int
    explanation: dict[str, list[str]]
    ml_forecast_ref: str | None = None
    risk_status: str = "not_evaluated"     # set only by the control plane
    actionable: bool = True
    no_trade_reason: str | None = None
    corroborating: list[str] = field(default_factory=list)
    execution_permission: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unify(c: Candidate, timeframe: int, hold_seconds: int = 86400) -> UnifiedCandidate:
    f = c.features
    expl = f.get("explanation") or {"OBSERVED": [], "INFERRED": [], "UNVERIFIED": []}
    return UnifiedCandidate(
        id=c.candidate_id, setup_type=setup_type_for(c), family=FAMILY.get(c.detector, c.detector), instrument=c.instrument,
        direction=c.direction, reference_levels=list(f.get("reference_levels") or [c.zone]),
        supporting_observations=list(expl.get("OBSERVED", [])), event_id=str(f.get("event_id") or c.candidate_id),
        confirmation_ts=c.detected_at,
        entry_hypothesis={"type": c.entry_type, "price": c.entry_reference, "active_from": c.detected_at,
                          "window_bars": 3, "timeframe_s": timeframe},
        invalidation={"stop": c.proposed_stop, "level": c.invalidation_level, "rule": f.get("invalidation_rule", "stop touch")},
        targets=[c.proposed_target], expected_holding_seconds=hold_seconds,
        required_data=list(f.get("required_data") or ["confirmed OHLCV bars"]),
        est_costs={k: f[k] for k in ("cost_r", "cost_price") if k in f}, expiration_ts=c.detected_at + 3 * timeframe,
        explanation=expl)


def resolve(cands: Iterable[UnifiedCandidate]) -> list[UnifiedCandidate]:
    """Deterministic conflict resolution over candidates that share an ``event_id`` (shared evidence).

    - opposite directions on one event -> every candidate of the event becomes NO_TRADE (CONFLICTING_CANDIDATES);
    - same direction -> the earliest (ties: lexical id) stays actionable, the rest become NO_TRADE (DUPLICATE_EVIDENCE)
      and are listed in ``corroborating`` of the kept one, so evidence is never counted twice.
    Continuation and reversal on the same breakout event can therefore never both be actionable."""
    out = list(cands)
    by: dict[str, list[UnifiedCandidate]] = {}
    for u in out:
        if u.actionable:
            by.setdefault(u.event_id, []).append(u)
    for group in by.values():
        if len({u.direction for u in group}) > 1:
            for u in group:
                u.actionable, u.no_trade_reason = False, NoTradeReason.CONFLICTING_CANDIDATES.value
            continue
        group.sort(key=lambda u: (u.confirmation_ts, u.id))
        for u in group[1:]:
            u.actionable, u.no_trade_reason = False, NoTradeReason.DUPLICATE_EVIDENCE.value
            group[0].corroborating.append(u.id)
    return out
