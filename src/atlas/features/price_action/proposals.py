"""Candidate + evaluation -> StrategySignal proposal for the deterministic control plane (never an order).

Conviction is the *calibrated* P(target before stop) from the unified ``predict()`` contract. When no
validated, calibrated model exists, or the evaluation abstains, no proposal is produced at all. There
is no placeholder conviction."""
from __future__ import annotations

from typing import Any

from atlas.features.price_action.detectors import Candidate
from atlas.models.opportunity import OpportunityEvaluation, evaluate_candidate
from atlas.models.predict import FeatureSnapshot, ModelRegistry, predict
from atlas.strategies.base import StrategySignal

SETUP_HORIZON = "setup_resolution"


class Abstained(ValueError):
    pass


def candidate_snapshot(c: Candidate) -> FeatureSnapshot:
    vals = {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None) for k, v in c.features.items()}
    return FeatureSnapshot(values=vals, available_at={k: c.detected_at for k in vals})


def evaluate(c: Candidate, *, model_version: str | None = None, registry: ModelRegistry | None = None,
             cost_per_unit: float = 0.0, **kw: Any) -> tuple[Any, OpportunityEvaluation]:
    pred = predict(c.instrument, c.detected_at, SETUP_HORIZON, candidate_snapshot(c), model_version, registry)
    return pred, evaluate_candidate(c, pred, cost_per_unit=cost_per_unit, **kw)


def candidate_to_signal(c: Candidate, evaluation: OpportunityEvaluation) -> StrategySignal:
    if evaluation is None or evaluation.abstained or evaluation.probability is None:
        raise Abstained(f"no proposal: {getattr(evaluation, 'abstention_reason', ['no_evaluation'])}")
    if evaluation.candidate_id != c.candidate_id:
        raise ValueError("evaluation does not belong to this candidate")
    p = float(evaluation.probability)
    return StrategySignal(
        strategy_id=f"PA_{c.detector.upper()}", symbol=c.instrument,
        direction="BUY" if c.direction == "long" else "SELL",
        target_conviction=p, conviction=p,
        suggested_stop_loss=c.proposed_stop, suggested_take_profit=c.proposed_target,
        execution_tactic="LIMIT", reference_price=c.entry_reference, target_entry_price=c.entry_reference,
        rationale=f"{c.detector} candidate {c.candidate_id}; calibrated p={p:.3f}, EV_R={evaluation.expected_value_r:.3f}",
        telemetry={"candidate_id": c.candidate_id, "probability_calibrated": True,
                   "evaluation": evaluation.to_dict(), "vpin": 0.0},
    )
