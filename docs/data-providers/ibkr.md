# Interactive Brokers (Client Portal Web API / TWS API) (`ibkr`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, future, option, fx, index |
| Schemas | bars, quotes |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | iserver/marketdata/history: period up to years for daily, ~1000 bars/request; pacing rules apply |
| Live stream | Client Portal websocket wss://localhost:5000/v1/api/ws (smd+conid) or TWS reqRealTimeBars |
| Rate limits | CP Web API: 10 req/s global; history endpoint 5 concurrent; TWS: 50 msgs/s, historical pacing 60 req/10 min |
| Env vars (names only) | `IBKR_CP_GATEWAY_URL` |
| Terms | <https://www.interactivebrokers.com/en/general/about/legal.php> |

## Notes
Requires a locally running, user-authenticated Client Portal Gateway (IBKR_CP_GATEWAY_URL e.g. https://localhost:5000). Market data subscriptions required. Instruments must carry an ibkr conid in the instrument master.

## Verification
Docs URL checked reachable 2026-10-23 (Web API doc). Content not re-read; requires local authenticated Client Portal Gateway.

## Official docs
- <https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/>
- <https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
