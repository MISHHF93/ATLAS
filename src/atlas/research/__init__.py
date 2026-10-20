"""Subsystem Z: Zero Data-Leakage Research & Sandbox (`src/atlas/research/`).

Re-exports SHA-256 manifest-verified frozen datasets (`FrozenDatasetBundle`),
continuous research tick orchestration (`ContinuousResearchRunner`), and
autonomous self-training with strict purging/embargoing (`run_autonomous_self_training_cycle`).
"""
from atlas.marketdata.frozen import FrozenDatasetBundle, build_canonical_frozen_bundles
from atlas.models.continuous import (
    CentralResearchNode,
    ContinuousResearchRunner,
    run_autonomous_self_training_cycle,
    run_track_paper_simulation,
)

__all__ = [
    "CentralResearchNode",
    "ContinuousResearchRunner",
    "FrozenDatasetBundle",
    "build_canonical_frozen_bundles",
    "run_autonomous_self_training_cycle",
    "run_track_paper_simulation",
]

