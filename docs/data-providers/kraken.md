# Kraken Spot public market data (`kraken`)

Status: **working**

| Field | Value |
|---|---|
| Asset classes | crypto |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | OHLC endpoint returns only the most recent 720 bars per interval (older data via Trades/downloadable CSV) |
| Live stream | websocket: wss://ws.kraken.com/v2 (ohlc, trade, ticker channels) |
| Rate limits | Public REST ~1 req/s per IP recommended (counter-based limits); EGeneral:Too many requests on excess |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.kraken.com/legal> |

## Notes
-

## Verification
Verified 2026-10-23: REST OHLC returns at most 720 most recent bars; last bar is not committed (treated as unconfirmed). WS v2 ohlc page reachable.

## Official docs
- <https://docs.kraken.com/api/docs/rest-api/get-ohlc-data>
- <https://docs.kraken.com/api/docs/websocket-v2/ohlc>
- <https://docs.kraken.com/api/docs/guides/spot-rest-ratelimits>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
