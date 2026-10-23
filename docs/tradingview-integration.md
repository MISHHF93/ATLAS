# TradingView integration

ATLAS is paper-trading only. TradingView content is for display. Detectors, the control plane and paper orders never read prices from TradingView.

## What the TradingView docs say (sources)
- Widgets data FAQ: https://www.tradingview.com/widget-docs/faq/data/
  - TradingView has no data API, and widget data can't be exported.
  - Widgets show TradingView data only. You can't put your own data in them.
  - US stocks are delayed. Forex and crypto are real time.
  - Paid plans don't change what widgets show.
- General widget FAQ: https://www.tradingview.com/widget-docs/faq/general/
  - Attribution can only be changed by contacting TradingView.
  - Use "container size" for responsive sizing.
  - Click-through goes to the full-size chart URL (`?tvwidgetsymbol=`).
  - Widgets set no cookies, but they do see the embedding page URL and IP.
- Libraries: https://www.tradingview.com/free-charting-libraries/
  - Lightweight Charts is Apache-2.0.
  - Advanced Charts and Trading Platform are proprietary. You have to apply for them, and they're for companies with public projects.
- The libraries contain no market data: https://www.tradingview.com/charting-library-docs/latest/connecting_data/datafeed-api/
- UDF spec: https://www.tradingview.com/charting-library-docs/latest/connecting_data/UDF/
- Lightweight Charts attribution (NOTICE plus a link): https://github.com/tradingview/lightweight-charts

## How ATLAS uses it
| Surface | Tech | Data owner |
|---|---|---|
| /listings, /market, chart companions | TradingView iframe widgets, with URLs built in `src/atlas/marketdata/tradingview.py` | TradingView |
| /research/price-action, LiveChartEngine, SecondBars | Lightweight Charts 4.2.3 | ATLAS (`causal_bars`) |
| AtlasUdfTape | Charting Library, only if `window.TradingView` is already present (not vendored) | ATLAS via `/api/udf` |

Every frame is labelled by `TvProvenance`: "TradingView display — not ATLAS data" or "ATLAS data". ATLAS charts also show a freshness line and flag data as stale when it's older than max(2×bar, 5 min). All axes use America/Toronto, and the Advanced Chart widget timezone is America/Toronto.

## UDF compliance (`/api/udf`)
- `config` (search, timescale marks)
- `symbols`: unknown symbols return `{s:"error"}`. Includes `visible_plots_set`.
- `search`
- `history`: supports `countback`, which takes priority over `from`. `to` is exclusive. Returns `nextTime`.
- `marks`: uses the table layout by default. `layout=rows` returns the array form.
- `timescale_marks`: session-open marks.
- `time`

The UDF bars match the bars the detectors use (`tests/test_udf_spec_parity.py`).

## Limitations and known issues
- Yahoo 60m feed: bars sit on :30 offsets, and there's a trailing 16:00 stub bar (o=h=l=c, volume 0). This affects the detectors and the UDF equally. Filtering it is a follow-up.
- The Advanced Charts library is not vendored. To use it, apply at https://www.tradingview.com/advanced-charts/ and then load it as a private asset. Don't commit it.
- In the console, widgets log CORS errors from `widget-sheriff.tradingview-widget.com` when the page is served from localhost. These are third-party and don't affect anything.
- CSP (recommended, not yet set): `frame-src https://s.tradingview.com https://www.tradingview-widget.com; script-src` adds `https://s3.tradingview.com` if script embeds are used.
