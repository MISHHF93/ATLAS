"""Read-only market data contracts, MCP allowlisted adapters, microstructure covariates, quality validation, and frozen datasets.

All outputs are research records with `execution_permission: none`.
"""
from atlas.marketdata.frozen import FrozenDatasetBundle, build_frozen_benchmark_dataset
from atlas.marketdata.mcp_adapters import (
    ALLOWED_MCP_TOOLS,
    FORBIDDEN_MCP_SERVERS,
    MCPDataSourceAdapter,
    MCPTransport,
)
from atlas.marketdata.microstructure import (
    RawMicrostructureEvent,
    WhaleMicrostructurePolicy,
    normalize_microstructure_covariates,
)
from atlas.marketdata.quality import DataQualityReport, validate_market_data_batch

__all__ = [
    "ALLOWED_MCP_TOOLS",
    "FORBIDDEN_MCP_SERVERS",
    "DataQualityReport",
    "FrozenDatasetBundle",
    "MCPDataSourceAdapter",
    "MCPTransport",
    "RawMicrostructureEvent",
    "WhaleMicrostructurePolicy",
    "build_frozen_benchmark_dataset",
    "normalize_microstructure_covariates",
    "validate_market_data_batch",
]
