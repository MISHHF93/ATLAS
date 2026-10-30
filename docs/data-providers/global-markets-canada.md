# Global markets from Canada: official, free, personal-use + ML-eligible data (research, checked 2026-10-30)

Request (evo-19): "we are traders in Canada; the bot should enter all markets and fetch all data." This page records what the official
documentation and terms actually permit. **Rule:** an adapter exists only where the provider's own terms allow automated personal
use and the source is free and official. No key is set anywhere; every keyed source is **needs verification** until the owner supplies
and verifies one. Paper only; ML `execution_permission` stays `none`; `ATLAS_ALLOW_UNOFFICIAL_DATA` and `ATLAS_ALLOW_PAID_DATA` stay off.
"All markets" is therefore **not** achievable for free and official terms. Exchange feeds are licensed products. Gaps stay visible
as "no feed" and nothing is fabricated or scraped.

Legend. Status: **wired** = adapter in the registry and working today; **fixture** = adapter written, tested against recorded fixtures only,
never run against the live service with a key; **needs verification** = keyed, key unset; **none** = no adapter, reason given.
ML column: whether the series may enter model training. "Context" means display / risk context only.

## Coverage matrix

| Market | Source (official docs) | Free? | Terms for personal use + ML | ATLAS status |
|---|---|---|---|---|
| US equities / ETFs (EOD, 2y) | Massive (ex-Polygon) free plan | Free key, 5 calls/min, EOD lag | Keyed, personal use. Free plan has no websocket/snapshot use. | **wired** (key set by the owner) |
| US equities / ETFs (bars) | Alpaca Basic (IEX), Tiingo, Finnhub, Twelve Data, Alpha Vantage | Free keys, strict caps | Several free plans forbid storage / chart display (see `free_sources.py`) so they are out of the automatic chain | **wired**, not in the default chain; keys needs verification |
| US + Canadian equities, ETFs, options (L1 quotes, candles) | Questrade API | Free with a Questrade account (OAuth); 20 req/s, 15,000/h | Account holder only; real-time needs a paid package, so quotes may be delayed. Not an ML-training licence | **fixture** adapter, `QUESTRADE_*` unset: needs verification |
| TSX / TSXV (intraday) | TMX Datalinx / TMX Info Services | Paid | Distribution/subscriber agreement; delayed means at least 15 min | **none** (licence) |
| TSX / TSXV / NEO (EOD, 30-day lookback) | TMX Analytics free plan | Free plan after registration (email, password, `x-api-key`), bearer token valid 1 h | Attribution required. **ML use not stated**; billing "in arrears with overage" is documented, so a runaway loop could cost money | **none yet**: `TMXStub` documents it; endpoint/response schema not verified, no adapter written |
| CSE (Canadian Securities Exchange) | CSE market data via authorised vendors | Paid via vendors | Executed market-information agreement | **none** (licence) |
| Cboe Canada | Authorised vendors / extranet | Retail real time on the web only | No public API | **none** |
| US options | OPRA via vendors; Cboe All Access | Paid (14-day trial only) | Licensed | **none**. Option quotes only through Questrade (above) |
| Futures (CME/ICE/CBOT/NYMEX) | CME / ICE | Paid | Licensed; vendor agreement | **none** (see `futures-canada-sources.md`; OANDA CFD proxy once a token is verified) |
| FX majors + CAD crosses | OANDA practice v20 (`api-fxpractice.oanda.com`) | Free practice account | Personal practice token; **no token given** | **wired**, key unset: needs verification |
| FX daily reference | Bank of Canada Valet (USD/CAD etc.), ECB | Keyless | BoC terms (no overload); ECB reuse with attribution | **wired** (`boc_valet`, `ecb_fx`) |
| Crypto spot | Coinbase, Kraken, OKX public REST/WS; Binance and Bybit public (Binance is geo-restricted in Ontario) | Free, keyless | Public market data, rate limits per `free_sources.py` | **wired** |
| Canadian-registered crypto exchanges | Newton: web prices, no documented API. Coinsquare: API docs on request only. Bitbuy: no longer serves Canadians (now Robinhood). | n/a | No public documented market-data API | **none**; Kraken and Coinbase (registered in Canada) cover the data |
| Metals | OANDA XAU/XAG CFD proxy; GLD/SLV via equities; EIA none | see above | LBMA/COMEX are licensed | **wired** via OANDA (key unset: needs verification); no free official daily spot-gold source |
| Energy benchmarks (WTI, Brent, Henry Hub spot) | EIA Open Data API v2 | Free key | US-government work, public domain; attribute EIA | **fixture** `eia`, `EIA_API_KEY` unset: needs verification. Spot, **not** futures |
| Rates, US | US Treasury Daily Par Yield Curve XML | Keyless | Public domain (CC0 on data.gov) | **wired as adapter** `us_treasury` (fixture-tested, live endpoint reachable) |
| Rates, Canada | Bank of Canada Valet GoC benchmark yields | Keyless | BoC terms (cache, no overload) | **wired as adapter** `boc_rates` (fixture-tested, live endpoint reachable) |
| Macro (FRED) | FRED | Free key | **Terms prohibit AI training/archival** | **wired**, display/risk context only. **Never enters ML training.** |
| London (LSE) | LSE market data | Paid / licensed | AI use is "Other Non-Display Usage" under 2026 policy; entitlement controls, audit | **none** |
| Euronext | Euronext Data | Delayed free for internal use only | Redistribution licensed; EMDA terms | **none** |
| Xetra / Deutsche Boerse | Deutsche Boerse market data | 15-min delayed free only if not commercialised | Licence for any onward or paid use | **none** |
| Tokyo (JPX) | JPX 15-min delayed API | Paid (JPY 80,000 per month plus fees) | Redistribution needs permission | **none** |
| Hong Kong (HKEX) | HKEX vendor licence | Paid | Delayed data only via licensed vendors, delay must be shown | **none** |
| Australia (ASX) | ASX market information | Paid | Licence; 20-min delay, top of market | **none** |
| India (NSE) | NSE market data policy | Free for internal employee use only | Licence for external use | **none** |

Indices and single names outside North America are reachable at personal level only through a broker you hold an account
with (for example an IBKR account with paid subscriptions: `ibkr` is a documented stub). That is the user's decision, not a free API.

## What was implemented in evo-19

New adapters in `src/atlas/feeds/providers/rates.py`, all daily **series** (never bars, never trade series, never an order path):

| Adapter | Source | Series ids | Key |
|---|---|---|---|
| `us_treasury` | US Treasury par yield XML (Atom) | `UST_1M` .. `UST_30Y` (9 tenors) | none |
| `boc_rates` | BoC Valet `BD.CDN.*.DQ.YLD` | `CAN_2Y`, `CAN_3Y`, `CAN_5Y`, `CAN_7Y`, `CAN_10Y`, `CAN_LONG` | none |
| `eia` | EIA v2 `petroleum/pri/spt` (WTI, Brent), `natural-gas/pri/fut` (Henry Hub spot) | `EIA_WTI_SPOT`, `EIA_BRENT_SPOT`, `EIA_HENRYHUB_SPOT` | `EIA_API_KEY` (unset: needs verification) |

- Catalog: `src/atlas/feeds/reference_series.py`, 18 reference series, `trade_series=false`, `execution_permission=none`,
  `ml_training=research_features_only`. Exposed read-only (no vendor call, no key shown) at `GET /api/feeds/reference-series`.
- Gate: all three are listed in `free_sources.py` (free, official). Rate limit is 1 request per second per adapter. Requests are one month or one year at a time.
- Not added, with reasons: TMX Analytics (ML terms unstated, usage billing, schema unverified), every exchange feed above (licensed), Newton/Coinsquare
  (no public documentation), Stooq (non-commercial, CAPTCHA key), Yahoo (unofficial).
- Tests: `tests/feeds/test_rates_adapters.py` (fixtures; no network).

## Open items for the owner

1. Register a free EIA key and, if wanted, TMX Analytics; supply keys only through Settings. Until then they stay "needs verification".
2. Read the TMX Analytics terms for ML use and the billing/overage clause before any adapter is written.
3. Decide whether to open a broker data account (Questrade, IBKR) for options, TSX/TSXV and global equities; that is the only route to those markets that is not a vendor licence.
