"""Local asset directory.

Flagship names, a searchable list of well-known listings, and placeholder ids.
`EQ####` and `PERP###` rows fill the count. They are not missing companies.
Named rows are a directory, not live quotes. A private company such as SpaceX
is stored so search can find it, and it is marked unlisted. Nothing here is an
order, and no vendor universe is downloaded.

All catalog outputs carry `execution_permission = "none"`.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

AssetClassType = Literal["equities", "crypto_perps", "futures"]
TrackType = Literal["open_market", "competition"]


@dataclass(frozen=True)
class CatalogAssetRecord:
    symbol: str
    name: str
    asset_class: AssetClassType
    exchange: str
    tick_size: float
    lot_size: float
    min_notional: float
    track: TrackType
    is_active: bool
    last_price: float
    change_pct: float
    volume_1m: float
    volume_24h: float
    vpin: float
    ofi_z: float
    kyles_lambda: float
    spread_bps: float
    regime: str
    provider: str
    priority_rank: int = 100
    data_status: Literal["synthetic_fixture"] = "synthetic_fixture"
    execution_permission: Literal["none"] = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Flagship curated US NMS Equities & ETFs (Polygon.io / Databento SIP)
FLAGSHIP_EQUITIES: tuple[tuple[str, str, str, float, float, float, str], ...] = (
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSE_ARCA", 584.20, 0.42, 0.242, "Compression"),
    ("QQQ", "Invesco QQQ Trust (Nasdaq-100)", "NASDAQ", 498.60, 0.88, 0.289, "Expansion"),
    ("NVDA", "NVIDIA Corporation", "NASDAQ", 142.10, 2.14, 0.368, "Expansion"),
    ("AAPL", "Apple Inc.", "NASDAQ", 231.45, 0.65, 0.214, "Compression"),
    ("MSFT", "Microsoft Corporation", "NASDAQ", 428.90, 0.31, 0.225, "Compression"),
    ("TSLA", "Tesla Inc.", "NASDAQ", 254.30, -1.12, 0.432, "Volatile Auction"),
    ("AMZN", "Amazon.com Inc.", "NASDAQ", 210.80, 1.05, 0.256, "Expansion"),
    ("META", "Meta Platforms Inc.", "NASDAQ", 592.40, 1.48, 0.274, "Expansion"),
    ("GOOGL", "Alphabet Inc. Class A", "NASDAQ", 181.65, 0.54, 0.219, "Compression"),
    ("AMD", "Advanced Micro Devices Inc.", "NASDAQ", 156.20, 1.92, 0.341, "Expansion"),
    ("AVGO", "Broadcom Inc.", "NASDAQ", 179.50, 1.36, 0.295, "Expansion"),
    ("NFLX", "Netflix Inc.", "NASDAQ", 764.10, 0.95, 0.248, "Compression"),
    ("JPM", "JPMorgan Chase & Co.", "NYSE", 232.80, 0.62, 0.208, "Compression"),
    ("GS", "The Goldman Sachs Group Inc.", "NYSE", 528.40, 0.78, 0.221, "Compression"),
    ("PLTR", "Palantir Technologies Inc.", "NYSE", 43.85, 3.45, 0.388, "Expansion"),
    ("COIN", "Coinbase Global Inc.", "NASDAQ", 218.60, 4.12, 0.415, "Expansion"),
    ("MSTR", "MicroStrategy Incorporated", "NASDAQ", 235.40, 5.20, 0.442, "Expansion"),
    ("SMCI", "Super Micro Computer Inc.", "NASDAQ", 48.20, -2.10, 0.465, "Volatile Auction"),
    ("ARM", "Arm Holdings plc", "NASDAQ", 152.90, 1.84, 0.318, "Expansion"),
    ("CRWD", "CrowdStrike Holdings Inc.", "NASDAQ", 314.50, 0.92, 0.264, "Compression"),
    ("PANW", "Palo Alto Networks Inc.", "NASDAQ", 372.10, 0.68, 0.239, "Compression"),
    ("SNOW", "Snowflake Inc.", "NYSE", 124.75, -0.45, 0.282, "Mean-Reverting"),
    ("LLY", "Eli Lilly and Company", "NYSE", 904.20, 0.55, 0.215, "Compression"),
    ("UNH", "UnitedHealth Group Inc.", "NYSE", 568.90, -0.32, 0.204, "Compression"),
    ("V", "Visa Inc. Class A", "NYSE", 291.40, 0.41, 0.195, "Compression"),
    ("MA", "Mastercard Incorporated", "NYSE", 512.30, 0.48, 0.198, "Compression"),
    ("XOM", "Exxon Mobil Corporation", "NYSE", 121.40, -0.58, 0.229, "Mean-Reverting"),
    ("IWM", "iShares Russell 2000 ETF", "NYSE_ARCA", 224.80, 0.74, 0.262, "Expansion"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", "NYSE_ARCA", 431.20, 0.36, 0.205, "Compression"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "NASDAQ", 93.45, -0.42, 0.251, "Mean-Reverting"),
    ("GLD", "SPDR Gold Shares ETF", "NYSE_ARCA", 252.80, 0.85, 0.234, "Expansion"),
    ("SLV", "iShares Silver Trust ETF", "NYSE_ARCA", 30.95, 1.65, 0.298, "Expansion"),
    ("XLF", "Financial Select Sector SPDR Fund", "NYSE_ARCA", 47.20, 0.52, 0.211, "Compression"),
    ("XLK", "Technology Select Sector SPDR Fund", "NYSE_ARCA", 232.10, 1.12, 0.268, "Expansion"),
    ("XLE", "Energy Select Sector SPDR Fund", "NYSE_ARCA", 90.40, -0.64, 0.244, "Mean-Reverting"),
    ("SOXX", "iShares Semiconductor ETF", "NASDAQ", 236.70, 1.78, 0.332, "Expansion"),
    ("MUB", "iShares National Muni Bond ETF", "NYSE_ARCA", 108.20, 0.04, 0.180, "Compression"),
    ("VTEB", "Vanguard Tax-Exempt Bond ETF", "NYSE_ARCA", 51.40, 0.03, 0.176, "Compression"),
    ("TFI", "SPDR Nuveen Bloomberg Municipal Bond ETF", "NYSE_ARCA", 46.10, 0.02, 0.174, "Compression"),
    ("HYMB", "SPDR Nuveen Bloomberg High Yield Municipal Bond ETF", "NYSE_ARCA", 49.80, 0.06, 0.210, "Mean-Reverting"),
    ("CMF", "iShares California Muni Bond ETF", "NYSE_ARCA", 57.30, 0.03, 0.178, "Compression"),
    ("NYF", "iShares New York Muni Bond ETF", "NYSE_ARCA", 52.10, 0.03, 0.177, "Compression"),
    ("SGOV", "iShares 0-3 Month Treasury Bond ETF", "NYSE", 100.60, 0.01, 0.120, "Compression"),
    ("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF", "NYSE_ARCA", 91.50, 0.01, 0.122, "Compression"),
    ("SHY", "iShares 1-3 Year Treasury Bond ETF", "NASDAQ", 82.40, -0.02, 0.160, "Compression"),
    ("IEF", "iShares 7-10 Year Treasury Bond ETF", "NASDAQ", 96.20, -0.08, 0.190, "Mean-Reverting"),
    ("VOO", "Vanguard S&P 500 ETF", "NYSE_ARCA", 548.00, 0.40, 0.230, "Compression"),
    ("VNQ", "Vanguard Real Estate ETF", "NYSE_ARCA", 92.40, 0.22, 0.240, "Mean-Reverting"),
    ("CPT", "Camden Property Trust", "NYSE", 118.50, 0.18, 0.220, "Compression"),
    ("SPG", "Simon Property Group", "NYSE", 172.40, 0.30, 0.236, "Expansion"),
    ("HST", "Host Hotels & Resorts", "NASDAQ", 18.20, 0.12, 0.250, "Mean-Reverting"),
    ("VICI", "VICI Properties", "NYSE", 33.10, 0.15, 0.210, "Compression"),
)

# Searchable company directory. No prices: these rows are names, not quotes.
NAMED_EQUITY_DIRECTORY: tuple[tuple[str, str, str], ...] = (
    ("BAC", "Bank of America Corporation", "NYSE"),
    ("WFC", "Wells Fargo & Company", "NYSE"),
    ("C", "Citigroup Inc.", "NYSE"),
    ("MS", "Morgan Stanley", "NYSE"),
    ("BLK", "BlackRock Inc.", "NYSE"),
    ("AXP", "American Express Company", "NYSE"),
    ("SCHW", "The Charles Schwab Corporation", "NYSE"),
    ("BX", "Blackstone Inc.", "NYSE"),
    ("SPGI", "S&P Global Inc.", "NYSE"),
    ("ICE", "Intercontinental Exchange Inc.", "NYSE"),
    ("CME", "CME Group Inc.", "NASDAQ"),
    ("MCO", "Moody's Corporation", "NYSE"),
    ("CB", "Chubb Limited", "NYSE"),
    ("PGR", "The Progressive Corporation", "NYSE"),
    ("ORCL", "Oracle Corporation", "NYSE"),
    ("CRM", "Salesforce Inc.", "NYSE"),
    ("IBM", "International Business Machines Corporation", "NYSE"),
    ("NOW", "ServiceNow Inc.", "NYSE"),
    ("SHOP", "Shopify Inc.", "NYSE"),
    ("UBER", "Uber Technologies Inc.", "NYSE"),
    ("RBLX", "Roblox Corporation", "NYSE"),
    ("DASH", "DoorDash Inc.", "NASDAQ"),
    ("INTC", "Intel Corporation", "NASDAQ"),
    ("CSCO", "Cisco Systems Inc.", "NASDAQ"),
    ("ADBE", "Adobe Inc.", "NASDAQ"),
    ("QCOM", "QUALCOMM Incorporated", "NASDAQ"),
    ("TXN", "Texas Instruments Incorporated", "NASDAQ"),
    ("AMAT", "Applied Materials Inc.", "NASDAQ"),
    ("MU", "Micron Technology Inc.", "NASDAQ"),
    ("INTU", "Intuit Inc.", "NASDAQ"),
    ("ADP", "Automatic Data Processing Inc.", "NASDAQ"),
    ("GOOG", "Alphabet Inc. Class C", "NASDAQ"),
    ("PYPL", "PayPal Holdings Inc.", "NASDAQ"),
    ("ABNB", "Airbnb Inc.", "NASDAQ"),
    ("HOOD", "Robinhood Markets Inc.", "NASDAQ"),
    ("SNAP", "Snap Inc.", "NYSE"),
    ("PINS", "Pinterest Inc.", "NYSE"),
    ("MARA", "MARA Holdings Inc.", "NASDAQ"),
    ("RIOT", "Riot Platforms Inc.", "NASDAQ"),
    ("TMUS", "T-Mobile US Inc.", "NASDAQ"),
    ("CMCSA", "Comcast Corporation", "NASDAQ"),
    ("SBUX", "Starbucks Corporation", "NASDAQ"),
    ("COST", "Costco Wholesale Corporation", "NASDAQ"),
    ("AMGN", "Amgen Inc.", "NASDAQ"),
    ("GILD", "Gilead Sciences Inc.", "NASDAQ"),
    ("ASML", "ASML Holding N.V.", "NASDAQ"),
    ("WMT", "Walmart Inc.", "NYSE"),
    ("TGT", "Target Corporation", "NYSE"),
    ("HD", "The Home Depot Inc.", "NYSE"),
    ("LOW", "Lowe's Companies Inc.", "NYSE"),
    ("NKE", "NIKE Inc.", "NYSE"),
    ("MCD", "McDonald's Corporation", "NYSE"),
    ("KO", "The Coca-Cola Company", "NYSE"),
    ("PEP", "PepsiCo Inc.", "NASDAQ"),
    ("PG", "The Procter & Gamble Company", "NYSE"),
    ("PM", "Philip Morris International Inc.", "NYSE"),
    ("MO", "Altria Group Inc.", "NYSE"),
    ("CL", "Colgate-Palmolive Company", "NYSE"),
    ("DIS", "The Walt Disney Company", "NYSE"),
    ("T", "AT&T Inc.", "NYSE"),
    ("VZ", "Verizon Communications Inc.", "NYSE"),
    ("F", "Ford Motor Company", "NYSE"),
    ("GM", "General Motors Company", "NYSE"),
    ("BA", "The Boeing Company", "NYSE"),
    ("CAT", "Caterpillar Inc.", "NYSE"),
    ("DE", "Deere & Company", "NYSE"),
    ("GE", "GE Aerospace", "NYSE"),
    ("HON", "Honeywell International Inc.", "NASDAQ"),
    ("UPS", "United Parcel Service Inc.", "NYSE"),
    ("UNP", "Union Pacific Corporation", "NYSE"),
    ("LMT", "Lockheed Martin Corporation", "NYSE"),
    ("RTX", "RTX Corporation", "NYSE"),
    ("NOC", "Northrop Grumman Corporation", "NYSE"),
    ("JNJ", "Johnson & Johnson", "NYSE"),
    ("PFE", "Pfizer Inc.", "NYSE"),
    ("MRK", "Merck & Co. Inc.", "NYSE"),
    ("ABBV", "AbbVie Inc.", "NYSE"),
    ("TMO", "Thermo Fisher Scientific Inc.", "NYSE"),
    ("DHR", "Danaher Corporation", "NYSE"),
    ("ABT", "Abbott Laboratories", "NYSE"),
    ("BMY", "Bristol-Myers Squibb Company", "NYSE"),
    ("CVS", "CVS Health Corporation", "NYSE"),
    ("CVX", "Chevron Corporation", "NYSE"),
    ("COP", "ConocoPhillips", "NYSE"),
    ("SLB", "Schlumberger Limited", "NYSE"),
    ("EOG", "EOG Resources Inc.", "NYSE"),
    ("PSX", "Phillips 66", "NYSE"),
    ("BABA", "Alibaba Group Holding Limited", "NYSE"),
    ("TSM", "Taiwan Semiconductor Manufacturing Company", "NYSE"),
    ("NVO", "Novo Nordisk A/S", "NYSE"),
    ("SAP", "SAP SE", "NYSE"),
    ("TM", "Toyota Motor Corporation", "NYSE"),
    ("SONY", "Sony Group Corporation", "NYSE"),
    ("SHEL", "Shell plc", "NYSE"),
    ("BP", "BP p.l.c.", "NYSE"),
    ("VTI", "Vanguard Total Stock Market ETF", "NYSE_ARCA"),
    ("VEA", "Vanguard FTSE Developed Markets ETF", "NYSE_ARCA"),
    ("VWO", "Vanguard FTSE Emerging Markets ETF", "NYSE_ARCA"),
    ("EEM", "iShares MSCI Emerging Markets ETF", "NYSE_ARCA"),
    ("EFA", "iShares MSCI EAFE ETF", "NYSE_ARCA"),
    ("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF", "NYSE_ARCA"),
    ("LQD", "iShares iBoxx $ Investment Grade Corporate Bond ETF", "NYSE_ARCA"),
    ("ARKK", "ARK Innovation ETF", "NYSE_ARCA"),
    ("SMH", "VanEck Semiconductor ETF", "NASDAQ"),
    ("XBI", "SPDR S&P Biotech ETF", "NYSE_ARCA"),
    ("KRE", "SPDR S&P Regional Banking ETF", "NYSE_ARCA"),
    ("XLV", "Health Care Select Sector SPDR Fund", "NYSE_ARCA"),
    ("XLI", "Industrial Select Sector SPDR Fund", "NYSE_ARCA"),
    ("XLY", "Consumer Discretionary Select Sector SPDR Fund", "NYSE_ARCA"),
    ("XLP", "Consumer Staples Select Sector SPDR Fund", "NYSE_ARCA"),
    ("XLU", "Utilities Select Sector SPDR Fund", "NYSE_ARCA"),
    ("XLRE", "Real Estate Select Sector SPDR Fund", "NYSE_ARCA"),
    ("IEMG", "iShares Core MSCI Emerging Markets ETF", "NYSE_ARCA"),
    ("AGG", "iShares Core U.S. Aggregate Bond ETF", "NYSE_ARCA"),
    ("BND", "Vanguard Total Bond Market ETF", "NASDAQ"),
)

NAMED_CRYPTO_DIRECTORY: tuple[tuple[str, str, str], ...] = (
    ("BCH-USD", "Bitcoin Cash", "COINBASE"),
    ("XLM-USD", "Stellar", "COINBASE"),
    ("ALGO-USD", "Algorand", "COINBASE"),
    ("ETC-USD", "Ethereum Classic", "COINBASE"),
)

# Search can find these. They are not exchange listings and have no quote.
UNLISTED_DIRECTORY: tuple[tuple[str, str], ...] = (
    ("SPACEX", "SpaceX — private company, not an exchange listing"),
    ("STRIPE", "Stripe — private company, not an exchange listing"),
    ("OPENAI", "OpenAI — private company, not an exchange listing"),
)

CATALOG_NOTICE = (
    "Named companies are a directory you can search. EQ#### and PERP### ids are placeholders, not missing companies. "
    "A private company such as SpaceX is marked not listed. Flagship prices are fixtures. This is not a live tradable universe."
)

# Flagship CME Group E-Mini & Micro Futures (Databento GLBX.MDP3)
FLAGSHIP_CME_FUTURES: tuple[tuple[str, str, str, float, float, float, float, float, str], ...] = (
    ("ES", "E-mini S&P 500 Futures (Front Month)", "CME", 0.25, 50.0, 2500.0, 5882.50, 0.45, "Compression"),
    ("NQ", "E-mini Nasdaq-100 Futures (Front Month)", "CME", 0.25, 20.0, 2000.0, 20545.25, 0.92, "Expansion"),
    ("YM", "E-mini Dow ($5) Futures (Front Month)", "CBOT", 1.00, 5.0, 1500.0, 43280.00, 0.38, "Compression"),
    ("RTY", "E-mini Russell 2000 Futures (Front Month)", "CME", 0.10, 50.0, 1500.0, 2264.40, 0.76, "Expansion"),
    ("CL", "Crude Oil WTI Futures (Front Month)", "NYMEX", 0.01, 1000.0, 1000.0, 71.45, -1.15, "Volatile Auction"),
    ("GC", "Gold Comex Futures (Front Month)", "COMEX", 0.10, 100.0, 2000.0, 2738.60, 0.88, "Expansion"),
    ("MES", "Micro E-mini S&P 500 Futures", "CME", 0.25, 5.0, 250.0, 5882.50, 0.45, "Compression"),
    ("MNQ", "Micro E-mini Nasdaq-100 Futures", "CME", 0.25, 2.0, 200.0, 20545.25, 0.92, "Expansion"),
    ("MYM", "Micro E-mini Dow Futures", "CBOT", 1.00, 0.5, 150.0, 43280.00, 0.38, "Compression"),
    ("M2K", "Micro E-mini Russell 2000 Futures", "CME", 0.10, 5.0, 150.0, 2264.40, 0.76, "Expansion"),
    ("MCL", "Micro WTI Crude Oil Futures", "NYMEX", 0.01, 100.0, 100.0, 71.45, -1.15, "Volatile Auction"),
    ("MGC", "Micro Gold Futures", "COMEX", 0.10, 10.0, 200.0, 2738.60, 0.88, "Expansion"),
    ("SI", "Silver Comex Futures", "COMEX", 0.005, 5000.0, 1500.0, 33.85, 1.72, "Expansion"),
    ("NG", "Henry Hub Natural Gas Futures", "NYMEX", 0.001, 10000.0, 1000.0, 2.42, -1.85, "Volatile Auction"),
    ("ZN", "10-Year US Treasury Note Futures", "CBOT", 0.015625, 1000.0, 1000.0, 111.75, -0.24, "Compression"),
    ("ZB", "30-Year US Treasury Bond Futures", "CBOT", 0.03125, 1000.0, 1000.0, 118.50, -0.38, "Compression"),
    ("6E", "Euro FX Futures", "CME", 0.00005, 125000.0, 1250.0, 1.0865, 0.18, "Compression"),
    ("6J", "Japanese Yen Futures", "CME", 0.0000005, 12500000.0, 1250.0, 0.00668, -0.31, "Mean-Reverting"),
    ("EUR_USD", "Euro / US Dollar Spot FX (ECB & Interbank)", "OTC_FX", 0.00001, 1.0, 100.0, 1.0865, 0.18, "Compression"),
    ("USD_CAD", "US Dollar / Canadian Dollar Spot FX (Bank of Canada & Interbank)", "OTC_FX", 0.00001, 1.0, 100.0, 1.4028, 0.12, "Compression"),
)

PRECIOUS_METALS_CATALOG: tuple[str, ...] = ("GC", "MGC", "SI", "GLD", "SLV")
COMMODITIES_CATALOG: tuple[str, ...] = ("GC", "MGC", "SI", "GLD", "SLV", "CL", "MCL", "NG")
ETFS_CATALOG: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV", "XLF", "XLK", "XLE", "SOXX", "MUB", "VTEB", "TFI", "HYMB", "CMF", "NYF",
    "SGOV", "BIL", "SHY", "IEF", "VOO", "VNQ", "VTI", "VEA", "VWO", "EEM", "EFA", "HYG", "LQD", "ARKK", "SMH", "XBI", "KRE",
    "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "IEMG", "AGG", "BND",
)
BONDS_RATES_CATALOG: tuple[str, ...] = (
    "TLT", "IEF", "SHY", "BIL", "SGOV", "AGG", "BND", "LQD", "HYG", "MUB", "VTEB", "TFI", "HYMB", "CMF", "NYF", "ZN", "ZB",
)
FX_CATALOG: tuple[str, ...] = ("EUR_USD", "USD_CAD", "6E", "6J")

ETF_SUBCATEGORY: dict[str, str] = {
    "GLD": "Precious Metals ETF", "SLV": "Precious Metals ETF",
    "SPY": "Broad Index ETF", "QQQ": "Broad Index ETF", "IWM": "Broad Index ETF", "DIA": "Broad Index ETF",
    "VOO": "Broad Index ETF", "VTI": "Broad Index ETF", "VEA": "International Index ETF", "VWO": "Emerging Markets ETF",
    "EEM": "Emerging Markets ETF", "EFA": "International Index ETF", "IEMG": "Emerging Markets ETF",
    "TLT": "Treasury & Bond ETF", "IEF": "Treasury & Bond ETF", "SHY": "Treasury & Bond ETF", "BIL": "Treasury & Bond ETF",
    "SGOV": "Treasury & Bond ETF", "AGG": "Treasury & Bond ETF", "BND": "Treasury & Bond ETF", "LQD": "Corporate Bond ETF",
    "HYG": "High-Yield Bond ETF", "MUB": "Municipal Bond ETF", "VTEB": "Municipal Bond ETF", "TFI": "Municipal Bond ETF",
    "HYMB": "Municipal Bond ETF", "CMF": "Municipal Bond ETF", "NYF": "Municipal Bond ETF",
    "XLK": "Sector & Thematic ETF", "XLF": "Sector & Thematic ETF", "XLE": "Sector & Thematic ETF",
    "XLV": "Sector & Thematic ETF", "XLI": "Sector & Thematic ETF", "XLY": "Sector & Thematic ETF",
    "XLP": "Sector & Thematic ETF", "XLU": "Sector & Thematic ETF", "XLRE": "Real Estate ETF", "VNQ": "Real Estate ETF",
    "SOXX": "Semiconductor ETF", "SMH": "Semiconductor ETF", "XBI": "Biotech ETF", "KRE": "Regional Banking ETF",
    "ARKK": "Innovation ETF",
}


def classify_catalog_category(symbol: str, asset_class: str, exchange: str = "") -> tuple[str, str]:
    """Return (primary_category, sub_category) for authentic asset catalog filtering and UI display."""
    sym = symbol.upper()
    if exchange.upper() == "UNLISTED":
        return ("unlisted", "Unlisted Private Company")
    if sym.startswith("EQ") and sym[2:].isdigit():
        return ("placeholder", "Directory Placeholder")
    if sym.startswith("PERP") and sym.endswith("-USD") and sym[4:-4].isdigit():
        return ("placeholder", "Directory Placeholder")
    if sym in PRECIOUS_METALS_CATALOG:
        return ("metals", "Precious Metals ETF" if sym in ETFS_CATALOG else "Precious Metals Futures")
    if sym in FX_CATALOG:
        return ("fx", "Spot FX" if sym in ("EUR_USD", "USD_CAD") else "CME FX Futures")
    if sym in ETFS_CATALOG:
        return ("etfs", ETF_SUBCATEGORY.get(sym, "Exchange-Traded Fund"))
    if asset_class == "futures":
        if sym in ("CL", "MCL", "NG"):
            return ("futures", "Energy Commodity Futures")
        if sym in ("ZN", "ZB"):
            return ("futures", "US Treasury Futures")
        return ("futures", "CME Equity Index Futures")
    if asset_class == "crypto_perps" or sym.endswith("-USD"):
        return ("crypto_perps", "Major Digital Asset")
    return ("equities", "US Listed Equity")

# Flagship CCXT Pro Crypto Perpetuals & Spot Pairs (Binance / Coinbase / Hyperliquid)
FLAGSHIP_CRYPTO_PERPS: tuple[tuple[str, str, str, float, float, float, str], ...] = (
    ("BTC-USD", "Bitcoin Perpetual Swap", "CCXT_PRO", 68410.00, 1.42, 0.312, "Expansion"),
    ("ETH-USD", "Ethereum Perpetual Swap", "COINBASE", 2645.50, 2.15, 0.278, "Expansion"),
    ("SOL-USD", "Solana Perpetual Swap", "HYPERLIQUID", 176.80, 3.18, 0.354, "Expansion"),
    ("BNB-USD", "BNB Perpetual Swap", "BINANCE", 598.40, 0.75, 0.235, "Compression"),
    ("XRP-USD", "XRP Perpetual Swap", "BINANCE", 0.5480, 1.12, 0.284, "Compression"),
    ("DOGE-USD", "Dogecoin Perpetual Swap", "BINANCE", 0.1445, 4.85, 0.392, "Expansion"),
    ("ADA-USD", "Cardano Perpetual Swap", "COINBASE", 0.3620, 0.94, 0.246, "Compression"),
    ("AVAX-USD", "Avalanche Perpetual Swap", "HYPERLIQUID", 28.40, 2.64, 0.328, "Expansion"),
    ("LINK-USD", "Chainlink Perpetual Swap", "COINBASE", 11.85, 1.88, 0.291, "Expansion"),
    ("SUI-USD", "Sui Network Perpetual Swap", "HYPERLIQUID", 2.08, 5.42, 0.412, "Expansion"),
    ("DOT-USD", "Polkadot Perpetual Swap", "BINANCE", 4.45, 0.62, 0.238, "Compression"),
    ("NEAR-USD", "NEAR Protocol Perpetual Swap", "HYPERLIQUID", 4.92, 2.95, 0.334, "Expansion"),
    ("LTC-USD", "Litecoin Perpetual Swap", "COINBASE", 71.20, 1.04, 0.229, "Compression"),
    ("UNI-USD", "Uniswap Perpetual Swap", "COINBASE", 7.85, 1.76, 0.282, "Expansion"),
    ("APT-USD", "Aptos Perpetual Swap", "HYPERLIQUID", 10.42, 3.85, 0.366, "Expansion"),
    ("ICP-USD", "Internet Computer Perpetual Swap", "BINANCE", 8.34, 1.22, 0.264, "Compression"),
    ("ARB-USD", "Arbitrum Perpetual Swap", "HYPERLIQUID", 0.584, 2.14, 0.315, "Expansion"),
    ("OP-USD", "Optimism Perpetual Swap", "HYPERLIQUID", 1.74, 2.48, 0.321, "Expansion"),
    ("INJ-USD", "Injective Perpetual Swap", "HYPERLIQUID", 21.60, 3.12, 0.348, "Expansion"),
    ("AAVE-USD", "Aave Protocol Perpetual Swap", "COINBASE", 154.80, 2.05, 0.296, "Expansion"),
    ("TIA-USD", "Celestia Perpetual Swap", "HYPERLIQUID", 6.12, 4.18, 0.384, "Expansion"),
    ("PEPE-USD", "Pepe 1000x Perpetual Swap", "HYPERLIQUID", 0.0104, 6.20, 0.448, "Volatile Auction"),
    ("WIF-USD", "dogwifhat Perpetual Swap", "HYPERLIQUID", 2.68, 5.75, 0.436, "Volatile Auction"),
    ("RENDER-USD", "Render Network Perpetual Swap", "BINANCE", 5.45, 2.84, 0.329, "Expansion"),
    ("FET-USD", "Artificial Superintelligence Perp", "BINANCE", 1.42, 3.10, 0.342, "Expansion"),
    ("SEI-USD", "Sei Network Perpetual Swap", "HYPERLIQUID", 0.465, 3.65, 0.358, "Expansion"),
    ("ATOM-USD", "Cosmos Hub Perpetual Swap", "COINBASE", 4.78, 0.54, 0.232, "Compression"),
    ("FIL-USD", "Filecoin Perpetual Swap", "COINBASE", 3.82, 0.88, 0.249, "Compression"),
    ("TON-USD", "Toncoin Perpetual Swap", "BINANCE", 5.24, 0.72, 0.241, "Compression"),
    ("HBAR-USD", "Hedera Perpetual Swap", "BINANCE", 0.0542, 1.15, 0.258, "Compression"),
)


class UniversalAssetCatalog:
    """Local directory: flagship fixtures, named companies, and EQ/PERP placeholders."""

    def __init__(self, target_equities_count: int = 10000, target_crypto_count: int = 520) -> None:
        self._lock = threading.RLock()
        self.target_equities_count = max(len(FLAGSHIP_EQUITIES), target_equities_count)
        self.target_crypto_count = max(len(FLAGSHIP_CRYPTO_PERPS), target_crypto_count)
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema_and_seed()

    def _init_schema_and_seed(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE catalog_assets (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    tick_size REAL NOT NULL,
                    lot_size REAL NOT NULL,
                    min_notional REAL NOT NULL,
                    track TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    last_price REAL NOT NULL,
                    change_pct REAL NOT NULL,
                    volume_1m REAL NOT NULL,
                    volume_24h REAL NOT NULL,
                    vpin REAL NOT NULL,
                    ofi_z REAL NOT NULL,
                    kyles_lambda REAL NOT NULL,
                    spread_bps REAL NOT NULL,
                    regime TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    priority_rank INTEGER NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX idx_catalog_track ON catalog_assets(track)")
            cur.execute("CREATE INDEX idx_catalog_class ON catalog_assets(asset_class)")
            cur.execute("CREATE INDEX idx_catalog_priority ON catalog_assets(priority_rank, symbol)")

            rows_to_insert: list[tuple[Any, ...]] = []

            # 1. Seed Flagship US Equities & ETFs
            for idx, (sym, name, exch, px, chg, vpin, regime) in enumerate(FLAGSHIP_EQUITIES):
                ofi_z = round((chg / 2.5) + 0.18, 3)
                rows_to_insert.append(
                    (
                        sym,
                        name,
                        "equities",
                        exch,
                        0.01,
                        1.0,
                        100.0,
                        "open_market",
                        1,
                        px,
                        chg,
                        round(18500.0 + idx * 420.0, 2),
                        round(14500000.0 + idx * 350000.0, 2),
                        vpin,
                        ofi_z,
                        0.0012,
                        1.4,
                        regime,
                        "synthetic_fixture",
                        1 + idx,
                    )
                )

            # 2. Seed Flagship CME Futures
            for idx, (sym, name, exch, tick_sz, lot_sz, min_not, px, chg, regime) in enumerate(
                FLAGSHIP_CME_FUTURES
            ):
                vpin = round(0.24 + (idx % 6) * 0.025, 3)
                ofi_z = round((chg / 1.8) + 0.22, 3)
                rows_to_insert.append(
                    (
                        sym,
                        name,
                        "futures",
                        exch,
                        tick_sz,
                        lot_sz,
                        min_not,
                        "competition",
                        1,
                        px,
                        chg,
                        round(9200.0 + idx * 310.0, 2),
                        round(8800000.0 + idx * 210000.0, 2),
                        vpin,
                        ofi_z,
                        0.0015,
                        1.8,
                        regime,
                        "synthetic_fixture",
                        10 + idx,
                    )
                )

            # 3. Seed Flagship CCXT Pro Crypto Perpetuals
            for idx, (sym, name, exch, px, chg, vpin, regime) in enumerate(FLAGSHIP_CRYPTO_PERPS):
                ofi_z = round((chg / 2.2) + 0.25, 3)
                provider = "synthetic_fixture"
                rows_to_insert.append(
                    (
                        sym,
                        name,
                        "crypto_perps",
                        exch,
                        0.01 if px > 10 else 0.0001,
                        0.001 if px > 1000 else 1.0,
                        10.0,
                        "competition",
                        1,
                        px,
                        chg,
                        round(32000.0 + idx * 540.0, 2),
                        round(48000000.0 + idx * 650000.0, 2),
                        vpin,
                        ofi_z,
                        0.0016,
                        3.2,
                        regime,
                        provider,
                        1 + idx,
                    )
                )

            # Named companies sit after the flagships and before the EQ/PERP placeholders.
            # Prices stay at zero: a name in this directory is not a quote.
            seeded = {row[0] for row in rows_to_insert}

            def _directory_row(
                sym: str,
                name: str,
                asset_class: str,
                exch: str,
                track: str,
                rank: int,
            ) -> tuple[Any, ...]:
                return (
                    sym,
                    name,
                    asset_class,
                    exch,
                    0.01,
                    1.0,
                    100.0 if asset_class == "equities" else 10.0,
                    track,
                    1,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    "Directory",
                    "synthetic_fixture",
                    rank,
                )

            for sym, name, exch in NAMED_EQUITY_DIRECTORY:
                if sym in seeded:
                    continue
                seeded.add(sym)
                rows_to_insert.append(_directory_row(sym, name, "equities", exch, "open_market", 70))

            for sym, name, exch in NAMED_CRYPTO_DIRECTORY:
                if sym in seeded:
                    continue
                seeded.add(sym)
                rows_to_insert.append(_directory_row(sym, name, "crypto_perps", exch, "competition", 70))

            for sym, name in UNLISTED_DIRECTORY:
                if sym in seeded:
                    continue
                seeded.add(sym)
                rows_to_insert.append(_directory_row(sym, name, "equities", "UNLISTED", "open_market", 71))

            # 4. Expand US NMS Equities & ETFs Universe to >= 10,000 assets
            remaining_equities = self.target_equities_count - len(FLAGSHIP_EQUITIES)
            exchanges_eq = ("NASDAQ", "NYSE", "NYSE_ARCA")
            regimes_eq = ("Compression", "Expansion", "Mean-Reverting", "Volatile Auction")
            sectors = ("Tech", "Bio", "Industrial", "FinTech", "Energy", "Aero", "Semi", "Cloud", "Quant", "Retail")
            for i in range(1, remaining_equities + 1):
                sym = f"EQ{i:04d}"
                sec = sectors[i % len(sectors)]
                exch = exchanges_eq[i % 3]
                px = round(18.50 + (i % 480) * 1.35, 2)
                chg = round(((i % 19) - 9) * 0.28, 2)
                vpin = round(0.19 + (i % 25) * 0.011, 3)
                ofi_z = round(chg * 0.35, 3)
                rows_to_insert.append(
                    (
                        sym,
                        f"US NMS {sec} Corp #{i:04d}",
                        "equities",
                        exch,
                        0.01,
                        1.0,
                        100.0,
                        "open_market",
                        1,
                        px,
                        chg,
                        round(1200.0 + (i % 80) * 45.0, 2),
                        round(950000.0 + (i % 200) * 12000.0, 2),
                        vpin,
                        ofi_z,
                        0.0014,
                        2.1,
                        regimes_eq[i % 4],
                        "polygon" if i % 2 == 0 else "databento",
                        200 + i,
                    )
                )

            # 5. Expand CCXT Pro Crypto Perpetuals Universe to >= 500 pairs
            remaining_crypto = self.target_crypto_count - len(FLAGSHIP_CRYPTO_PERPS)
            exchanges_cr = ("BINANCE", "COINBASE", "HYPERLIQUID")
            for i in range(1, remaining_crypto + 1):
                sym = f"PERP{i:03d}-USD"
                exch = exchanges_cr[i % 3]
                px = round(0.45 + (i % 150) * 1.85, 4)
                chg = round(((i % 23) - 10) * 0.42, 2)
                vpin = round(0.22 + (i % 28) * 0.012, 3)
                ofi_z = round(chg * 0.41, 3)
                rows_to_insert.append(
                    (
                        sym,
                        f"Liquid Crypto Perpetual #{i:03d} ({exch})",
                        "crypto_perps",
                        exch,
                        0.001,
                        1.0,
                        10.0,
                        "competition",
                        1,
                        px,
                        chg,
                        round(4500.0 + (i % 60) * 110.0, 2),
                        round(3200000.0 + (i % 120) * 45000.0, 2),
                        vpin,
                        ofi_z,
                        0.0018,
                        4.2,
                        regimes_eq[i % 4],
                        "ccxt_pro",
                        150 + i,
                    )
                )

            cur.executemany(
                """
                INSERT INTO catalog_assets VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                rows_to_insert,
            )
            self._conn.commit()

    def _apply_asset_class_filter(self, asset_class: str | None, clauses: list[str], params: list[Any]) -> None:
        if not asset_class or asset_class.lower() in ("all", ""):
            return
        ac = asset_class.lower().strip()
        if ac in ("metals", "gold_silver", "precious_metals"):
            placeholders = ",".join("?" for _ in PRECIOUS_METALS_CATALOG)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(PRECIOUS_METALS_CATALOG)
        elif ac == "commodities":
            placeholders = ",".join("?" for _ in COMMODITIES_CATALOG)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(COMMODITIES_CATALOG)
        elif ac in ("etf", "etfs"):
            placeholders = ",".join("?" for _ in ETFS_CATALOG)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(ETFS_CATALOG)
        elif ac in ("bonds", "rates", "bonds_rates"):
            placeholders = ",".join("?" for _ in BONDS_RATES_CATALOG)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(BONDS_RATES_CATALOG)
        elif ac == "fx":
            placeholders = ",".join("?" for _ in FX_CATALOG)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(FX_CATALOG)
        elif ac == "stocks":
            placeholders = ",".join("?" for _ in ETFS_CATALOG)
            clauses.append(f"asset_class = 'equities' AND symbol NOT LIKE 'EQ%' AND exchange != 'UNLISTED' AND symbol NOT IN ({placeholders})")
            params.extend(ETFS_CATALOG)
        elif ac == "authentic":
            clauses.append("symbol NOT LIKE 'EQ%' AND symbol NOT LIKE 'PERP%' AND exchange != 'UNLISTED'")
        else:
            clauses.append("asset_class = ?")
            params.append(ac)

    def universe_counts(self) -> dict[str, int]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT asset_class, COUNT(*) as cnt
                FROM catalog_assets
                WHERE is_active = 1
                GROUP BY asset_class
                """
            )
            by_class = {str(r["asset_class"]): int(r["cnt"]) for r in cur.fetchall()}
            total = sum(by_class.values())
            cur.execute(
                """
                SELECT COUNT(*) as cnt
                FROM catalog_assets
                WHERE is_active = 1
                  AND symbol NOT LIKE 'EQ%'
                  AND symbol NOT LIKE 'PERP%'
                  AND exchange != 'UNLISTED'
                """
            )
            authentic_cnt = int(cur.fetchone()["cnt"])
            return {
                "total_assets": total,
                "equities": by_class.get("equities", 0),
                "crypto_perps": by_class.get("crypto_perps", 0),
                "futures": by_class.get("futures", 0),
                "metals": len(PRECIOUS_METALS_CATALOG),
                "commodities": len(COMMODITIES_CATALOG),
                "etfs": len(ETFS_CATALOG),
                "bonds_rates": len(BONDS_RATES_CATALOG),
                "fx": len(FX_CATALOG),
                "authentic_assets": authentic_cnt,
            }

    def get_asset(self, symbol: str) -> CatalogAssetRecord | None:
        clean = symbol.strip().upper()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM catalog_assets WHERE symbol = ?", (clean,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def update_live_tick(
        self,
        *,
        symbol: str,
        last_price: float,
        vpin: float | None = None,
        ofi_z: float | None = None,
        kyles_lambda: float | None = None,
        regime: str | None = None,
    ) -> None:
        clean = symbol.strip().upper()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT last_price, change_pct, vpin, ofi_z, kyles_lambda, regime FROM catalog_assets WHERE symbol = ?", (clean,))
            row = cur.fetchone()
            if row is None:
                return
            prev_px = float(row["last_price"])
            delta_pct = ((last_price - prev_px) / max(1e-6, prev_px)) * 100.0
            new_chg = round(float(row["change_pct"]) + delta_pct, 2)
            cur.execute(
                """
                UPDATE catalog_assets
                SET last_price = ?,
                    change_pct = ?,
                    vpin = ?,
                    ofi_z = ?,
                    kyles_lambda = ?,
                    regime = ?
                WHERE symbol = ?
                """,
                (
                    round(last_price, 4),
                    new_chg,
                    round(vpin if vpin is not None else float(row["vpin"]), 4),
                    round(ofi_z if ofi_z is not None else float(row["ofi_z"]), 4),
                    round(kyles_lambda if kyles_lambda is not None else float(row["kyles_lambda"]), 6),
                    regime if regime is not None else str(row["regime"]),
                    clean,
                ),
            )
            self._conn.commit()

    def search(
        self,
        query: str = "",
        *,
        track: str | None = None,
        asset_class: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search the local synthetic directory; this is not a verified live universe."""
        t0 = time.perf_counter()
        q_clean = query.strip().upper()
        safe_limit = max(1, min(250, int(limit)))
        safe_offset = max(0, int(offset))

        clauses = ["is_active = 1"]
        where_params: list[Any] = []

        if track and track.lower() not in ("all", ""):
            clauses.append("track = ?")
            where_params.append(track.lower())

        self._apply_asset_class_filter(asset_class, clauses, where_params)

        if q_clean:
            clauses.append("(symbol LIKE ? OR UPPER(name) LIKE ? OR UPPER(exchange) LIKE ?)")
            like_prefix = f"{q_clean}%"
            like_contains = f"%{q_clean}%"
            where_params.extend([like_contains, like_contains, like_prefix])
            order_sql = """
                CASE
                    WHEN symbol = ? THEN 0
                    WHEN symbol LIKE ? THEN 1
                    ELSE 2
                END,
                priority_rank ASC,
                symbol ASC
            """
            order_params = [q_clean, like_prefix]
        else:
            order_sql = "priority_rank ASC, symbol ASC"
            order_params = []

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT * FROM catalog_assets
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(f"SELECT COUNT(*) as total FROM catalog_assets WHERE {where_sql}", where_params)
            total_matching = int(cur.fetchone()["total"])
            cur.execute(sql, [*where_params, *order_params, safe_limit, safe_offset])
            rows = [self._row_to_record(r).to_dict() for r in cur.fetchall()]

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "query": query,
            "track": track or "all",
            "asset_class": asset_class or "all",
            "count": len(rows),
            "total_matching": total_matching,
            "page_size": safe_limit,
            "offset": safe_offset,
            "query_latency_ms": elapsed_ms,
            "universe_counts": self.universe_counts(),
            "results": rows,
            "source": "synthetic_fixture",
            "is_live": False,
            "notice": CATALOG_NOTICE,
            "execution_permission": "none",
        }

    def snapshot(
        self,
        *,
        track: str | None = None,
        asset_class: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Paginated catalog snapshot with latest 1-minute close, volume, VPIN, OFI, and volatility regime."""
        t0 = time.perf_counter()
        safe_page = max(1, int(page))
        safe_size = max(1, min(250, int(page_size)))
        offset = (safe_page - 1) * safe_size

        clauses = ["is_active = 1"]
        params: list[Any] = []

        if track and track.lower() not in ("all", ""):
            clauses.append("track = ?")
            params.append(track.lower())

        self._apply_asset_class_filter(asset_class, clauses, params)

        where_sql = " AND ".join(clauses)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(f"SELECT COUNT(*) as total FROM catalog_assets WHERE {where_sql}", params)
            total_matching = int(cur.fetchone()["total"])

            cur.execute(
                f"""
                SELECT * FROM catalog_assets
                WHERE {where_sql}
                ORDER BY priority_rank ASC, symbol ASC
                LIMIT ? OFFSET ?
                """,
                [*params, safe_size, offset],
            )
            listings = [self._row_to_record(r).to_dict() for r in cur.fetchall()]

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "track": track or "all",
            "asset_class": asset_class or "all",
            "page": safe_page,
            "page_size": safe_size,
            "total_matching": total_matching,
            "query_latency_ms": elapsed_ms,
            "universe_counts": self.universe_counts(),
            "listings": listings,
            "source": "synthetic_fixture",
            "is_live": False,
            "notice": CATALOG_NOTICE,
            "execution_permission": "none",
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CatalogAssetRecord:
        return CatalogAssetRecord(
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            asset_class=row["asset_class"],
            exchange=str(row["exchange"]),
            tick_size=float(row["tick_size"]),
            lot_size=float(row["lot_size"]),
            min_notional=float(row["min_notional"]),
            track=row["track"],
            is_active=bool(row["is_active"]),
            last_price=float(row["last_price"]),
            change_pct=float(row["change_pct"]),
            volume_1m=float(row["volume_1m"]),
            volume_24h=float(row["volume_24h"]),
            vpin=float(row["vpin"]),
            ofi_z=float(row["ofi_z"]),
            kyles_lambda=float(row["kyles_lambda"]),
            spread_bps=float(row["spread_bps"]),
            regime=str(row["regime"]),
            provider=str(row["provider"]),
            priority_rank=int(row["priority_rank"]),
            execution_permission="none",
        )


GLOBAL_ASSET_CATALOG = UniversalAssetCatalog()

