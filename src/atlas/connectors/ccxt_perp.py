"""Crypto perpetuals execution connector module (`src/atlas/connectors/ccxt_perp.py`).

Thin re-export of the canonical `CCXTPerpConnector` implementation
(CCXT Pro async WebSocket 24/7 crypto perpetual orders and funding tracker)
so production routes can import the venue connector from its dedicated module path.
"""

from atlas.connectors.base import CCXTPerpConnector

__all__ = ["CCXTPerpConnector"]
