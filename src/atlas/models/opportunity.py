"""Trade evaluation after costs (spec 13). Research only. Every output is a *proposal input*:
``ActionableControlPlaneEngine`` makes the final sizing and authorization decision.

Simplified binary payoff, all values per unit in price units:
    EV            = p*G - (1-p)*L - C
    break-even p  = (L + C) / (G + L)
    Kelly f*      = (b*p - (1-p)) / b,   b = (G - C) / (L + C)   (net gain per unit net risk)
    units         = floor(equity * risk_fraction / ((L + C) * multiplier) / lot) * lot
Kelly is a research benchmark. We report a fractional multiple clipped at 0, never the full f* as a policy.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.models.predict import Prediction

INSUFFICIENT_EDGE = "insufficient_edge"
COSTS = "costs_exceed_edge"
PROB_SEMANTICS = "probability_semantics_mismatch"
BAD_GEOMETRY = "invalid_stop_target_geometry"


def expected_value(p: float, gain: float, loss: float, cost: float) -> float:
    return p * gain - (1.0 - p) * loss - cost


def break_even_probability(gain: float, loss: float, cost: float) -> float:
    if gain + loss <= 0:
        raise ValueError("gain + loss must be positive")
    return (loss + cost) / (gain + loss)


def kelly_fraction(p: float, b: float) -> float:
    if b <= 0:
        raise ValueError("b must be positive")
    return (b * p - (1.0 - p)) / b


def risk_units(equity: float, risk_fraction: float, risk_per_unit: float, *, multiplier: float = 1.0, lot: float = 1.0) -> float:
    if risk_per_unit <= 0 or multiplier <= 0 or lot <= 0:
        return 0.0
    return math.floor(equity * risk_fraction / (risk_per_unit * multiplier) / lot) * lot


@dataclass
class OpportunityEvaluation:
    candidate_id: str
    probability: float | None
    gain: float
    loss: float
    cost: float
    expected_value: float | None = None
    expected_value_r: float | None = None
    break_even_probability: float | None = None
    edge_over_break_even: float | None = None
    kelly_full: float | None = None
    kelly_fractional: float | None = None
    research_units: float | None = None
    abstention_reason: list[str] = field(default_factory=list)
    sizing_authority: str = "ActionableControlPlaneEngine"
    execution_permission: str = "none"

    @property
    def abstained(self) -> bool:
        return bool(self.abstention_reason)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["abstained"] = self.abstained
        return d


def evaluate_candidate(candidate: Any, prediction: Prediction, *, cost_per_unit: float, min_edge_r: float = 0.05,
                       kelly_multiple: float = 0.25, equity: float | None = None, risk_fraction: float = 0.006,
                       multiplier: float = 1.0, lot: float = 1.0) -> OpportunityEvaluation:
    """``prediction`` must be a ``setup_success`` model output, i.e. P(target reached before stop)."""
    gain = abs(candidate.proposed_target - candidate.entry_reference)
    loss = abs(candidate.entry_reference - candidate.proposed_stop)
    ev = OpportunityEvaluation(candidate.candidate_id, None, gain, loss, float(cost_per_unit))
    r = ev.abstention_reason
    if gain <= 0 or loss <= 0:
        r.append(BAD_GEOMETRY)
        return ev
    if prediction.abstained:
        r.extend(prediction.abstention_reason)
    elif prediction.target != "setup_success" or prediction.probability_positive is None:
        r.append(PROB_SEMANTICS)
    ev.break_even_probability = break_even_probability(gain, loss, cost_per_unit)
    if cost_per_unit >= gain:
        r.append(COSTS)
    if r:
        return ev
    p = prediction.probability_positive
    ev.probability = p
    ev.expected_value = expected_value(p, gain, loss, cost_per_unit)
    ev.expected_value_r = ev.expected_value / loss
    ev.edge_over_break_even = p - ev.break_even_probability
    b = (gain - cost_per_unit) / (loss + cost_per_unit)
    ev.kelly_full = kelly_fraction(p, b)
    ev.kelly_fractional = max(0.0, kelly_multiple * ev.kelly_full)
    if equity is not None:
        ev.research_units = risk_units(equity, risk_fraction, loss + cost_per_unit, multiplier=multiplier, lot=lot)
    if ev.expected_value_r <= min_edge_r:
        gross_r = (ev.expected_value + cost_per_unit) / loss
        r.append(COSTS if gross_r > min_edge_r else INSUFFICIENT_EDGE)
    return ev
