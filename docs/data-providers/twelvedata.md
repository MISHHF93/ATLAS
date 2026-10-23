# Twelve Data (`twelvedata`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, fx, crypto, index |
| Schemas | bars, quotes |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | Decades for daily; intraday multi-year; 5000 points/request |
| Live stream | websocket: wss://ws.twelvedata.com/v1/quotes/price (paid tiers) |
| Rate limits | Basic (free): 8 API credits/min, 800/day |
| Env vars (names only) | `TWELVEDATA_API_KEY` |
| Terms | <https://twelvedata.com/terms> |

## Notes
-

## Verification
Verified 2026-10-23: Basic plan 8 credits/min, 800/day.

## Official docs
- <https://twelvedata.com/docs#time-series>
- <https://twelvedata.com/docs#websocket>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
