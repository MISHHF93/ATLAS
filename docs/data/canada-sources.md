# Free, official data/paper sources for a Canadian individual (researched 2026-10-29)

Scope: US stocks and ETFs, TSX if possible, gold and index proxies, FX. Individual, personal, non-commercial use, a single owner viewing their own charts.
"Display for self" = the licence lets you show the data on your own private dashboard. Every row below links to the official page it was read from.
Anything I could not confirm from an official page is marked **VERIFY**. A few URLs (Massive request-limit article, FMP terms, IBKR paper page) were taken from search results and not opened individually.

## Headline findings
1. **Alpaca**: the docs say anyone globally can open a *paper-only* account and get IEX data
   (https://docs.alpaca.markets/us/docs/paper-trading). Live accounts are not open to Canadian residents
   (https://alpaca.markets/learn/live-trading-account-non-us), and the Alpaca forum (14 Aug 2026) says it does not sell market-data subscriptions to Canadian residents; target for individual Canadian accounts is about Nov 2026
   (https://forum.alpaca.markets/t/is-the-market-data-subscription-available-in-canada/19519). The owner reports they cannot get keys, so Alpaca is now **optional**, never required.
2. **Three providers ATLAS already listed as "free" are not usable for a stored, charted feed on their free plans**:
   - **Tiingo Starter**: ToS s1.6(a) forbids writing/saving/caching Tiingo data or derived products in any persistent storage, and s1.6(c) lists "dashboards, charts ... that display Tiingo Data" as prohibited (https://app.tiingo.com/tos/). The Power plan ($30/mo) allows personal storage. => not free-usable for ATLAS.
   - **Twelve Data Basic**: "internal non-display usage" only; charts need a paid individual plan (https://twelvedata.com/pricing, https://twelvedata.com/terms). Free exchanges are US + forex + crypto only, no TSX.
   - **Finnhub free**: 60 calls/min but `/stock/candle` is premium; free keys only get quotes (https://github.com/finnhubio/Finnhub-API/issues/546, https://finnhub.io/pricing).
3. **Best default primary for a Canadian individual: Massive (formerly Polygon.io) Stocks Basic** - free, instant signup, no brokerage account, personal display allowed.
   Limits: 5 REST calls/min, end-of-day bars only, 2 years of history, the current day is not available until after midnight ET.
   Signup: https://massive.com/dashboard/signup (product page https://massive.com/stocks).

## Source matrix
| Source | Canada eligibility | Free limits | Coverage | Display/storage licence | Official URLs |
|---|---|---|---|---|---|
| **Massive (Polygon) Stocks Basic** (RECOMMENDED primary) | Open signup; no residency gate found. Individuals' terms apply | 5 calls/min per asset class; EOD aggregates; 2 yr history; REST only | US stocks, ETFs (GLD/SPY/QQQ/IWM/DIA/SLV as index and gold proxies) | Personal, non-business, non-commercial. You may display for yourself; once another person can see it you need a Business plan. Display-only, no redistribution | https://massive.com/stocks , https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis , https://massive.com/knowledge-base/article/which-plan-do-i-need-to-show-massive-data-in-my-app , https://massive.com/legal/individuals-terms-of-service |
| **Alpha Vantage free** (fallback 1, TSX) | Free key by email, no gate | 25 requests/day; `TIME_SERIES_DAILY` compact (last 100 bars) only; `TIME_SERIES_INTRADAY` is premium | US + global equities; TSX with the `.TRT` suffix (confirm with SYMBOL_SEARCH); FX and gold spot daily endpoints | Personal, non-commercial; display on your own device allowed; no third-party access | https://www.alphavantage.co/support/api-key/ , https://www.alphavantage.co/documentation/ , https://www.alphavantage.co/terms_of_service/ |
| **Questrade API** (optional; the only Canadian-native source) | Needs a Questrade account in good standing (opening one is for Canadian residents); API Centre is free; practice accounts have a separate practice login and server. Funding not stated as required (**VERIFY** at signup) | Free API; `/markets/candles` up to 2,000 candles per call; without a paid data package quotes are snap quotes then delayed | TSX/TSXV and US stocks/ETFs; candles daily and intraday | Personal use under the API agreement; real-time needs a paid package | https://www.questrade.com/api , https://www.questrade.com/api/documentation/getting-started , https://www.questrade.com/api/documentation/rest-operations/market-calls/markets-candles-id |
| **IBKR Canada paper** (optional) | New IBKR Canada accounts include a paper account; TWS API needs TWS/IB Gateway running locally; the Web API needs a fully open, funded IBKR Pro account (so skip it). Real-time data needs a funded account | Free, but paper data is delayed: US stocks 15 min, US futures 10 min, metals and forex no delay | US stocks/ETFs, metals, FX, futures. Canadian-market API trading is restricted | Delayed data for personal use. **No ATLAS adapter yet** (needs `ib_async` + a local gateway) | https://www.interactivebrokers.ca/en/trading/papertrader-delayed-data.php , https://www.interactivebrokers.com/docs/tws-api/doc/md/delayed-data.md , https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/ |
| **OANDA practice** (FX + metals) | Canadians can open an OANDA Canada demo; v20 practice REST at https://api-fxpractice.oanda.com ; token from Hub -> Tools -> API | 120 req/s; free | FX majors, XAU_USD and other metals if OANDA Canada offers them to you (**VERIFY** the instrument list in your demo); intraday granularities | Practice data for personal use (**VERIFY** wording at signup) | https://www.oanda.com/ca-en/skills-and-insights/education/platforms-and-tools/oanda-platforms/how-to-create-oanda-demo-account/ , https://developer.oanda.com/rest-live-v20/development-guide/ |
| **Alpaca paper-only** (optional) | Docs: anyone globally can open paper-only; owner reports they cannot (**VERIFY**) | 200 req/min; IEX only | US stocks/ETFs incl. intraday | IEX feed, personal | https://docs.alpaca.markets/us/docs/paper-trading |
| Financial Modeling Prep free | Open signup | 250 calls/day, EOD, about 5 yr, US only | US | Standard terms bar public display, sharing and third-party access without a display licence. Private use only. Not implemented | https://site.financialmodelingprep.com/developer/docs/pricing , https://site.financialmodelingprep.com/developer/docs/terms-of-service |
| Tiingo Starter | Open signup | 50/hr, 1,000/day, 500 symbols/mo | US, ETFs, FX, crypto | **Persistent storage and chart display forbidden on the free plan** (see above) | https://app.tiingo.com/tos/ |
| Twelve Data Basic | Open signup | 8 credits/min, 800/day | US, forex, crypto (no TSX) | **Internal non-display only** | https://twelvedata.com/pricing |
| Finnhub free | Open signup | 60 calls/min | US quotes only | **No candles on the free plan** | https://finnhub.io/pricing |

## Keyless official sources (no signup, Canada-friendly)
| Source | What | URL |
|---|---|---|
| Bank of Canada Valet | USD/CAD and other CAD crosses, daily | https://www.bankofcanada.ca/valet/docs |
| ECB reference rates | EUR crosses, daily | https://data.ecb.europa.eu/help/api/data |
| SEC EDGAR | filings (needs a descriptive User-Agent, max 10 req/s) | https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| US Treasury FiscalData | yields, auctions (keyless) | https://fiscaldata.treasury.gov/api-documentation/ |
| GDELT | global news events (keyless) | https://www.gdeltproject.org/data.html |
| FRED | needs a free key (not keyless) | https://fred.stlouisfed.org/docs/api/api_key.html |

## What this means per asset class (Canadian owner, free only)
| Class | Primary | Fallbacks | Honest label |
|---|---|---|---|
| US stocks and ETFs | Massive Basic (EOD) | Alpha Vantage (100 daily bars, 25/day), Questrade, Alpaca (if the owner has keys) | Daily only, previous close; intraday needs Questrade, IBKR delayed or Alpaca |
| Gold, silver, indices | GLD / SLV / SPY / QQQ / DIA / IWM through the same chain | OANDA practice XAU_USD if offered | Labelled ETF proxy, not spot or index level |
| TSX / TSXV | Alpha Vantage `.TRT` (daily) | Questrade | No free keyless source; the only fully free route is Alpha Vantage at 25/day |
| FX | ECB (EUR_USD) / Bank of Canada (USD_CAD), daily, keyless | OANDA practice for intraday | Daily reference rates, not tradable quotes |
| Futures | none free and official | - | Blocked (Databento is paid, Yahoo unofficial) |
| Crypto | Alpaca crypto / Coinbase / Kraken keyless | - | Real time |

## Recommended path for the owner
1. **Sign up for Massive Basic** at https://massive.com/dashboard/signup (email only) and verify the key in Settings -> Setup. That alone fills every US stock/ETF/gold-proxy daily chart.
2. Add an **Alpha Vantage** key (https://www.alphavantage.co/support/api-key/) for a fallback and for TSX daily.
3. Optional: **OANDA practice** (FX/gold intraday), **Questrade** (TSX + intraday, requires an account) or **IBKR paper** (delayed intraday).
4. Do not use Tiingo / Twelve Data / Finnhub free keys for charting: their free terms prohibit it.

Caveats: provider terms change; each Verify action in Settings tests the key only once the owner enters it. Multi-user launch needs a Business licence from every provider above; free plans are single-owner, private display only.
