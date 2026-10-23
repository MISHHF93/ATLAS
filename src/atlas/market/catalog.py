"""Unified Instrument Catalog and Provider Registry for ATLAS.

Implements a centralized registry of all eligible assets, their exchange 
mappings, and the capabilities of available market-data providers.

This ensures that the system knows exactly which provider to use for 
which asset and whether the requested data (e.g., Order Book) is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Dict, Any
from atlas.models.schemas import Record, Text


class AssetClass(Enum):
    EQUITY = auto()
    CRYPTO = auto()
    FUTURE = auto()
    FOREX = auto()
    COMMODITY = auto()
    OPTION = auto()
    INDEX = auto()


class DataCapability(Enum):
    OHLCV = auto()
    TICK_TAPE = auto()
    ORDER_BOOK = auto()
    TICK_DEPTH = auto()
    FUNDAMENTALS = auto()
    ECONOMIC_EVENTS = auto()


@dataclass(frozen=True)
class InstrumentDefinition(Record):
    """The canonical definition of a financial instrument."""
    symbol: Text
    asset_class: AssetClass
    exchange: Text
    base_currency: Text = "USD"
    quote_currency: Text = "USD"
    tick_size: float = 0.01
    lot_size: float = 1.0
    is_tradable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_permission: Literal["none"] = "none"


class InstrumentCatalog:
    """
    The single source of truth for all instruments recognized by ATLAS.
    """

    def __init__(self):
        self._instruments: Dict[str, InstrumentDefinition] = {}
        self._provider_capabilities: Dict[str, List[DataCapability]] = {}
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Seed the catalog with core Module 02 assets."""
        # Crypto
        self.add_instrument(InstrumentDefinition(
            symbol="BTC-USD", asset_class=AssetClass.CRYPTO, exchange="COINBASE"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="ETH-USD", asset_class=AssetClass.CRYPTO, exchange="COINBASE"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="SOL-USD", asset_class=AssetClass.CRYPTO, exchange="COINBASE"
        ))
        
        # Equities
        self.add_instrument(InstrumentDefinition(
            symbol="SPY", asset_class=AssetClass.EQUITY, exchange="AMEX"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="NVDA", asset_class=AssetClass.EQUITY, exchange="NASDAQ"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="AAPL", asset_class=AssetClass.EQUITY, exchange="NASDAQ"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="MSFT", asset_class=AssetClass.EQUITY, exchange="NASDAQ"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="QQQ", asset_class=AssetClass.EQUITY, exchange="AMEX"
        ))
        self.add_instrument(InstrumentDefinition(
            symbol="TSLA", asset_class=AssetClass.EQUITY, exchange="NASDAQ"
        ))

    def add_instrument(self, instrument: InstrumentDefinition) -> None:
        self._instruments[instrument.symbol.upper()] = instrument

    def get_instrument(self, symbol: str) -> Optional[InstrumentDefinition]:
        return self._instruments.get(symbol.upper())

    def list_instruments(self, asset_class: Optional[AssetClass] = None) -> List[InstrumentDefinition]:
        if asset_class:
            return [i for i in self._instruments.values() if i.asset_class == asset_class]
        return list(self._instruments.values())

    def register_provider_capability(self, provider: str, capabilities: List[DataCapability]) -> None:
        self._provider_capabilities[provider.lower()] = capabilities

    def can_provide(self, provider: str, capability: DataCapability) -> bool:
        caps = self._provider_capabilities.get(provider.lower(), [])
        return capability in caps

# Global Singleton for the system
GLOBAL_CATALOG = InstrumentCatalog()
