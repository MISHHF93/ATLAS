"""Order flow toxicity, informed trading price impact, multi-level OFI, and Hawkes intensity.

Re-exports and extends the institutional flow models defined in
`atlas.marketdata.microstructure` with strict `execution_permission = "none"`
invariants.
"""
from __future__ import annotations

from atlas.marketdata.microstructure import (
    BookLevelSnapshot,
    HawkesIntensityReport,
    KylesLambdaResult,
    MultiLevelOfiReport,
    VpinBucketReport,
    VpinBucketSlice,
    compute_hawkes_intensity,
    compute_multilevel_ofi,
    compute_volume_synchronized_vpin,
    estimate_kyles_lambda,
)

from atlas.features.microstructure import compute_atr  # noqa: F401  (canonical ATR re-export)

__all__ = [
    "BookLevelSnapshot",
    "HawkesIntensityReport",
    "KylesLambdaResult",
    "MultiLevelOfiReport",
    "VpinBucketReport",
    "VpinBucketSlice",
    "compute_atr",
    "compute_hawkes_intensity",
    "compute_multilevel_ofi",
    "compute_volume_synchronized_vpin",
    "estimate_kyles_lambda",
]

