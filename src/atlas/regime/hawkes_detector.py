"""WF-07 & Subsystem R: Regime-Conditioned Hidden Liquidity Detector (`src/atlas/regime/hawkes_detector.py`).

Implements the Hawkes self-exciting point process intensity:
    lambda(t) = mu_0 + sum_{t_i < t} alpha * exp(-beta * (t - t_i))
for detecting iceberg child-order clustering and hidden dark-pool replenishment.
All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

from atlas.marketdata.microstructure import (
    HawkesIntensityReport,
    compute_hawkes_intensity,
)
from atlas.models.regimes import RegimeConfig, RegimeState, classify_regime

__all__ = [
    "HawkesIntensityReport",
    "RegimeConfig",
    "RegimeState",
    "classify_regime",
    "compute_hawkes_intensity",
]

