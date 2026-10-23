# Alpha Vantage (`alphavantage`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, fx, crypto, macro |
| Schemas | bars, series |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | TIME_SERIES_INTRADAY: 20+ years via month=YYYY-MM; daily 20+ years |
| Live stream | none (polling) |
| Rate limits | Free: 25 requests/day |
| Env vars (names only) | `ALPHAVANTAGE_API_KEY` |
| Terms | <https://www.alphavantage.co/terms_of_service/> |

## Notes
-

## Verification
Verified 2026-10-23: free tier 25 requests/day; intraday timestamps are bar END, converted to bar start.

## Official docs
- <https://www.alphavantage.co/documentation/#intraday>
- <https://www.alphavantage.co/support/#api-key>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
