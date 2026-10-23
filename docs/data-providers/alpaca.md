# Alpaca Market Data API v2 (stocks) (`alpaca`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf |
| Schemas | bars, trades, quotes |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Since 2016 (SIP needs paid plan for recent 15 min; IEX free) |
| Live stream | websocket: wss://stream.data.alpaca.markets/v2/iex (free) | /v2/sip (paid) |
| Rate limits | Free (Basic) 200 req/min; X-RateLimit-Limit/Remaining/Reset headers; HTTP 429 when exceeded |
| Env vars (names only) | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` |
| Terms | <https://alpaca.markets/disclosures> |

## Notes
Optional ALPACA_DATA_FEED=iex|sip (default iex). Streamed bars are 1-minute; ATLAS aggregates to 15m/1h. 'u' updatedBars messages are stored as revisions.

## Verification
Verified against official docs (bars endpoint, pagination, websocket auth/messages) on 2026-10-23.

## Official docs
- <https://docs.alpaca.markets/reference/stockbars>
- <https://docs.alpaca.markets/docs/real-time-stock-pricing-data>
- <https://docs.alpaca.markets/docs/about-market-data-api>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
