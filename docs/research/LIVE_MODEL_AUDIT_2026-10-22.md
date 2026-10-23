# Live model and interface audit — October 22, 2026

The local production application at http://localhost:3000 was inspected, rebuilt,
and restarted. This is an audit of the local process, not a production hosting or
broker certification.

## Verified behavior

- The startup lifecycle refreshes public data and runs research training on both
  books automatically, with a 900-second delay between completed cycles.
- After restart, all nine symbols trained using 119 completed daily public bars:
  BTC-USD, ETH-USD, SOL-USD, SPY, NVDA, AAPL, MSFT, QQQ, TSLA. Sources were
  Coinbase Exchange public candles and Yahoo chart public candles, respectively.
- Chart reads resolve the selected symbol to its track's research model.
- No model passed its promotion gates. Research fits submit zero orders.
- Eight desktop pages returned HTTP 200 with no browser page errors or horizontal
  overflow: desk, listings, trade, central research, walk-forward, training status,
  pipelines, and account risk. Chrome desktop and mobile screenshots are saved in
  `.test-runs/visual-audit/` (local, ignored artifacts).
- Backend verification: 198 tests passed. Frontend typecheck and production build
  passed; 43 static pages were generated.

## Repairs

- Public candle caches now expire (60 seconds for intraday, 900 seconds for daily)
  and retry provider reads. Disabled public fetching still permits offline cache
  reads. A provider miss preserves the last cached series.
- Background universe refresh explicitly includes daily training candles.
- Public training excludes unfinished daily candles. Observation availability is
  conservatively assigned to bar open plus 24 hours, including equities; this can
  delay use beyond the actual equity session close but avoids partial-bar labels.
- Per-symbol reports include the last bar open, close availability, and fit cutoff.
- Background fit failures now appear as errors instead of silently retaining an
  apparently healthy status.
- The research card sits below the chart, preserving chart visibility. Mobile
  panels and header controls wrap and the document can scroll.

## Material gaps

The served whale research model is a candle-retuned microstructure heuristic.
The walk-forward evaluator fits separate logistic policies; those fitted
coefficients are not deployed into the served model. API training reports now
identify both methods explicitly. Evaluator metrics do not validate the served
heuristic. No GBDT/actor-critic deployment was established despite legacy names.

Training uses completed daily history, refreshed periodically; it is not online
learning from every tick. Coinbase public crypto last-trade polling exists, while
stock data can be delayed. The 1 Hz universe pump remains explicitly labeled demo.
TradingView widget bars are not delivered to the model. Candle-derived flow
proxies are not observed exchange order-book or liquidation events.

Cached public data can survive a provider outage; public provenance alone does
not establish freshness. No entitled Polygon/Databento stock session, persisted
trained-model deployment, or restart-at-boot service was verified. Background
research runs only while the application process is alive. Real-time stock
monitoring and a validated trained model serving path remain outstanding.

Existing user edits in three TSX components were preserved.
