"""Subsystem P: Probability Calibration & Forecast Fans (`src/atlas/calibration/`).

Re-exports empirical bin probability calibration (`ProbabilityCalibrator`) and adds
Platt sigmoid scaling (`1 / (1 + exp(A * score + B))`) for calibrated forecast intervals.
"""
from __future__ import annotations

import math

from atlas.models.model_store import ProbabilityCalibrator


def platt_scale_probability(raw_score: float, *, slope_a: float = -2.2, intercept_b: float = 0.0) -> float:
    """Compute Platt-scaled probability P(y=1 | s) = 1 / (1 + exp(A * s + B))."""
    z = max(-40.0, min(40.0, slope_a * float(raw_score) + intercept_b))
    return round(1.0 / (1.0 + math.exp(z)), 6)


__all__ = ["ProbabilityCalibrator", "platt_scale_probability"]

