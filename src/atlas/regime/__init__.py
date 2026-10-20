"""Subsystem R: Regime Classification & Hawkes Hidden Liquidity Engine (`src/atlas/regime/`)."""
from atlas.regime.hawkes_detector import (
    HawkesIntensityReport,
    RegimeConfig,
    RegimeState,
    classify_regime,
    compute_hawkes_intensity,
)

__all__ = [
    "HawkesIntensityReport",
    "RegimeConfig",
    "RegimeState",
    "classify_regime",
    "compute_hawkes_intensity",
]

