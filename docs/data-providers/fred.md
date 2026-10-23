# FRED / ALFRED (St. Louis Fed) (`fred`)

Status: **interface_fixture_tested** (endpoint reachable, returns 400 without key)

| Field | Value |
|---|---|
| Asset classes | macro |
| Schemas | series |
| Intervals | 1d |
| History depth | Full series history; vintages via realtime_start/realtime_end (ALFRED) |
| Live stream | none (polling; series release schedules) |
| Rate limits | 120 requests/min per API key |
| Env vars (names only) | `FRED_API_KEY` |
| Terms | <https://fred.stlouisfed.org/docs/api/terms_of_use.html> |

## Notes
Free key required (the keyless request returns 400 'api_key is not set'). Use output_type=2/vintages for point-in-time.

## Verification
Verified 2026-10-23: observations params realtime_start/realtime_end, output_type 1-4, vintage_dates; api_key is a 32-char lowercase string; keyless call returns 400.

## Official docs
- <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- <https://fred.stlouisfed.org/docs/api/api_key.html>
- <https://fred.stlouisfed.org/docs/api/fred/realtime_period.html>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
