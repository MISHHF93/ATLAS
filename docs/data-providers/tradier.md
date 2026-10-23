# Tradier market data (`tradier`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, option |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1d |
| History depth | timesales: 1m ~20 days, 5m/15m ~40 days; daily history full |
| Live stream | websocket: wss://ws.tradier.com/v1/markets/events (needs session id) |
| Rate limits | Per-endpoint quotas with X-Ratelimit-Allowed/Used/Available/Expiry headers; over-quota returns HTTP 400 "Quota Violation" (not 429) - ATLAS retries with backoff |
| Env vars (names only) | `TRADIER_ACCESS_TOKEN` |
| Terms | <https://tradier.com/legal> |

## Notes
Optional TRADIER_ENV=sandbox|production (default sandbox; sandbox data is 15-min delayed).

## Verification
Verified 2026-10-23: over-quota returns HTTP 400 'Quota Violation' (ATLAS retries it as a rate limit) with X-Ratelimit-* headers; sandbox data 15-min delayed; tokens are environment-specific; personal use only without Partner status.

## Official docs
- <https://docs.tradier.com/reference/brokerage-api-markets-get-timesales>
- <https://docs.tradier.com/docs/rate-limiting>
- <https://docs.tradier.com/docs/streaming-market-data>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
