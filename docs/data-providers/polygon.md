# Massive (formerly Polygon.io) aggregates (`polygon`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, option, fx, crypto, index |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Stocks: up to 20+ years depending on plan (free: 2 years, EOD/delayed) |
| Live stream | websocket: wss://socket.massive.com/stocks (paid; delayed.massive.com for delayed) |
| Rate limits | Free (Basic): 5 API calls/min; paid: unlimited (soft) |
| Env vars (names only) | `POLYGON_API_KEY` |
| Terms | <https://massive.com/legal/terms> |

## Notes
-

## Verification
Verified 2026-10-23 (Massive, formerly Polygon): /v2/aggs/ticker/{t}/range/{mult}/{timespan}/{from}/{to}, limit 50,000, next_url pagination; Basic plan is end-of-day with 2 years history.

## Official docs
- <https://massive.com/docs/rest/stocks/aggregates/custom-bars>
- <https://massive.com/docs/websocket/stocks/aggregates-per-minute>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
