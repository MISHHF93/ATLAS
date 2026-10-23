# CME Group market data (MDP 3.0 / DataMine) (`cme`)

Status: **documented_stub**

| Field | Value |
|---|---|
| Asset classes | future, option |
| Schemas | bars, trades, quotes |
| Intervals |  |
| History depth | licensed; see docs |
| Live stream | licensed feed (not implemented) |
| Rate limits | n/a |
| Env vars (names only) | none (keyless) |
| Terms | <https://www.cmegroup.com/market-data/license-data.html> |

## Notes
Direct CME data needs a licence + distributor agreement. Practical route: Databento GLBX.MDP3 (adapter above).

## Verification
Documented stub. CME pages returned 403 to automated fetch; not verified.

## Official docs
- <https://www.cmegroup.com/market-data/real-time-futures-and-options-data-api.html>
- <https://www.cmegroup.com/market-data/datamine-historical-data.html>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
