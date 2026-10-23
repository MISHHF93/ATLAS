"""Subsystem Q: Quantitative Validation & Purged Walk-Forward (`src/atlas/experiments/`).

Re-exports purged & embargoed walk-forward evaluation (`build_purged_embargoed_splits`,
`run_baseline_vs_tree_study`) and SQLite experiment tracking.
"""
from atlas.models.challengers import (
    WalkForwardStudyResult,
    run_baseline_vs_tree_study,
)
from atlas.models.experiments import ExperimentStore
from atlas.models.self_training import (
    PurgedFoldSplit,
    build_purged_embargoed_splits,
)

# Backwards-compatible name used by older subsystem documentation.
SQLiteExperimentTracker = ExperimentStore

__all__ = [
    "ExperimentStore",
    "PurgedFoldSplit",
    "SQLiteExperimentTracker",
    "WalkForwardStudyResult",
    "build_purged_embargoed_splits",
    "run_baseline_vs_tree_study",
]
