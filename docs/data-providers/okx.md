# OKX public market data (`okx`)

Status: **working**

| Field | Value |
|---|---|
| Asset classes | crypto |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | /market/candles: recent 1440 bars; /market/history-candles: multi-year, 100 bars/request |
| Live stream | websocket: wss://ws.okx.com:8443/ws/v5/business (candle<bar> channels) |
| Rate limits | market/candles 40 req/2s, history-candles 20 req/2s per IP |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.okx.com/help/terms-of-service> |

## Notes
-

## Verification
Live-tested from the box 2026-10-23 (history-candles, confirm flag). Doc page reachable; content not re-read this slice.

## Official docs
- <https://www.okx.com/docs-v5/en/#public-data-rest-api-get-candlesticks-history>
- <https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-candlesticks-channel>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
