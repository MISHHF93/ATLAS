# Shared price-action package (`atlas.features.price_action`)

Status: **implemented + tested on synthetic fixtures only.** No real-data evaluation has been run, and no performance metrics are claimed. A detected pattern is a *proposal*. It carries `execution_permission: none` and `probability: None`, and only `ActionableControlPlaneEngine` can turn it into an action. Everything is paper/simulation.

## Availability rule
A bar is used only after it has closed: `now >= start + duration` **and** `provider_completion_verified`. The engine refuses bars that are unconfirmed, duplicated, out of order, or of the wrong timeframe. Every computation is causal and uses only bars ≤ t.

## Indicators (`indicators.py`): streaming and an independent batch version
- **EMA(n):** seeded with the SMA of the first n values, then `e = a·x + (1−a)·e`, where `a = 2/(n+1)`.
- **RSI (Wilder, n):** seeded with the mean gain/loss of the first n changes, then `avg = (avg·(n−1)+x)/n`. Edge cases: loss = 0 → 100; gain = 0 → 0; both 0 → 50.
- **ATR (Wilder, n):** `TR = max(H−L, |H−Cprev|, |L−Cprev|)`, with `TR0 = H−L`. Seeded with the SMA, then Wilder smoothing.
- **Bollinger(src, n, k):** SMA ± k·σ, where σ is the *population* standard deviation (ddof = 0).
- **Bar VWAP:** Σ(typical·vol)/Σvol with typical = (H+L+C)/3. Resets each session. This is a *bar approximation*, not a tick VWAP.

## Zones (`zones.py`)
Fields: id, type, direction, bounds, formed/confirmed/invalidated/expired timestamps, touch_count, max_age_seconds, invalidation_buffer.
Helpers: height, midpoint, distance, normalized distance (distance/ATR; 0 inside the zone; None when ATR is unknown).
Events:
- touch: counted on a new entry only;
- retest;
- invalidated: a directional close beyond the bound ± buffer;
- expired: when the zone reaches max_age.

## Sessions (`sessions.py`)
`SessionSpec(tz, open, close, weekdays, holidays)` handles DST through zoneinfo. Presets: US_EQUITY_RTH, LONDON_CASH, TOKYO_CASH. **Holiday lists are empty by default.** Callers must supply them.

## Detectors (`detectors.py`)
- **Opening range → breakout → retest → continuation**
  - States follow the spec. The range is the aggregate of the bars inside the first `range_seconds`. If those bars are missing or misaligned, the session is INVALIDATED.
  - The breakout needs a close beyond the range by `breakout_buffer + breakout_buffer_atr·ATR`. A retest must arrive within `max_bars_after_breakout`, and then continuation is required.
  - A failure re-arms the detector, up to `max_setups_per_session`. The detector moves to EXPIRED at session close.
  - Stop = the extreme since the breakout ∓ tolerance. Target uses `reward_risk = 2`, which is an *engineering default, not an optimised value*.
  - Snapshot/restore is supported. Transitions are persisted idempotently (`store.py`, SQLite PK(setup_id, seq)).
- **Dual Bollinger:** band A = close/20/2, band B = open/4/4. Variants: close_beyond, range_pierce, or both, with the threshold taken from the current or prior band. The zone is the qualifying candle's high–low.
- **Wick reversal:** requires a lookback swing extreme, minimum wick ratios (wick/range and wick/body), and a confirmation window. Zone = [low, body low] for bullish; mirrored for bearish.

## Economic events (`events.py`)
`EconomicEvent` has `*_available_at` fields. `as_of(t)` hides any value whose availability time is later than t. `raw_surprise` is also provided. `event_zone` uses the completed 1h bar that contains the release. **Interface only: no calendar feed is connected.**

## API (read-only)
- `GET /api/quant/zones` and `GET /api/quant/setups` (`symbol`, `resolution`, `session`) run on the platform's causal UDF bars.
- `POST /api/quant/analyze` accepts caller bars plus a `data_label`.
- Proposals are returned as `StrategySignal` objects (conviction 0.5, `probability_calibrated: false`) with `submitted: false`. Nothing is submitted.

## Frontend
`/research/price-action` shows candles with optional overlays (opening range, dual-band, wick) in colour-blind-safe colours, plus candidate and zone tables.

## Tests
`tests/price_action/test_price_action.py` has 30 tests:
- hand-computed indicator values;
- zone lifecycle;
- session DST;
- each detector;
- events as_of;
- batch/stream parity and prefix invariance (no retroactive events);
- refusal of bad bars;
- snapshot/restore and the idempotent store;
- control-plane ingestion;
- API.

All fixtures are seeded synthetic data and labelled as such.

## Limitations
- The old indicator and zone implementations are not yet consolidated onto this package.
- There is no calibrated probability or EV. Conviction is a placeholder; Phase 2 should add a unified predict() with calibration and abstention.
- `market_regime` is None in candidate features.
- Bar VWAP is an approximation.
- There is no holiday data.
- There is no economic data feed.
- Performance has not been evaluated on real data.

## Slice 2 — prediction contract, EV gate, replay, consolidation

### `atlas.models.predict.predict()` (spec 12.1)
- Returns a `Prediction` with only the fields listed in the registered model's `validated_outputs`; everything else is `None`. `execution_permission` is always `"none"`.
- A probability is returned only through an in-scope calibrator (`PlattCalibrator`, or `BinCalibratorAdapter` that wraps `ProbabilityCalibrator`) fitted on held-out data before the observation time. If no such calibrator exists, the prediction abstains.
- Abstention codes:
  - `no_validated_model`, `unknown_model`
  - `horizon_mismatch`, `instrument_out_of_scope`
  - `missing_features`, `feature_from_future`, `stale_data`
  - `uncalibrated`, `calibration_unsupported`
  - `uncertainty_unavailable`, `uncertainty_too_wide` (from the conformal half-width)
- `DEFAULT_REGISTRY` is **empty**. No price-action setup model has been validated, so every live candidate abstains with `no_validated_model`.

### `atlas.models.opportunity` (research only)
- EV = pG − (1−p)L − C
- break-even p = (L+C)/(G+L)
- Kelly b = (G−C)/(L+C)
- The fractional Kelly result is clipped at 0.
- Research units = floor(eq·rf/((L+C)·mult)/lot)·lot.
- Gate reasons:
  - `costs_exceed_edge`
  - `insufficient_edge`
  - `probability_semantics_mismatch`
  - `invalid_stop_target_geometry`
- Sizing is a proposal only. `sizing_authority` = ActionableControlPlaneEngine; the founder Safe-stop still applies.

### Proposals
- The 0.5 conviction placeholder has been removed. `candidate_to_signal` raises `Abstained` unless the evaluation carries a calibrated probability; in that case conviction = the calibrated p.
- `/api/quant/setups` returns `evaluations` for all candidates and `proposals` for non-abstained candidates only.

### Replay (`price_action.replay`, `GET /api/quant/replay`)
- Feeds bars through the same streaming `PriceActionEngine.update` used live.
- Fill model `conservative_ohlc_v1`:
  - **Entry:** limit at the entry reference, starting the bar after detection, held for `entry_window` bars.
  - **Fill bar:** a stop touch counts; a target touch is ignored.
  - **Gaps:** a gap through the stop exits at the open; a gap through the target is capped at the target.
  - **Ambiguous bars:** a bar touching both stop and target counts as a stop.
  - **Timeout:** exits at the close after `max_hold_bars`.
  - **Costs:** charged per unit.
- Output is labelled `real:<feed_origin>`, `no_data`, or (tests only) `synthetic_fixture`. It is descriptive and is not a validated performance estimate.

### Consolidation
- These legacy functions are shims over `price_action.indicators`, with behaviour verified against frozen copies in `tests/price_action/legacy_reference.py`:
  - `pine_features` (EMA/RSI/ATR)
  - `mcp/trading/research` (EMA/RSI/ATR)
  - `microstructure.compute_atr`
  - `udf._atr`
- The legacy `features/zones` engine is kept. `PriceZone.to_lifecycle_zone()` adapts it to the lifecycle `Zone`; it has not been rewritten.

## Slice 3: real-data evidence and the zone engine rewrite

- **Data.** `scripts/fetch_public_history.py` pulls free public bars into `var/evidence_cache/`, which is never committed:
  - Yahoo chart API, 1h (730 days) and 1d (since inception), for SPY, QQQ and IWM;
  - Binance `data-api.binance.vision` 1h klines (2 years) for BTCUSDT and ETHUSDT.
- **Evaluation.** `scripts/run_setup_evidence.py` runs `atlas.research.setup_evidence`:
  - triple-barrier labels from the conservative replay;
  - expanding walk-forward with 5 folds, purged by exit time, plus a 1-day embargo;
  - per-detector Platt calibration fitted on the training window only;
  - Brier score, log-loss and reliability bins, each compared with the base-rate baseline;
  - DSR across all trials, and PBO via CSCV.
- **Results** are in `docs/spec/evidence/price-action-setups-2026-10-23.{md,json}`. No config passed the gates, so nothing was registered.
- **Replay additions:**
  - `ReplayConfig.cost_bps`, a round-trip cost as bps of entry;
  - `ReplayConfig.zone_rule="zone_entry_v1"`, a research-only mapping of dual-band and wick zones to candidates.
- **`features/zones.ZoneEngine`** is now a facade over price_action. It keeps the same methods and the `PriceZone` outputs:
  - Breakout uses the canonical population-std bands. This is a documented change from the old pandas ddof=1 bands.
  - The anchor rule is unchanged and is checked against a frozen reference.
  - Opening, breakout and event construction used to raise TypeError because of missing fields. This is fixed.
