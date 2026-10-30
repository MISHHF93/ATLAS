"""Provider-adapter library. Each module exposes one ProviderAdapter subclass with a Capabilities manifest."""
from .alpaca import AlpacaAdapter, AlpacaCryptoAdapter
from .alphavantage import AlphaVantageAdapter
from .boc import BankOfCanadaFXAdapter
from .coinbase import CoinbaseAdapter
from .ecb import ECBFXAdapter
from .finnhub import FinnhubAdapter
from .fred import FREDAdapter
from .kraken import KrakenAdapter
from .oanda import OandaAdapter
from .polygon import PolygonAdapter
from .questrade import QuestradeAdapter
from .rates import BankOfCanadaRatesAdapter, EIAAdapter, UsTreasuryYieldAdapter
from .stubs import CMEStub, DatabentoAdapter, IBKRAdapter, TMXStub
from .tiingo import TiingoAdapter
from .twelvedata import TwelveDataAdapter
from .yahoo import YahooAdapter

ALL_ADAPTERS = (CoinbaseAdapter, KrakenAdapter, YahooAdapter, FREDAdapter,
                AlpacaAdapter, AlpacaCryptoAdapter, TiingoAdapter, PolygonAdapter, FinnhubAdapter, TwelveDataAdapter, AlphaVantageAdapter,
                DatabentoAdapter, IBKRAdapter, OandaAdapter, QuestradeAdapter, CMEStub, TMXStub, BankOfCanadaFXAdapter,
                ECBFXAdapter, UsTreasuryYieldAdapter, BankOfCanadaRatesAdapter, EIAAdapter)
