"""Feature engineering and microstructure toxicity subsystem (`src/atlas/features`).

All feature and toxicity estimators are strictly causal and carry
``execution_permission = "none"``.
"""
from atlas.features.microstructure import (
    BookLevelSnapshot,
    HawkesIntensityReport,
    KylesLambdaResult,
    MicrostructureWhaleFeatureExtractor,
    MultiLevelOfiReport,
    VpinBucketReport,
    VpinBucketSlice,
    WhaleMicrostructureFeatureSnapshot,
    compute_exponential_multilevel_ofi,
    compute_hawkes_child_order_intensity,
    compute_hawkes_intensity,
    compute_multilevel_ofi,
    compute_rolling_kyles_lambda,
    compute_rolling_vpin,
    compute_volume_synchronized_vpin,
    estimate_kyles_lambda,
)

__all__ = [
    "BookLevelSnapshot",
    "HawkesIntensityReport",
    "KylesLambdaResult",
    "MicrostructureWhaleFeatureExtractor",
    "MultiLevelOfiReport",
    "VpinBucketReport",
    "VpinBucketSlice",
    "WhaleMicrostructureFeatureSnapshot",
    "compute_exponential_multilevel_ofi",
    "compute_hawkes_child_order_intensity",
    "compute_hawkes_intensity",
    "compute_multilevel_ofi",
    "compute_rolling_kyles_lambda",
    "compute_rolling_vpin",
    "compute_volume_synchronized_vpin",
    "estimate_kyles_lambda",
]
