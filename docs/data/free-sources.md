# Free data sources (hard rule: free + official APIs only)

ATLAS uses only data that costs nothing and comes from official APIs whose terms allow automated
personal use. No scraping, no unofficial endpoints. The policy lives in code at
`src/atlas/feeds/free_sources.py`. `AtlasFeed` refuses paid providers unless `ATLAS_ALLOW_PAID_DATA=true`,
and unofficial ones (Yahoo) unless `ATLAS_ALLOW_UNOFFICIAL_DATA=true`. Both flags are off by default.
Every stored bar is tagged with its `provider`. Latency (realtime / delayed_15m / eod / daily_reference) comes from
`free_sources.latency(provider)`, and the Settings → Integrations card shows it with the limits.

**Stock and ETF source (evo-13):** `ATLAS_STOCK_PROVIDER` picks the primary; the default is **Massive (formerly Polygon) Stocks Basic**, because it is free,
needs only an email (no brokerage account, so it works for a Canadian resident) and its free terms allow showing data on your own private dashboard.
The automatic chain is `massive/polygon → alphavantage → questrade → tradier → alpaca → yahoo(policy-blocked)`. **Alpaca is optional** (it does not serve
Canadian residents); if you have keys, set `ATLAS_STOCK_PROVIDER=alpaca`. Tiingo, Twelve Data and Finnhub are never auto-chained: their free plans forbid
storage/chart display, or are non-display, or have no candles. Name one in `ATLAS_STOCK_PROVIDER` only if you hold a plan that allows it. Free plans cover one
private owner; showing data to other users needs a business data licence. Details and sources: `docs/data/canada-sources.md`.
Free plan limits: Massive 5 calls/min, end-of-day bars only (daily charts, previous close); Alpha Vantage 25 calls/day, last 100 daily bars. Set `ATLAS_<PROVIDER>_PLAN=paid` once you pay and intraday intervals are used.
Alpaca on the free **Basic** plan: IEX feed only, 200 req/min (ATLAS caps itself at 180), and 30 websocket symbols.

| Asset class | Best free primary | Fallback | Limits | Terms note |
|---|---|---|---|---|
| US stocks / ETFs | Massive/Polygon Stocks Basic (EOD, free, email signup) | Alpha Vantage (25/day), Questrade, Tradier sandbox, Alpaca Basic (IEX, optional) | Massive 5/min; Alpha Vantage 25/day; Alpaca 200/min | Daily bars only on free plans. Tiingo/Twelve Data/Finnhub free plans are excluded from the automatic chain (storage/display or candles not allowed). |
| Crypto | Alpaca crypto history endpoint (keyless, real time) | Coinbase, Kraken public APIs; Binance/OKX/Bybit where legal | Alpaca 200/min; Kraken ~1 req/s | Binance.com is geo-restricted in Ontario/US. Public market-data endpoints need no key. |
| Gold | OANDA practice XAU/USD (CFD price, real time) | Twelve Data free (XAU/USD, delayed) | OANDA practice is free with a demo account | **Gap:** CME GC futures data is licensed; the LBMA price is licensed (no free API). OANDA is a CFD proxy, not the exchange price. |
| Futures | none free and official | CFTC COT (weekly positioning, Socrata, keyless) | — | **Gap:** CME real time/delayed is licensed. Yahoo futures are unofficial and excluded. |
| Forex | OANDA practice (real time) | Twelve Data / Finnhub free; Bank of Canada Valet (`boc_valet`, `USD_CAD` daily reference, keyless); European Central Bank Data Portal (`ecb_fx`, `EUR_USD` / `USD_CAD` daily reference, keyless) | BoC & ECB: ATLAS caps 1 req/s | Both BoC Valet (`www.bankofcanada.ca/valet`) and ECB Data Portal (`data-api.ecb.europa.eu` with `certifi` TLS + `eurofxref` XML fallback) are official keyless central-bank reference feeds. |
| Indices | ETF proxies via the stock source (SPY, QQQ, DIA, IWM) | FRED daily index series (SP500, NASDAQCOM, DJIA) | FRED 120/min | **Gap:** licensed index levels (S&P/Dow/TMX) are not free real time. |
| Options | Alpaca Basic indicative options feed | Tradier sandbox (delayed 15m) | Tradier sandbox 60/min | OPRA real time is paid (not used). |
| Fundamentals | SEC EDGAR (keyless, User-Agent with an email required) | FMP free, Finnhub free | EDGAR 10 req/s | SEC fair-access policy: you must declare a User-Agent. |
| Macro | FRED/ALFRED (free key) | Treasury Fiscal Data, BLS, BEA (free keys), BoC Valet | FRED 120/min; BLS v2 500/day | All are official government APIs. |
| News | Alpaca news (Basic) | Finnhub company news (free) | per provider | Headlines only; no full-text redistribution. |

## Excluded
- **Paid (not used):** Databento, IBKR market data, EODHD paid plans, CME/TMX licensed feeds, Alpaca Algo Trader Plus (SIP), Polygon/Massive paid tiers.
- **Unofficial (not used):** Yahoo Finance chart endpoints, and Stooq CSV downloads (no published API terms).

## Free keys to register
Recommended: `POLYGON_API_KEY` (a Massive key, https://massive.com/dashboard/signup), `ATLAS_SEC_USER_AGENT` (your name and email, no key), `FRED_API_KEY`. Optional: `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (paper; not available to Canadian residents). None are set for you: each shows Needs verification until you enter it and press Verify.
Optional: `FINNHUB_API_KEY`, `TIINGO_API_KEY`, `TWELVEDATA_API_KEY`, `ALPHAVANTAGE_API_KEY`, `FMP_API_KEY`,
`POLYGON_API_KEY`/`MASSIVE_API_KEY`, `OANDA_API_TOKEN` + `OANDA_ACCOUNT_ID` (practice), `TRADIER_ACCESS_TOKEN` (sandbox).
Registration links are next to each key in `.env.example`.


## evo-12: what serves each asset class today
Check it live at Settings, Connectors, "Data coverage" (`GET /api/feeds/catalog-health`).

| Class | Keyless today | Free key that unlocks it |
|---|---|---|
| Crypto | Alpaca crypto history, Binance, OKX and others (official public endpoints) | none |
| FX daily | ECB reference rates (EUR crosses), Bank of Canada Valet (USD/CAD): daily only, labelled | Oanda practice, Twelve Data, Finnhub for intraday |
| Stocks and ETFs (incl. GLD, SLV, SPY, QQQ) | none (official sources all require a free key) | Massive/Polygon Basic (primary, daily), Alpha Vantage, Questrade, Tradier, Alpaca (optional) |
| Gold / silver spot, index levels | none | GLD, SLV, SPY, QQQ, DIA, IWM are the labelled free stand-ins once a stock key exists |
| Futures (GC, SI, ES, ...) | none | Databento is paid and stays off |

Yahoo's chart endpoint is unofficial and is blocked by the data policy (`ATLAS_ALLOW_UNOFFICIAL_DATA`); bars stored from it earlier are ignored on read. Enabling it is an owner decision about Yahoo's terms, not a default.
Keys are re-read on every provider use, so saving a key in Settings, Setup is enough; open a chart or run `scripts/backfill_feeds.py` to fill bars.


## evo-13: keyless context (no key, official, read-only)
`GET /api/context/{sources,calendar,filings,news,rss}` and Research, Macro & news. Economic calendar from the BLS release schedule (iCalendar) and US Treasury
FiscalData auctions; FRED release dates only once a verified `FRED_API_KEY` exists (otherwise the source reads Needs verification). SEC EDGAR filings need only
`ATLAS_SEC_USER_AGENT`. Official RSS: Federal Reserve, SEC, Bank of Canada. GDELT headlines are limited to one request per 5 seconds. A failing source says so;
nothing is estimated. Auction times are not in the Treasury dataset, so those rows show a date only.
