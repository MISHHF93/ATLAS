"""The UI universe: every symbol any ATLAS screen lists (ticker tape, /api/listings, market list, watchlists, trade desk,
library page) mapped to an ATLAS feed instrument. ``tests/feeds/test_live_quotes.py`` asserts that every symbol the UI
catalog/listings expose is in here, so a new UI symbol without a feed series fails CI instead of showing a fake price.

Symbols are kept here as plain data (no import of atlas.marketdata) so the feed layer stays at the bottom of the stack.
"""
from __future__ import annotations

from .contracts import CONTRACT_TERMS
from .instruments import Instrument

from .stock_providers import equity_priority as _equity_priority

# Default chain (Canada-eligible primary first). InstrumentMaster.get() re-resolves it per call from ATLAS_STOCK_PROVIDER.
EQUITY_PRIORITY = _equity_priority({})
EQUITY_PROVIDERS = ("alpaca", "tiingo", "polygon", "finnhub", "twelvedata", "alphavantage", "questrade", "yahoo")

# US equities and ETFs (catalog flagships + named directory + /api/listings).
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV", "XLF", "XLK", "XLE", "SOXX", "MUB", "VTEB", "TFI", "HYMB", "CMF", "NYF",
    "SGOV", "BIL", "SHY", "IEF", "VOO", "VNQ", "VTI", "VEA", "VWO", "EEM", "EFA", "HYG", "LQD", "ARKK", "SMH", "XBI", "KRE",
    "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "IEMG", "AGG", "BND",
}
STOCKS = (
    "NVDA AAPL MSFT TSLA AMZN META GOOGL AMD AVGO NFLX JPM GS PLTR COIN MSTR SMCI ARM CRWD PANW SNOW LLY UNH V MA XOM CPT "
    "SPG HST VICI BAC WFC C MS BLK AXP SCHW BX SPGI ICE CME MCO CB PGR ORCL CRM IBM NOW SHOP UBER RBLX DASH INTC CSCO ADBE "
    "QCOM TXN AMAT MU INTU ADP GOOG PYPL ABNB HOOD SNAP PINS MARA RIOT TMUS CMCSA SBUX COST AMGN GILD ASML WMT TGT HD LOW "
    "NKE MCD KO PEP PG PM MO DIS T VZ F GM BA CAT DE GE HON UPS UNP LMT RTX NOC JNJ PFE MRK ABBV TMO DHR ABT BMY CVS CVX COP "
    "SLB EOG PSX BABA TSM NVO SAP TM SONY SHEL BP ROK CEG OKLO VST RKLB SOFI ENPH"
).split()

# CME futures the catalog/desk shows (GC/MGC/SI/ES terms come from feeds.contracts, the single source) -> Yahoo continuous front month (unofficial, delayed).
FUTURES = {
    "ES": ("E-mini S&P 500", *CONTRACT_TERMS["ES"]), "NQ": ("E-mini Nasdaq-100", 0.25, 20), "YM": ("E-mini Dow", 1.0, 5),
    "RTY": ("E-mini Russell 2000", 0.1, 50), "CL": ("WTI crude oil", 0.01, 1000), "GC": ("Gold", *CONTRACT_TERMS["GC"]),
    "MES": ("Micro E-mini S&P 500", 0.25, 5), "MNQ": ("Micro E-mini Nasdaq-100", 0.25, 2), "MYM": ("Micro E-mini Dow", 1.0, 0.5),
    "M2K": ("Micro E-mini Russell 2000", 0.1, 5), "MCL": ("Micro WTI crude", 0.01, 100), "MGC": ("Micro gold", *CONTRACT_TERMS["MGC"]),
    "SI": ("Silver", *CONTRACT_TERMS["SI"]), "NG": ("Henry Hub natural gas", 0.001, 10000), "ZN": ("10Y T-Note", 0.015625, 1000),
    "ZB": ("30Y T-Bond", 0.03125, 1000), "6E": ("Euro FX", 0.00005, 125000), "6J": ("Japanese yen", 0.0000005, 12500000),
}

# Crypto bases the UI lists as "<BASE>-USD". The feed series id stays <BASE>USDT (legacy id, keeps stored history, models and URLs),
# but the data is Coinbase/Kraken USD spot (feeds.crypto_venues). A base with no Coinbase/Kraken listing has an empty chain.
CRYPTO = ("BTC ETH SOL BNB XRP DOGE ADA AVAX LINK SUI DOT NEAR LTC UNI APT ICP ARB OP INJ AAVE TIA PEPE WIF RENDER FET SEI "
          "ATOM FIL TON HBAR BCH XLM ALGO ETC").split()

FX_ALIASES = {
    "EUR_USD": "EUR_USD", "EURUSD": "EUR_USD", "EUR/USD": "EUR_USD", "EUR-USD": "EUR_USD",
    "USD_CAD": "USD_CAD", "USDCAD": "USD_CAD", "USD/CAD": "USD_CAD", "USD-CAD": "USD_CAD",
    "XAU_USD": "GC", "XAUUSD": "GC", "XAU/USD": "GC", "XAU-USD": "GC", "GOLD": "GC",
    "XAG_USD": "SI", "XAGUSD": "SI", "XAG/USD": "SI", "XAG-USD": "SI", "SILVER": "SI",
}


def crypto_instrument(base: str) -> Instrument:
    from .crypto_venues import crypto_fields
    sym = f"{base}USDT"
    f = crypto_fields(base)
    return Instrument(sym, "crypto", "COINBASE", "USD", "UTC", "24x7", 0.00000001, 0.00001, **f)


def equity_instrument(sym: str) -> Instrument:
    etf = sym in ETFS
    return Instrument(sym, "etf" if etf else "equity", "XNYS", "USD", "America/New_York", "us_equity_rth", 0.01, 1,
                      provider_symbols={p: (sym.replace(".", "-") if p == "yahoo" else sym) for p in EQUITY_PROVIDERS},
                      provider_priority=EQUITY_PRIORITY, sanity_providers=("yahoo", "alpaca"), description=sym)


def future_instrument(root: str) -> Instrument:
    desc, tick, mult = FUTURES[root]
    return Instrument(root, "future", "XCME", "USD", "America/Chicago", "cme_globex", tick, 1, mult,
                      provider_symbols={"databento": f"{root}.c.0", "yahoo": f"{root}=F"}, provider_priority=("databento", "yahoo"),
                      description=f"{desc} continuous front month")


def ui_instruments() -> dict[str, Instrument]:
    out: dict[str, Instrument] = {}
    for s in sorted(ETFS) + STOCKS:
        out[s] = equity_instrument(s)
    for b in CRYPTO:
        i = crypto_instrument(b)
        out[i.id] = i
    for r in FUTURES:
        i = future_instrument(r)
        out[i.id] = i
    return out


def resolve(symbol: str) -> str | None:
    """UI symbol -> feed instrument id (BTC-USD -> BTCUSDT, ES1! -> ES, AAPL -> AAPL). None if not in the universe."""
    s = (symbol or "").strip().upper()
    if s in FX_ALIASES:
        return FX_ALIASES[s]
    if s.endswith("-USD") and s[:-4] in CRYPTO:
        return f"{s[:-4]}USDT"
    if s.endswith("USDT") and s[:-4] in CRYPTO:
        return s
    if s.endswith("USD") and s[:-3] in CRYPTO:
        return f"{s[:-3]}USDT"
    if s in FUTURES:
        return s
    if s.endswith("1!") and s[:-2] in FUTURES:
        return s[:-2]
    if s in ETFS or s in STOCKS:
        return s
    return None


def ui_symbols() -> list[str]:
    return sorted(ETFS) + STOCKS + [f"{b}-USD" for b in CRYPTO] + list(FUTURES)
