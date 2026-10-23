# Real time chart repair

The Desk and Markets use the same embedded TradingView Lightweight Charts candle viewer and model diagnostics. Markets exposes its timeframe selector and places the selected viewer above the external information widgets. The real-time chart uses received Coinbase trade candles; TradingView iframe contents are not model inputs.

Chart dimensions follow the container through ResizeObserver. Updates preserve the existing viewport after initial fitting. Requests cannot overlap, old symbol requests are aborted, and empty or unavailable feeds show an explicit message with a working candle-chart fallback. Smaller-priced assets receive appropriate price precision. Markets cards cannot shrink over the chart, and empty-state controls sit above the chart canvas.

Provider subscriptions are validated against the current online USD product registry, which is also captured as an artifact. Unknown products cannot reject the shared subscription. Real time model reads watch only the selected listing rather than implicitly registering unrelated book symbols. Core BTC, ETH and SOL observation continues in the background.

Verification: production build, 206 backend tests and three navigation tests passed. Browser audit checked 32 page/viewport combinations and seven Real time viewer sizes without browser errors or horizontal document overflow. Live chart and model candles were observed on Desk and Markets; the observer restored its learned state across restart and continued learning. Additional interaction checks cover unavailable-stock fallback and Markets desktop/mobile sizing.

Coverage remains limited to subscribed products from the connected provider, not every directory listing or every online market. Missing prints are not invented, detected gaps are retained, and the experimental online observer has no order authority or demonstrated predictive accuracy.
