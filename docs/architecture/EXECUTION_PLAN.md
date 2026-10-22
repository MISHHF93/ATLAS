# Execution plan — simplified desk, public candles, live training

Updated 2026-10-21 for `C:\Users\borah\ATLAS-main`. This is the operating plan for the current build. The A–Z roadmap libraries stay in place. This pass closes the gap between that sheet and the desk the operator actually uses.

## What the product is

One Next.js shell on `127.0.0.1:3000` (`frontend/server.mjs`) serves the pages and forwards `/api` and `/ws/market-stream` to the Python app. Primary navigation is Desk, Markets, Trade, Risk, Research, and Data. The older routes still resolve. Duplicate URLs redirect. Trading stays disabled until a venue session is configured.

The control plane is the only component that can authorize, size, or paper a bracket. Machine-learning output keeps `execution_permission: "none"`. A promoted model is not a competition win and is not a live order.

## Routes that match the simplified shell

| Nav | Route | Job |
| --- | --- | --- |
| Desk | `/` | Chart, both books, whale read, training status |
| Markets | `/listings` | TradingView stock, crypto, ETF, and forex catalogs, plus the nine-name tape |
| Trade | `/trade` | Cockpit, depth, blotter, journal |
| Risk | `/control` | Rulebook, kill switch, surveillance |
| Research | `/research` | Walk-forward, microstructure, roadmap, models |
| Data | `/data` | Lakehouse, pipelines, governance, connectors |

## Data

1. Prefer public candles. Crypto uses Coinbase's public product API. Equities and ETFs use Yahoo's public chart API. The payload names that source.
2. Those calls are not Polygon, Databento, IBKR, or a funded-firm session. `venue_sessions` on a public read is `public_market_data`.
3. If the public call misses, the chart keeps the labeled synthetic fixture and says `labeled_synthetic_fixture`.
4. The 1 Hz pump still animates a book around the latest public close. A tick that is far from that close is not painted onto a public candle.

## Training path

Path id: `desk-public-candle-walk-forward:v1`.

`POST /api/ml/live-train` and the startup research cycle run all six stages in one pass. `GET /api/ml/live-train/status` returns that pass. The desk prints the stage line.

| Stage | What it does |
| --- | --- |
| `read_public_candles` | Daily bars for BTC-USD, ETH-USD, SOL-USD, SPY, NVDA, AAPL, MSFT, QQQ, TSLA. Coinbase for crypto, Yahoo for equities. A miss is labeled fixture. |
| `label_printed_closes` | Observations use the bar time as both event time and available time. No future close is a feature. |
| `walk_forward_gate` | Purged walk-forward on each symbol. The gate still requires causal folds, Sharpe above 1.80, max drawdown under 3.2%, and Brier under 0.18. |
| `fit_track_weights` | One weight vector for the competition book and one for the open-market book. A symbol does not donate its weights to the other book. |
| `score_both_books` | Each symbol is scored with its book vector on the same daily candles. |
| `withhold_orders` | `orders_submitted` stays 0. |

`GET /api/ml/chart-read` then scores the timeframe on screen with the book vector, using public bars for that timeframe when they exist. FRED stays out of training. `irohan0/quant-mcp` stays quarantined. A gate pass is research eligibility only. It is not a competition result and it does not authorize a live order.

## Range garden

Path id: `range-garden:v1`. The spec is `docs/roadmap/range_garden.md`.

The desk watches about once a second and papers a bracket only at a proven rail, and only when the distance to the target clears the round-trip cost. Crypto uses the Coinbase public last trade. Equities stay on Yahoo minute bars, which are older than the open-market 2000 ms rule, so that book watches until a fresh print exists. Opens use the control-plane intake. Closes use `close_position`. Both are paper. The fixture seed position is not a garden position. `GET /api/strategies/range-garden` is the status the desk prints.

## Charts

Every chart surface (desk, markets, trade cockpit, and the market terminal) embeds TradingView's Advanced Chart widget from `tradingview.com`. The same symbol also loads their quote, technical rating, profile, financials, and news. The desk and the markets page add the nine-name ticker tape. The map is `GET /api/market/tradingview`. The tape is `GET /api/market/tradingview/tape`. BTC-USD is `COINBASE:BTCUSD`, SPY is `AMEX:SPY`, ES is `CME_MINI:ES1!`. Catalog ids `EQ####` and `PERP###-USD` are not TradingView listings, so those screens say so and do not draw a substitute chart. The free widget has no 1-second bars.

None of the widgets return bars, and none of them are a training input. The model keeps reading the public-candle path for the same symbol and the same resolution. `GET /api/ml/chart-read` includes that TradingView symbol and interval. TradingView's technical rating is their gauge, not the ATLAS model. TradingView's licensed Advanced Charts library is not bundled.

## Asset catalog

TradingView does not offer a download of their symbol database, and their widget FAQ says the data cannot be exported. The catalog inside ATLAS is their official widgets, loaded from `tradingview.com`. `GET /api/market/tradingview/markets` returns four panes: the US stock screener (`market: us`, screen `most_capitalized`), the crypto screener (`market: crypto`, screen `top_gainers`), the US ETF heatmap (`dataSource: AllUSEtf`), and the forex screener (`market: forex`). The markets page embeds those panes. The synthetic `EQ####` and `PERP###-USD` rows stay in the local catalog and are not replaced with a scraped list.

A click uses the documented handoff `/?tvwidgetsymbol={symbolname}`. The same handoff is on the nine-name tape. The origin is accepted only for `http://127.0.0.1` and `http://localhost` (optional port). Any other origin omits the click-through, so the widget cannot be turned into an open redirect. The desk reads that query, opens TradingView's chart for the qualified symbol (`NASDAQ:AAPL`, `COINBASE:ETHUSD`, `CME_MINI:ES1!`), and asks the model to read the public-candle series only when the listing maps to one: a Coinbase `BASEUSD` pair, a NASDAQ/NYSE/AMEX ticker, or a mapped futures root. Other listings, including `BINANCE:BTCUSDT`, stay on TradingView's chart. The model says it has no public-candle series for them. Fixture ids still get no chart. None of these panes can submit an order.

## Reserve sleeve

`reserve-yield:v1` plans a paper sweep of cumulative paper profit: 40% munis (`MUB`, `VTEB`, `TFI`, `HYMB`, `CMF`, `NYF`), 30% T-bills (`SGOV`, `BIL`), 20% broad equities (`VOO`, `QQQ`), and 10% real estate (`VNQ`, `CPT`). Tax-equivalent yield is `yield / (1 - t)` for munis, with `t` assumed at 0.37 until a filing rate is set. Distribution yield stays unobserved until a public yield is supplied. `SHY`, `IEF`, `TLT`, `SPG`, `HST`, and `VICI` are on the chartable list at a zero sweep weight. MSRB EMMA, FINRA TRACE, and the IBKR bond scanner are not connected. `GET /api/strategies/reserve-yield` returns the plan with `orders_submitted: 0`. The competition seed position stays open. The spec is `docs/roadmap/reserve_yield.md`.

## Still later

Broker and prop-firm sessions, certified live order routing, and any claim that a model won a competition. Those wait on credentials and on the control-plane gate. Unknown venue means no live order.
