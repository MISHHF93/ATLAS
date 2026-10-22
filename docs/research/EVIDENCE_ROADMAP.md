# Evidence roadmap

This page records what the running desk has measured, what is only a hypothesis, and what is not built. A support call on one sample is not a competition result and cannot send an order.

## Verified on this desk

- Paper control plane only. Trading stays disabled. One seed competition position stays open. Research paths do not flatten it.
- One TradingView tape and one viewer. The Track button follows that chart's symbol and interval. The model reads the public-candle path. Widget bars, studies, drawings, and crosshair are not readable. `bars_from_tradingview` stays false. The free widget has no 1-second picture.
- Markets calls the rest of TradingView's iframe registry: stock, crypto, and forex screeners, stock, crypto, and ETF heatmaps, the economic calendar, forex cross rates and heat map, US hot lists, market overview, market quotes, a static ticker strip, and top stories. The selected listing also calls Symbol Overview, Mini Chart, and Single Ticker. US stock widgets are delayed. Forex and crypto widgets are TradingView's real-time feed. None of those panes feed the model or send an order. Seasonal Chart, World Market Summary, Market Summary, Economic Map, and Ticker Tag are Web Components outside that iframe registry, so they are not embedded.
- Markets opens TradingView's stock page for the selected listing: Symbol Info, Company Profile, Fundamental Data in their adaptive layout, Technical Analysis with their interval tabs, and Top Stories for that symbol. A US name is labeled stock information. US stock widgets are delayed. The home desk stays one tape and one viewer.
- The asset library asks for a public last print on the names loaded on the page, up to eighty, forty at a time. Crypto uses a Coinbase last trade. Stocks, ETFs, and the mapped futures roots use a Yahoo spark print and are labeled delayed. Unlisted names and filler ids stay without a quote. A check of that route returned NVDA, AAPL, and ES from Yahoo and BTC-USD from Coinbase, omitted SpaceX and EQ0001, left Disney's directory price at 0, and left NVDA's stored directory price at 142.1. Nothing was written back and nothing was sent. Every page sits in that same header, grouped as Desk, Trade, Risk, Research, and Data. The page you are on is the one marked. The separate Pages list is closed. The old side rail of section buttons remains in the page markup and is hidden.
- The 1-second button on a crypto name reads Coinbase's public last trade and folds each new trade into that UTC second. The open second moves when the trade prints. A second with no new trade is left empty. This is not every match. Equities have no public 1-second print here, so that button stays withheld and the minute chart remains the picture.
- Daily trend ledger, horizon next daily close, 20-day sign plus a logistic filter that abstains. Round-trip cost is 16 bps on the competition book and 4 bps on the open-market book. Proof requires 60 public resolved stances, a positive costed mean, a bootstrap interval above zero, and two symbols with a positive mean.
- Latest public sample, both tracks `not_supported`. Competition: 52 of 108 taken stances moved with the side, costed mean about -0.33%, Brier 0.259 on 297 probabilities. Open market: 88 of 193, costed mean about -0.24%, Brier 0.258 on 594 probabilities. A constant one-half forecast scores 0.25, so these probabilities are not yet a reliable confidence. Execution on both tracks is `not_attempted`.
- `GET /api/control/trade-readiness` also compares the latest 30 days of costed stances with the full sample. That month can keep the research light withheld. It cannot open live money. Eight costed stances in the window is the desk floor. On the serving desk the latest 30 days are about -0.46% on 30 competition stances and about +0.18% on 29 open-market stances. The open-market month is positive, and the full sample is still not supported, so the light stays withheld.
- Research trial log `research-trial-log:v1` appends each distinct ledger verdict once. A later pass does not delete an earlier miss. Repeating the same verdict does not add a row. The log does not estimate a probability of backtest overfitting and cannot send an order. The research light still follows only the current sample.

## Hypothesis, not a result

- The 20-day trend, after cost, might be useful on a later untouched sample. The current public sample does not support that.
- A tree model might beat the logistic filter after a frozen matrix of thousands of purged samples exists. LightGBM, XGBoost, PyTorch, and scikit-learn are not installed. Popularity is not a reason to add them.
- Order-flow measures (Kyle, VPIN, OFI, Hawkes) stay in the library. The candle path does not observe the book, so they are not the proof path.

## Planned, not started

- Portfolio view of how the two books' daily moves line up: correlation, concentration, and whether size would have worsened the fill. No new order path.

## Unresolved

- No live broker, no real order-book replay, and no corporate-action tape.
- Equity public bars, and the library's Yahoo stock and futures quotes, are older than the open-market freshness rule, so equity paper orders stay withheld.
- Live-money autonomy stays off. `GET /api/control/trade-readiness` reads the ledger and stays withheld until a sample clears the costed test and beats a one-half Brier. That page cannot open live money. The old readiness audit no longer marks those gates as passed from hardcoded flags.

## Sources for the reliability split

- Brier, Monthly Weather Review, 1950: a probability forecast is scored by the squared gap to the later outcome.
- Federal Reserve SR 11-7: ongoing monitoring and outcomes analysis compare model output with what later happened. That comparison is not a license to trade.
- López de Prado, Advances in Financial Machine Learning, chapter 3: the rule can choose a side while a second model sets the size to zero. A direction and a trade are not the same event.
- Bailey, Borwein, López de Prado, and Zhu, "The Probability of Backtest Overfitting," Journal of Computational Finance, first published 19 September 2016 (SSRN 2326253). Selecting the best trial and dropping the rest overstates the result. This desk keeps the rows. It does not compute that probability.
- Federal Reserve SR 11-7, model inventory and ongoing outcomes analysis: models in use, in development, and retired stay on the inventory, and performance is compared with later outcomes as conditions change. That inventory is not a license to trade.
