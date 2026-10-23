# Coinbase Exchange public market data (`coinbase`)

Status: **working**

| Field | Value |
|---|---|
| Asset classes | crypto |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Multi-year; max 300 candles per request (GET /products/{id}/candles) |
| Live stream | websocket: wss://ws-feed.exchange.coinbase.com (matches/ticker channels; no candle channel) |
| Rate limits | Public REST ~10 req/s per IP (burst 15); 429 on excess |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.coinbase.com/legal/user_agreement> |

## Notes
Quote currency is USD (not USDT); ATLAS maps BTCUSDT->BTC-USD as a cross-venue proxy for sanity checks.

## Verification
Live-tested from the box 2026-10-23 (candles endpoint). Doc pages reachable; content not re-read this slice.

## Official docs
- <https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles>
- <https://docs.cdp.coinbase.com/exchange/websocket-feed/channels>
- <https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
