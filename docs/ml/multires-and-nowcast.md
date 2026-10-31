# Multi-resolution features, nowcasts and gap fill (milestone c)

Status: research and shadow only. Nothing here gives an order, a size or `execution_permission`. All outputs that are not real
bars are PREDICTED values, labelled "Predicted (not market data)".

## 1. Multi-resolution features on the 15m decision clock (`ai/ml/multires.py`, schema `atlas-multires-v1`)

* Decision times are multiples of 900 s (UTC), which are also the ET quarter-hours in both EST and EDT.
* A feature at decision time T uses only bars whose END is <= T. Windows must be contiguous or the feature is NaN (never
  forward-filled). A series whose last bar ended more than 4 bar-durations before T is stale and yields NaN.
* 30 features in six groups: m15 (returns, realized vol, VWAP deviation, volume z-score, range), h1 (returns, vol),
  m5 (built only from complete 5 x 1m buckets), m1 (15m/60m return, vol, VWAP deviation, volume ratio, coverage),
  flow (order-flow imbalance 1/5/15 min, trade intensity, VWAP deviation, active-second share), s1 (1s vol, trades, return, OFI).
* Trade intensity counts only minutes in which the collector provably ran (any instrument of the venue has a row), so a collector
  outage is not read as "no trades".
* Spread: NOT a feature. No bid/ask is stored (`SPREAD_AVAILABLE = False`); it will be added only from real quotes.
* Order flow uses the TAKER side (Kraken `side`, Coinbase maker side inverted).

## 2. Nowcast workers (`ai/ml/nowcast_xgb.py`, schema `atlas-nowcast-xgb-v1`)

Estimate the current state of markets whose data arrives T+1 or daily from REAL, already closed related inputs.

| group | target | what is predicted | related inputs (all real closed bars) |
|---|---|---|---|
| `stocks_15m` | 17 priority US tickers incl. GLD (polygon, T+1) | log(close of the 15m RTH window ending T / previous session close) | coinbase 15m BTC, ETH, 8 alts |
| `stocks_1m` | same | same, 1m windows | kraken 1m (history too short, see below) |
| `fx_1d` | EUR_USD (ecb_fx), USD_CAD (boc_valet) | log(today's fixing / previous fixing), decided at 12:00 UTC | coinbase 15m crypto |

Rules enforced in code and tests:
* Only real bars are labels (`assert_real_labels`: `label_source == "real_bar"`, provider in polygon/ecb_fx/boc_valet, no `pred*` column).
* T+1 knowledge time (`known_at`): a stock session is usable only from the next ET midnight; at issue time the previous session
  must be known and today's bars are never read.
* Output: q10/q50/q90 plus an 80% interval widened by a split-conformal (CQR) margin from a chronologically separate calibration block.
* The baseline for "skill" is the SAME XGBoost class trained on own-session and calendar features only (no live related inputs).
  A cheaper baseline (unconditional quantiles) overstates skill: a shuffled-proxy placebo still scored 1.95% against it. Both are reported.
* Predictions live only in `var/ml/nowcast_xgb/ledger.sqlite` (`predicted` has `CHECK(predicted=1)`), never in the feed DB.
* `score_due` compares each prediction with the real bar once it exists in the feed store and records error, pinball loss,
  interval coverage and direction hit.
* Gate: offline (n_test >= `GATES["min_oos"]`, skill CI lower bound > 0, coverage 0.75-0.85) AND live (>= min_oos scored, >= min_shadow_weeks weeks,
  positive live skill). `GATES` is imported unchanged from `ai/ml/train.py`. Until both pass, status is `research_only` or `offline_pass_pending_live`.

Smoke results on real data (date-chronological, 2-session embargo; not a profit estimate):

| group | rows | test n | skill vs own-feature baseline (95% CI) | coverage | status |
|---|---|---|---|---|---|
| stocks_15m | 216,971 | 54,366 | +2.5% (+0.4% .. +4.5%) | 0.762 | offline pass, pending live; coverage is at the lower edge; MAE only 2.9% below zero-forecast |
| fx_1d | 990 | 246 | -0.2% (-1.9% .. +1.3%) | 0.902 | research_only (fails skill and coverage) |
| stocks_1m | 0 overlapping rows | - | - | - | insufficient_data (kraken 1m history ~7 h, coinbase 1m just started) |

The in-sample directional hit of stocks_15m (about 60%) is largely persistence of the day-so-far move and is not a trading statistic.

## 3. Crypto 1s gap fill (`ai/ml/gapfill1s.py`)

Missing seconds are filled only BETWEEN two real 1s bars and only for gaps of 2..300 s, with a log-linear bridge between the endpoints.
It uses the future endpoint, so rows carry `uses_future = 1` and `predicted = 1` (both CHECK-enforced) and are stored in
`var/ml/nowcast_xgb/pred_1s.sqlite`; `atlas_1s.sqlite` and the feed are never written, and `multires.py` never reads them.
No XGBoost is used: both endpoints are known and there is too little 1s history for a learned model to beat the bridge.

Calibration masks real interior seconds and compares the bridge with carry-forward (pooled over 34 instruments per venue, ~55 min of 1s data;
buckets with n < 200 get no interval):

| venue | gap (s) | n | bridge MAE (bp) | carry MAE (bp) | 80% half-width (bp) |
|---|---|---|---|---|---|
| coinbase | 2 | 3,482 | 0.118 | 0.139 | 0.107 |
| coinbase | 3-5 | 7,774 | 0.208 | 0.280 | 0.318 |
| coinbase | 6-15 | 7,536 | 0.528 | 0.722 | 0.797 |
| coinbase | 16-60 | 13,478 | 1.07 | 1.65 | 1.57 |
| coinbase | 61-300 | 7,790 | 3.35 | 5.13 | 5.49 |
| kraken | 2 | 172 | 0.561 | 0.677 | uncalibrated |
| kraken | 3-5 | 657 | 0.882 | 1.23 | 1.04 |
| kraken | 6-15 | 2,405 | 1.05 | 1.46 | 1.36 |
| kraken | 16-60 | 6,148 | 1.69 | 2.53 | 2.33 |
| kraken | 61-300 | 8,565 | 3.55 | 5.74 | 5.44 |

(MAE in basis points of log price; the calibration sample is in-period, so recalibrate as history grows.)

## 4. Horizon tuning (`ai/ml/horizon_tune.py`, `scripts/horizon_tune.py`)

Screen on 2 years of real 15m/1h bars: out-of-sample rank IC of a small XGBoost (60/30 chronological split with a purge of horizon + 96 bars),
date-block bootstrap CI, and the share of realized moves above the modelled round-trip cost (crypto 124 bp, US equity 4 bp + $0.01/sh, assumptions in `costs.py`).
It is a feasibility screen on signal and cost, not a P&L backtest.

| class | horizon | OOS rank IC (95% CI) | moves > cost | screen |
|---|---|---|---|---|
| crypto | 15m / 30m | +0.002 / -0.007 (CIs include 0) | 0.5% / 1.5% | drop |
| crypto | 1h / 2h / 4h | -0.020 / -0.022 / -0.032 (CIs below 0) | 3.7% / 8.3% / 16% | drop |
| crypto | 8h / 24h | +0.007 / +0.016 (CIs include 0) | 28% / 52% | no IC yet; kept for (d) because only these can clear costs |
| US equity | 15m / 30m | +0.016 / +0.014 (CIs include 0) | 77% / 83% | secondary |
| US equity | 1h | +0.025 (+0.003 .. +0.048) | 88% | keep (1 of 5 tests; weak evidence) |
| US equity | 2h / 4h | -0.008 / -0.005 (CIs include 0) | 91% / 95% | drop |

`SELECTED_FOR_D = {"crypto": (32, 96), "us_equity": (1, 2, 4)}` (in 15m bars). Milestone (d) trains these under the unchanged gates; no horizon
currently has demonstrated crypto signal, and (d) must say so if it still does not.

## 5. Coverage by market and interval (real data, 2026-10-31)

| market | finest real interval | history | notes |
|---|---|---|---|
| crypto (coinbase) | 1s trades -> 1m flow | 1s ~55 min and growing; 1m since 2026-10-30; 15m/1h since 2024-10 | 34 instruments |
| crypto (kraken) | 1s, 1m | 1s ~55 min; 1m since 2026-10-23 | 34 instruments |
| US stocks/ETFs (polygon, T+1) | 1m for 17 priority tickers since 2026-09-01; 15m/1h for 173 since 2024-11 | session N available the next day | nowcast fills the live gap, as PREDICTED |
| FX (ecb_fx, boc_valet) | 1d | 3 years | daily only; nowcast is research_only |
| gold/metals | GLD as T+1 stock only | - | no live gold proxy |

## 6. Tests

`tests/ml/test_multires.py`, `test_nowcast_xgb.py`, `test_gapfill1s.py`, `test_horizon_tune.py`: truncation invariance, poisoned-future invariance,
1m/5m/15m/1h consistency, ET/UTC alignment across DST, T+1 `known_at`, real-label guard, predicted-flag CHECKs, issue -> score against a real bar with
the feed row count unchanged, feature rows identical on a feed truncated at T, gap-fill isolation, horizon labels with no stand-in bars and no session crossing.
