# Tiingo (EOD + IEX intraday) (`tiingo`)

Status: **interface_fixture_tested**

| Field | Value |
|---|---|
| Asset classes | equity, etf, crypto, fx |
| Schemas | bars, quotes, trades |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | EOD 30+ years; IEX intraday history (resampleFreq) |
| Live stream | websocket: wss://api.tiingo.com/iex |
| Rate limits | Free: 50 req/hour, 1000 req/day, 500 unique symbols/month |
| Env vars (names only) | `TIINGO_API_KEY` |
| Terms | <https://www.tiingo.com/about/terms> |

## Notes
-

## Verification
Verified 2026-10-23: free tier 50 req/hour, 1,000/day, 500 unique symbols/month, 1 GB/month, internal use only.

## Official docs
- <https://www.tiingo.com/documentation/iex>
- <https://www.tiingo.com/documentation/end-of-day>
- <https://www.tiingo.com/documentation/websockets/iex>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
