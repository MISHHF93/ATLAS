# Free data sources (hard rule: free + official APIs only)

ATLAS uses only data that costs nothing and comes from official APIs whose terms allow automated
personal use. No scraping, no unofficial endpoints. The policy lives in code at
`src/atlas/feeds/free_sources.py`. `AtlasFeed` refuses paid providers unless `ATLAS_ALLOW_PAID_DATA=true`,
and unofficial ones (Yahoo) unless `ATLAS_ALLOW_UNOFFICIAL_DATA=true`. Both flags are off by default.
Every stored bar is tagged with its `provider`. Latency (realtime / delayed_15m / eod / daily_reference) comes from
`free_sources.latency(provider)`, and the Settings → Integrations card shows it with the limits.

Alpaca stays on the free **Basic** plan: IEX feed only, 200 req/min (ATLAS caps itself at 180), and 30 websocket symbols.

| Asset class | Best free primary | Fallback | Limits | Terms note |
|---|---|---|---|---|
| US stocks / ETFs | Alpaca Basic (IEX, real time, paper keys) | Finnhub free (quotes), Tiingo free (EOD/IEX), Massive/Polygon Basic (EOD), Alpha Vantage (25/day), FMP (250/day) | Alpaca 200/min; Finnhub 60/min; Tiingo 50/h, 1000/day | IEX is about 2–3% of volume; SIP needs a paid plan (not used). Tiingo free is personal use only. |
| Crypto | Alpaca crypto (keyless history, real time) | Coinbase, Kraken public APIs; Binance/OKX/Bybit where legal | Alpaca 200/min; Kraken ~1 req/s | Binance.com is geo-restricted in Ontario/US. Public market-data endpoints need no key. |
| Gold | OANDA practice XAU/USD (CFD price, real time) | Twelve Data free (XAU/USD, delayed) | OANDA practice is free with a demo account | **Gap:** CME GC futures data is licensed; the LBMA price is licensed (no free API). OANDA is a CFD proxy, not the exchange price. |
| Futures | none free and official | CFTC COT (weekly positioning, Socrata, keyless) | — | **Gap:** CME real time/delayed is licensed. Yahoo futures are unofficial and excluded. |
| Forex | OANDA practice (real time) | Twelve Data / Finnhub free; Bank of Canada Valet (`boc_valet`, `USD_CAD` daily reference, keyless); European Central Bank Data Portal (`ecb_fx`, `EUR_USD` / `USD_CAD` daily reference, keyless) | BoC & ECB: ATLAS caps 1 req/s | Both BoC Valet (`www.bankofcanada.ca/valet`) and ECB Data Portal (`data-api.ecb.europa.eu` with `certifi` TLS + `eurofxref` XML fallback) are official keyless central-bank reference feeds. |
| Indices | ETF proxies via Alpaca (SPY, QQQ, DIA, IWM) | FRED daily index series (SP500, NASDAQCOM, DJIA) | FRED 120/min | **Gap:** licensed index levels (S&P/Dow/TMX) are not free real time. |
| Options | Alpaca Basic indicative options feed | Tradier sandbox (delayed 15m) | Tradier sandbox 60/min | OPRA real time is paid (not used). |
| Fundamentals | SEC EDGAR (keyless, User-Agent with an email required) | FMP free, Finnhub free | EDGAR 10 req/s | SEC fair-access policy: you must declare a User-Agent. |
| Macro | FRED/ALFRED (free key) | Treasury Fiscal Data, BLS, BEA (free keys), BoC Valet | FRED 120/min; BLS v2 500/day | All are official government APIs. |
| News | Alpaca news (Basic) | Finnhub company news (free) | per provider | Headlines only; no full-text redistribution. |

## Excluded
- **Paid (not used):** Databento, IBKR market data, EODHD paid plans, CME/TMX licensed feeds, Alpaca Algo Trader Plus (SIP), Polygon/Massive paid tiers.
- **Unofficial (not used):** Yahoo Finance chart endpoints, and Stooq CSV downloads (no published API terms).

## Free keys to register
Required: `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (paper), `ATLAS_SEC_USER_AGENT` (your name and email, no key), `FRED_API_KEY`.
Optional: `FINNHUB_API_KEY`, `TIINGO_API_KEY`, `TWELVEDATA_API_KEY`, `ALPHAVANTAGE_API_KEY`, `FMP_API_KEY`,
`POLYGON_API_KEY`/`MASSIVE_API_KEY`, `OANDA_API_TOKEN` + `OANDA_ACCOUNT_ID` (practice), `TRADIER_ACCESS_TOKEN` (sandbox).
Registration links are next to each key in `.env.example`.


## evo-12: what serves each asset class today
Check it live at Settings, Connectors, "Data coverage" (`GET /api/feeds/catalog-health`).

| Class | Keyless today | Free key that unlocks it |
|---|---|---|
| Crypto | Alpaca crypto history, Binance, OKX and others (official public endpoints) | none |
| FX daily | ECB reference rates (EUR crosses), Bank of Canada Valet (USD/CAD): daily only, labelled | Oanda practice, Twelve Data, Finnhub for intraday |
| Stocks and ETFs (incl. GLD, SLV, SPY, QQQ) | none (official sources all require a free key) | Alpaca paper (IEX free feed, primary), else Tiingo, Finnhub, Twelve Data, Polygon, Tradier, Alpha Vantage |
| Gold / silver spot, index levels | none | GLD, SLV, SPY, QQQ, DIA, IWM are the labelled free stand-ins once a stock key exists |
| Futures (GC, SI, ES, ...) | none | Databento is paid and stays off |

Yahoo's chart endpoint is unofficial and is blocked by the data policy (`ATLAS_ALLOW_UNOFFICIAL_DATA`); bars stored from it earlier are ignored on read. Enabling it is an owner decision about Yahoo's terms, not a default.
Keys are re-read on every provider use, so saving a key in Settings, Setup is enough; open a chart or run `scripts/backfill_feeds.py` to fill bars.
