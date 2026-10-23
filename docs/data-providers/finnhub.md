# Finnhub (`finnhub`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, fx, crypto |
| Schemas | bars, trades |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Stock candles are a premium endpoint; free tier: quotes + websocket trades |
| Live stream | websocket: wss://ws.finnhub.io?token=<key> (trades) |
| Rate limits | Plan limit per minute (429 on excess) plus a global 30 calls/s cap; websocket: 1 connection per key |
| Env vars (names only) | `FINNHUB_API_KEY` |
| Terms | <https://finnhub.io/terms-of-service> |

## Notes
-

## Verification
Verified 2026-10-23: 429 on plan limit plus 30 calls/s cap; stock candles are Premium; 1 websocket connection per key. Exact free per-minute quota not confirmed on the fetched page.

## Official docs
- <https://finnhub.io/docs/api/stock-candles>
- <https://finnhub.io/docs/api/websocket-trades>
- <https://finnhub.io/docs/api/rate-limit>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
