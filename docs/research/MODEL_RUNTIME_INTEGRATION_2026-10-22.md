# Live model integration and verification

## Operating model

The experimental online observer consumes actual provider inputs independently of browser views. Its background service watches BTC-USD, ETH-USD and SOL-USD from the Coinbase trade stream, plus SPY, NVDA, AAPL, MSFT, QQQ and TSLA from available public minute candles. These defaults follow the existing market gateway universe. `ATLAS_OBSERVER_SYMBOLS` can add comma-separated symbols within the reported watch capacity.

Recently viewed symbols remain watched for five minutes after the last viewer request. Additional scope is bounded to twelve names; the existing transport permits three additional crypto subscriptions. Status reports capacity-limited and omitted names instead of claiming they are observed. The API candle source retains its actual one-minute resolution and unknown provider delay. It does not supply tick-level equities data.

Crypto and minute work use separate asynchronous loops and thread pools. A slow stock API cannot exhaust the crypto observation workers. Failures are isolated and reported per symbol. Public-feed disable settings are honored, and no gateway fixture ticks are used by the observer.

## Integrity changes

- Provider observation timestamps now limit which candles can count as completed. Cached forming candles cannot become training targets simply because wall time crossed a boundary.
- Disconnected, disabled, unavailable or failed-refresh inputs pause learning. Waiting and paused responses still expose saved learned counts, coefficients and evaluation state.
- Input timestamps, finite positive OHLC, candle ranges and volume are validated at the model boundary. Older snapshots cannot overwrite newer predictions.
- Known trade-ID, heartbeat, reconnect and restart gaps mark affected received candles incomplete. Prices remain visible; contaminated feature windows and pending predictions are excluded from training. Healthy later inputs can recover without a permanent block.
- Learning artifacts and the corresponding model checkpoint commit in one SQLite transaction. Failed commits leave both durable and in-memory learned state unchanged.
- Live predictions are scored against later outcomes before coefficients update. Brier score, log loss and directional accuracy are diagnostics over the outcomes recorded since evaluation was enabled; older saved learning is not retrospectively assigned invented scores. These metrics do not establish independent validation or profitability.

## Platform visibility

`GET /api/ml/live-observer/status` reports the service lifecycle, actual coverage, per-symbol providers, resolutions, timestamps, feed/model states, learned counts and errors. The Training status page (`/models`) displays this information separately from the existing daily candle fit. Real time on Desk and Markets retains the shared chart/model snapshot and adds live prediction diagnostics.

Desk also receives the same validated snapshot for its selected price display and existing paper-sizing reference. Genuine native quotes are protected from fixture socket updates, older-symbol responses, and the separate library quote refresh while Real time owns the selected price. Stale responses cannot introduce replacement prices.

## Verification

The production build and TypeScript checks passed. The full backend suite passed 261 tests; three navigation tests passed. Focused tests cover autonomous stock learning without viewer requests, separate worker capacity, watch expiry, source-watermark completion, paused state continuity, invalid inputs, contaminated windows, causal scoring, and atomic failure rollback.

Runtime evidence showed all nine default listings observed with real provider sources. Between two status-only reads, BTC learned outcomes increased from 2,075 to 2,106, ETH 1,992 to 2,018, SOL 919 to 935, and all six equity/ETF observers advanced by one later minute outcome without their viewers open. Browser verification checked the Training status page at desktop/mobile sizes and the live diagnostics panel, with no browser errors or horizontal document overflow. Evidence lives under `.test-runs/visual-audit/model-readiness/` and `observer-before.json` / `observer-after.json`.

A subsequent application restart preserved or advanced all nine learned counts. Browser checks verified BTC and NVDA selected header prices against actual received native snapshots, including after legacy socket updates. The final running process served the production build and reported no observer errors.

The separate daily policy, walk-forward evaluator, and online observer remain distinct models. None of these integration checks establishes a production trading model's predictive quality. The live observer has no order authority.
