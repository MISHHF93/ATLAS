"""Candidate -> StrategySignal proposal for the deterministic control plane (never an order)."""
from __future__ import annotations

from atlas.features.price_action.detectors import Candidate
from atlas.strategies.base import StrategySignal


def candidate_to_signal(c: Candidate) -> StrategySignal:
    return StrategySignal(
        strategy_id=f"PA_{c.detector.upper()}", symbol=c.instrument,
        direction="BUY" if c.direction == "long" else "SELL",
        # No calibrated model probability exists for this setup: neutral 0.5, flagged in telemetry.
        target_conviction=0.5, conviction=0.5,
        suggested_stop_loss=c.proposed_stop, suggested_take_profit=c.proposed_target,
        execution_tactic="LIMIT", reference_price=c.entry_reference, target_entry_price=c.entry_reference,
        rationale=f"{c.detector} candidate {c.candidate_id}; deterministic rule, uncalibrated",
        telemetry={"candidate_id": c.candidate_id, "probability_calibrated": False, "vpin": 0.0},
    )
