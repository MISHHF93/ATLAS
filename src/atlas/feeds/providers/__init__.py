"""Provider-adapter library. Each module exposes one ProviderAdapter subclass with a Capabilities manifest."""
from .alpaca import AlpacaAdapter, AlpacaCryptoAdapter
from .alphavantage import AlphaVantageAdapter
from .binance import BinanceAdapter
from .boc import BankOfCanadaFXAdapter
from .bybit import BybitAdapter
from .coinbase import CoinbaseAdapter
from .ecb import ECBFXAdapter
from .finnhub import FinnhubAdapter
from .fred import FREDAdapter
from .kraken import KrakenAdapter
from .oanda import OandaAdapter
from .okx import OKXAdapter
from .polygon import PolygonAdapter
from .questrade import QuestradeAdapter
from .stubs import CMEStub, DatabentoAdapter, IBKRAdapter, TMXStub
from .tiingo import TiingoAdapter
from .tradier import TradierAdapter
from .twelvedata import TwelveDataAdapter
from .yahoo import YahooAdapter

ALL_ADAPTERS = (BinanceAdapter, CoinbaseAdapter, KrakenAdapter, OKXAdapter, BybitAdapter, YahooAdapter, FREDAdapter,
                AlpacaAdapter, AlpacaCryptoAdapter, TiingoAdapter, PolygonAdapter, FinnhubAdapter, TwelveDataAdapter, AlphaVantageAdapter,
                DatabentoAdapter, IBKRAdapter, OandaAdapter, QuestradeAdapter, TradierAdapter, CMEStub, TMXStub, BankOfCanadaFXAdapter,
                ECBFXAdapter)
