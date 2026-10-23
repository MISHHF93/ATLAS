# Bybit V5 public market data (`bybit`)

Status: **working**

| Field | Value |
|---|---|
| Asset classes | crypto |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 4h, 1d |
| History depth | /v5/market/kline multi-year, 1000 bars/request |
| Live stream | websocket: wss://stream.bybit.com/v5/public/spot (kline.<interval>.<symbol>) |
| Rate limits | 600 requests / 5s per IP for public endpoints |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.bybit.com/en/terms-service/> |

## Notes
Geo-blocked from this box (CloudFront 403); adapter is implemented + fixture-tested; failover skips it.

## Verification
Fixture-tested only: Bybit is geo-blocked from the box (CloudFront 403). Doc page reachable; content not re-read this slice.

## Official docs
- <https://bybit-exchange.github.io/docs/v5/market/kline>
- <https://bybit-exchange.github.io/docs/v5/websocket/public/kline>
- <https://bybit-exchange.github.io/docs/v5/rate-limit>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
