# OANDA v20 REST (`oanda`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | fx, cfd |
| Schemas | bars, quotes |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | Multi-year candles, 5000 per request |
| Live stream | HTTP stream: https://stream-fxpractice.oanda.com/v3/accounts/<id>/pricing/stream |
| Rate limits | 120 requests/s per connection; 2 new connections/s |
| Env vars (names only) | `OANDA_API_TOKEN` |
| Terms | <https://www.oanda.com/us-en/legal/> |

## Notes
Optional OANDA_ENV=practice|live (default practice), OANDA_ACCOUNT_ID for pricing stream. Mid candles, complete flag maps to confirmed.

## Verification
Partly verified 2026-10-23: pricing endpoint page documents GET /v3/accounts/{accountID}/instruments/{instrument}/candles (count max 5000, default 500). The adapter uses the older /v3/instruments/{instrument}/candles path; its doc page now returns 404, so confirm with a practice token before relying on it.

## Official docs
- <https://developer.oanda.com/rest-live-v20/pricing-ep/>
- <https://developer.oanda.com/rest-live-v20/best-practices/>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
