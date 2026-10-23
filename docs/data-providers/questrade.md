# Questrade API (market candles) (`questrade`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, option |
| Schemas | bars, quotes |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Candles via /v1/markets/candles/{symbolId}, max 2000 per request |
| Live stream | streaming port via /v1/markets/quotes?stream=true (websocket) |
| Rate limits | Market data: 20 req/s, 15000 req/hour |
| Env vars (names only) | `QUESTRADE_REFRESH_TOKEN` |
| Terms | <https://www.questrade.com/api/home> |

## Notes
OAuth refresh-token flow: refresh token -> access_token + api_server (login.questrade.com/oauth2/token). Refresh tokens are single-use; ATLAS keeps the rotated token in memory only. Symbol ids resolved via /v1/symbols/search.

## Verification
Partly verified 2026-10-23: rate-limit page (market data 20 req/s, 15,000/hour; 429 with X-RateLimit-* headers). Candle and OAuth pages reachable, not re-read in detail.

## Official docs
- <https://www.questrade.com/api/documentation/rest-operations/market-calls/markets-candles-id>
- <https://www.questrade.com/api/documentation/getting-started>
- <https://www.questrade.com/api/documentation/rate-limiting>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
