# US stock / ETF 1-minute bars (Massive free plan, T+1)

Measured 2026-10-30 against the owner's Massive Stocks Basic key: `/v2/aggs/ticker/{T}/range/1/minute/{from}/{to}` returns 1-minute bars for **completed prior New York sessions**
(pre-market, regular session and after-hours, about 916 bars a day). The current ET day returns HTTP 403 until midnight ET, there is no websocket, snapshot or last trade on
the free plan. So the stock 1m series is **T+1**: it is real, but it is never live. The UI and API keep the "end-of-day lag" label.

## What ATLAS stores

| Item | Value |
| --- | --- |
| Provider / interval | `polygon`, `1m`, in the same point-in-time feed store as the 15m and daily bars |
| Session | regular session only (09:30-16:00 ET, 390 bars a day); pre/post-market rows are dropped by the adapter, like the 15m bars |
| Tickers | the priority list in `massive_backfill.PRIORITY` (17). `ATLAS_STOCK_1M=all` widens it to every stock/ETF (about 10x the rows and calls) |
| Window | the last `ATLAS_STOCK_1M_DAYS` completed days, default 60 (about 23k rows per ticker) |
| Throttle | the shared 4-calls-per-minute limiter (file `var/feeds/massive_throttle.json`), the same one the 15m/daily refresh and the server use; one call per ticker covers the whole window |
| Refresh | the live loop's daily Massive refresh (phase `D`) asks only for the completed days the store is missing; a re-run with nothing new costs zero calls |
| Manual | `python scripts/backfill_massive.py --phases D` (`--plan` lists the jobs without calling) |

Rows are never forward-filled, never invented, and never mixed with another provider's bars. A halted or illiquid minute has no row. Older 1m rows are not deleted (the store is
point-in-time), so growth is about 17 x 390 x 252 = 1.7M rows a year, roughly 200 MB.

## Use in the ML

The 15m decision clock reads the 1m bars only up to the last completed bar before the decision (`as_of`), so a 15m decision at 10:15 ET uses 1m bars that closed by 10:15.
On the T+1 feed the newest 1m bar is yesterday's close; anything between that and now is not data and is handled by the separate, labelled nowcast (milestone d), never stored here.
