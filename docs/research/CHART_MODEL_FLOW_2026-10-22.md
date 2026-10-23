# Chart and model flow — October 22, 2026

The Desk now contains an always-visible **Inside the model** panel below its
TradingView chart. It replaces the separate lock, whale card, and tracking strip
on this view with one inspectable model snapshot.

The chart loads the TradingView widget at `s.tradingview.com/widgetembed/`.
Widget content and model candles use separate data paths. TradingView documents
the widget data boundary at https://www.tradingview.com/widget-docs/faq/data/.
This change does not scrape or export widget data. TradingView's top toolbar is
hidden so the Desk's timeframe controls remain the intended interval selector.
A frame-load message reports iframe loading, not proof of market-data freshness.

The panel shows:

- TradingView symbol, actual model feed, requested interval, and actual bar size.
- Last 36 candles from the active model's input payload, with OHLC inspection
  on hover or keyboard focus and shading from the model's causal swing window.
- Read time and last bar closing time, refreshed every four seconds.
- ATR, candle-derived VPIN and Kyle's lambda, and observed/unobserved inputs.
- Actual model weights and raw score, scoring formula, HOLD conditions, policy
  stop and target rules, and separate swing invalidation/objective levels.
- Factor label, policy direction, abstention reasons, training timestamps,
  per-symbol evaluation results, promotion thresholds, and a manual daily refit.

Public-candle inference now excludes unfinished bars. As with training, daily
bar availability conservatively uses bar open plus 24 hours. Demo ticks are no
longer allowed to supply supposedly observed flow, VPIN, lambda, or spread to a
public-candle score. Same-symbol/interval matching is reported only when the
actual public series matches the requested bucket; fixture and shortened ring
fallbacks no longer claim alignment.

The served model remains a candle-retuned heuristic. The walk-forward evaluator
fits a separate logistic model; its learned coefficients are not deployed. The
panel states this explicitly. Neither watching the chart nor receiving new bars
constitutes online learning. The heuristic conviction is not a calibrated
probability. Kyle's lambda is displayed as a diagnostic, not a scoring term.

Validation: 199 backend tests passed, including regression coverage for partial
public candles and demo-input contamination. Three routing checks and the
production build passed. Chrome confirmed an actual TradingView chart frame
with seven canvas elements, synchronized 1m-to-5m Desk/model selection, 36
inspectable input candles, no page errors, and no mobile document overflow.
Local screenshots and results: `.test-runs/visual-audit/model-flow/`.
