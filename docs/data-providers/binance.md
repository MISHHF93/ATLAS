# Binance Spot public market data (`binance`)

Status: **working**

| Field | Value |
|---|---|
| Asset classes | crypto |
| Schemas | bars, trades |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | Full listing history via /api/v3/klines (1000 bars/request) |
| Live stream | websocket: wss://data-stream.binance.vision/ws/<symbol>@kline_<interval> |
| Rate limits | Request weight 6000/min per IP (klines weight 2); HTTP 429 then 418 ban on abuse; honor Retry-After |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.binance.com/en/terms> |

## Notes
api.binance.com returns HTTP 451 from restricted locations (incl. this box); data-api.binance.vision is the market-data-only mirror.

## Verification
Live-tested from the box 2026-10-23 (data-api.binance.vision works; api.binance.com returns 451 restricted location). Doc page reachable; content not re-read this slice.

## Official docs
- <https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints>
- <https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams>
- <https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
