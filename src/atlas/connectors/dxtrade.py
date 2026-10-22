"""Institutional prop challenge bridge module (`src/atlas/connectors/dxtrade.py`).

Thin re-export of the canonical `DXtradePropConnector` implementation
(FIX 4.4 / REST prop-challenge evaluation bridge) so production routes can
import the venue connector from its dedicated module path.
"""

from atlas.connectors.base import DXtradePropConnector

__all__ = ["DXtradePropConnector"]
