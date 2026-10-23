# Yahoo Finance chart endpoint (UNOFFICIAL fallback) (`yahoo`)

Status: **working** (UNOFFICIAL)

| Field | Value |
|---|---|
| Asset classes | equity, etf, index, fx, crypto, future |
| Schemas | bars |
| Intervals | 1m, 5m, 15m, 1h, 1d |
| History depth | Intraday limited: 1m=7d, 5m/15m=60d, 60m=730d; daily=max |
| Live stream | none (polling only) |
| Rate limits | Undocumented; ATLAS self-limits to 1 req/s and backs off on 429 |
| Env vars (names only) | none (keyless) |
| Terms | <https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html> |

## Notes
No official public API/docs; endpoint query1.finance.yahoo.com/v8/finance/chart is unofficial and may change. Labelled fallback only; personal/research use per Yahoo terms. Bars are 15m-delayed-ish; last bar may be partial.

## Verification
Live-tested 2026-10-23. UNOFFICIAL, undocumented endpoint; may change or block at any time; used as last-resort ETF source.

## Official docs
- <https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html>

Adapter: `src/atlas/feeds/providers/`. The manifest in code is the source of this page. Paper and simulation only.
