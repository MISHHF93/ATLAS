# Databento Historical + Live (`databento`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, future, option |
| Schemas | bars, trades, quotes, mbo, mbp |
| Intervals | 1m, 1h, 1d |
| History depth | Venue-dependent, e.g. CME Globex (GLBX.MDP3) since 2010, XNAS.ITCH since 2018 |
| Live stream | Databento Live (raw TCP gateway / official python client) |
| Rate limits | Historical per IP: 100 concurrent connections, 100 timeseries requests/s; 429 + Retry-After; metered per GB (metadata.get_cost is free) |
| Env vars (names only) | `DATABENTO_API_KEY` |
| Terms | <https://databento.com/terms> |

## Notes
HTTP API: https://hist.databento.com/v0/timeseries.get_range (Basic auth, key as username). Prices in 1e-9 fixed point. Usage is billed: ATLAS never calls it unless DATABENTO_API_KEY is set AND ATLAS_DATABENTO_DATASET is set.

## Verification
Verified 2026-10-23: HTTP Basic auth with key as username; per-IP 100 concurrent connections and 100 timeseries req/s, 429 + Retry-After; billed per GB (metadata.get_cost free).

## Official docs
- <https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range>
- <https://databento.com/docs/schemas-and-data-formats/ohlcv>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
