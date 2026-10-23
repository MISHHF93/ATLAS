# TMX Group / TSX market data (TMX Datalinx) (`tmx`)

Status: **documented_stub**

| Field | Value |
|---|---|
| Asset classes | equity, etf, future, option |
| Schemas | bars, trades, quotes |
| Intervals |  |
| History depth | licensed; see docs |
| Live stream | licensed feed (not implemented) |
| Rate limits | n/a |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.tmxinfoservices.com/> |

## Notes
Licensed vendor feed; no public self-serve API. Practical route for TSX symbols: Questrade/IBKR adapters or Yahoo '.TO' fallback.

## Verification
Documented stub. TMX Info Services home reachable; no public API docs verified.

## Official docs
- <https://www.tmxinfoservices.com/>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
