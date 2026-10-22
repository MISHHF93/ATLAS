"""Unified Execution Connectors Package (`src/atlas/connectors/`).

Per-venue module files expose the documented import surface:
- `connectors.alpaca` → `AlpacaEquitiesConnector` (US Equities REST/WS DMA)
- `connectors.ibkr`   → `IBKRDMAConnector` (Interactive Brokers FIX 4.4 / TWS DMA)
- `connectors.dxtrade` → `DXtradePropConnector` ( institutional prop challenge bridge)
- `connectors.ctrader` → `CTradePropAPIConnector` (cTrader Open API prop bridge)
- `connectors.ccxt_perp` → `CCXTPerpConnector` (24/7 crypto perpetuals)
"""
from atlas.connectors.base import (
    AlpacaEquitiesConnector,
    BaseExecutionConnector,
    CCXTPerpConnector,
    ConnectorVenueType,
    DXtradePropConnector,
    UnifiedExecutionCallback,
    UnifiedOrderPlacementRequest,
    UnifiedOrderSide,
    UnifiedOrderStatus,
    UnifiedOrderType,
    UnifiedPositionBlotterEntry,
)
from atlas.connectors.ctrader import CTradePropAPIConnector
from atlas.connectors.ibkr import IBKRDMAConnector, IBKRSessionConfig

__all__ = [
    "AlpacaEquitiesConnector",
    "BaseExecutionConnector",
    "CCXTPerpConnector",
    "CTradePropAPIConnector",
    "ConnectorVenueType",
    "DXtradePropConnector",
    "IBKRDMAConnector",
    "IBKRSessionConfig",
    "UnifiedExecutionCallback",
    "UnifiedOrderPlacementRequest",
    "UnifiedOrderSide",
    "UnifiedOrderStatus",
    "UnifiedOrderType",
    "UnifiedPositionBlotterEntry",
]
