# Unified Intelligence Assessment

Verified on 2026-10-23 against the working tree and the full local test suite.

## Verified current state

- FastAPI exposes health, read-only fixture market data, research capabilities,
  and the persistent vertical-slice routes.
- `ActionableControlPlaneEngine` is still the only order-authorization boundary.
  The slice calls it only after uncertainty gating. Every forecast and trade row
  records `execution_permission: "none"`.
- Authorized public candles are available from Coinbase public candles for
  crypto and Yahoo chart candles for equities. A miss returns `unavailable`; it
  is not replaced with a synthetic forecast.
- `atlas.research.vertical_slice` implements the first end-to-end pipeline:
  normalize -> causal features -> labels -> purged walk-forward -> model
  selection -> forecast -> SQLite ledger -> paper authorization -> resolution.
- Model selection compares softmax logistic, XGBoost multiclass, class-frequency,
  and uniform baselines on the same out-of-sample decisions.
- Forecast rows, model rows, paper trades, chart observations, and measured
  limitations are persisted in SQLite. Open paper positions, equity, and the
  matching entry orders are snapshotted and restored after restart.
- A completed-bar scheduler runs the slice at most once per bar, resolves due
  forecasts, and persists its counters. A cross-process lock prevents two API
  processes from owning the same ledger scheduler. `evaluate_multi` produces an
  isolated multi-symbol, multi-horizon walk-forward matrix without creating
  paper trades.
- `ablate_feature_families`, `POST /api/research/vertical-slice/feature-ablation`,
  and `POST /api/research/vertical-slice/feature-ablation-multi` measure each
  feature family on the same purged folds without writing to the ledger. The
  matrix adds symbols, horizons, descriptive trailing volatility/trend regimes,
  and optional session/cross-asset candidates built from authorized timestamps
  and public reference candles. The prediction ledger displays the measured
  deltas.
- The prediction-ledger page shows authorized candles, the recorded forecast
  marker, the feature snapshot, model contributions, forecasts, paper
  authorizations, lucky moments, multi-horizon evidence, scheduler status,
  paper equity, and challenger status.
- Backend: 353 tests pass. Frontend: typecheck, route ownership tests, and a
  production build pass (45 static pages). A production-server scan confirmed
  all 41 app routes resolve to their canonical owner and all 29 referenced
  `/_next` JS/CSS assets return HTTP 200. The prediction-ledger page includes
  the feature-ablation and cross-symbol matrix UI.

## Measured live smoke result

One BTC-USD daily run fetched 350 public bars. On the purged walk-forward:

| Candidate | Brier | Log loss | Accuracy |
| --- | ---: | ---: | ---: |
| Softmax logistic | 0.6152 | 1.0035 | 42.1% |
| XGBoost multiclass | 0.6661 | 1.0837 | 47.4% |
| Class-frequency baseline | 0.5854 | 0.9500 | 46.1% |
| Uniform baseline | 0.6667 | 1.0986 | 33.3% |

The frequency baseline won. ATLAS selected it and abstained. This is a negative
result for the learned models on one symbol and horizon, not a profitability
claim. It demonstrates the intended evidence rule: a learned model that loses
out of sample is not promoted.

The same 350 bars were used for a read-only feature-family ablation. Baseline
softmax Brier was 0.6134. Removing momentum produced 0.6076, volatility 0.6073,
trend 0.6116, positioning 0.6116, and volume 0.6129. Momentum and volatility
removal slightly improved Brier on this sample; the other changes were
inconclusive. The differences are small, the frequency baseline still won, and
the result must be repeated across symbols, horizons, and regimes before the
feature set is changed. No ablation writes forecasts or paper trades.

## Problems found and corrected

- Import and re-export breakage across research, experiments, fundamentals,
  integrations, keys, and AI policy.
- Drift dashboard features and metrics were synthesized with `Math.random()`.
  The route now redirects to `/research`; drift APIs require observed feature
  windows.
- Transformer documentation claimed completed end-to-end training. The encoder
  is fixed and the forecast head is trained; the docs and challenger now state
  that distinction.
- The vertical slice lived under `atlas.models` while calling the control plane,
  which violated the model-boundary architecture test. It now lives under
  `atlas.research`.
- Forecast rows were ordered by availability, not event time, during resolution.
  Resolution now maps availability conservatively.

## Remaining architecture gaps

1. (retired) The advanced-ML HTTP surface is no longer mounted.
   `/api/advanced-ml/*` returns HTTP 503 with `state: "retired"` and points to
   the audited vertical slice. The underlying research modules remain importable
   for isolated experiments, but there is one public research API.
2. (blocked externally) The instrument catalog contains many explicitly labeled
   synthetic fixtures. Real asset coverage is limited by provider subscriptions
   and licensing; the catalog already reports `source: synthetic_fixture` and
   `is_live: false`.
3. (blocked externally) TradingView remains display-only. Custom prediction
   markers require a licensed charting integration; ATLAS renders its own marker
   over authorized bars.
4. The vertical slice has a background scheduler that checks completed public
   bars and runs at most once per symbol/horizon bar. A cross-process scheduler
   lock prevents duplicate owners, but it remains a local process loop rather
   than a distributed job system. Horizons 1-24 each have an isolated paper
   book, and a forecast can only close the book matching its persisted horizon.
5. Paper positions, equity, and open authorizations are snapshotted into the
   local ledger and restored on restart. They remain simulated paper state, not
   venue fills or a live trading record.
6. Beating a frequency baseline on one crypto symbol is not evidence of general
   predictive value. `evaluate_multi` produces a multi-symbol, multi-horizon
   purged walk-forward matrix without touching the production ledger. The
   scheduler can serve multiple horizons, each with its own paper book, while
   the evaluation path remains read-only. `feature-ablation-multi` now repeats
   feature-family ablation across symbols, horizons, and descriptive
   volatility/trend regimes. The regime labels are trailing and causal but are
   not a validated regime classifier.
7. The production feature set remains narrow and price/volume only. Session and
   cross-asset candidates are now built from authorized timestamps and public
   reference candles, and are measured through the ablation matrix before any
   promotion. Order-book depth, macro, news, and corporate-event features still
   require additional authorized feeds and a separate validation cycle.

## Shortest route to one unified pipeline

Use `VerticalSliceService` as the single intelligence facade:

1. (implemented) The advanced-ML HTTP surface is retired and directs callers to
   the audited slice. Its modules remain internal experiment code only.
2. (implemented) A scheduler calls the slice on completed-bar boundaries for the
   authorized universe, using the same config and ledger.
3. (implemented) The ledger snapshots open positions, order history, and equity
   so paper sessions survive a restart.
4. Add a licensed chart adapter that consumes `/chart`; keep TradingView as a
   display surface, never as a model input.
5. (implemented) Evaluate the same models across several symbols and horizons
   through `POST /api/research/vertical-slice/evaluate-multi`, retaining a
   baseline whenever it wins. Results are shown in the prediction ledger.
6. (implemented) Serve multiple horizons through
   `ATLAS_VERTICAL_SLICE_HORIZONS`, persisting a separate paper book and state
   key per horizon. Horizon selection on resolution comes from the stored
   forecast, not from whichever horizon ran last.

Real-money execution stays disabled until separate approval, regulatory review,
and operational safeguards exist.
