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
