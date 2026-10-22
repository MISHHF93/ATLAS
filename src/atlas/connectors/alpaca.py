"""US Equities execution connector module (`src/atlas/connectors/alpaca.py`).

Thin re-export of the canonical `AlpacaEquitiesConnector` implementation
(Rest/WebSocket US-equity DMA adapter) so production routes can import the
venue connector from its dedicated module path.
"""

from atlas.connectors.base import AlpacaEquitiesConnector

__all__ = ["AlpacaEquitiesConnector"]
