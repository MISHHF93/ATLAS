# ATLAS ML: feed-only meta-labeling pipeline

## Where evolution stands (2026-10-28)

The desk shows `src/atlas/ai/ml/evolution.py`, gate `evo8-strict-1` (`DSR_MIN` 0.95, `MIN_TRADES_PER_FOLD` 20, five purged folds, Bonferroni alpha 0.05). The official universe is 4h `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`, variant `atr2_rr2_cf15` (prior-day-range reversal, 2 ATR stop, cost/R cap 0.15). Latest stored file `var/ml/registry/evolution/niches_1793235961.json`: genome `ridge|full|none|time|htf`, decision abstain, strict gate failed (`min_trades_per_fold`, DSR 0.368, Bonferroni; one-sided t p-value 0.183 over 15 trials). LightGBM and XGBoost with the same full features and higher-timeframe context had fitness −0.049 and −0.106 on that book. `champion.json` is absent. `execution_permission` is `none`. The hand cannot buy or sell.

Meta-labeling (López de Prado, *Advances in Financial Machine Learning*, 2018, §3.6) filters a primary that already has an edge. It does not create that edge. Deflated Sharpe follows Bailey and López de Prado, *Journal of Portfolio Management* 40(5), 2014. `src/atlas/ai/models/quant/metrics.py` implements that formula: per-period Sharpe, raw kurtosis, and the expected-maximum threshold with the Euler–Mascheroni constant. The bar used here is 0.95. Citations live in [sources.md](sources.md). On the current 4h book the primary's gross edge is short of that bar before any model search, so another genome search on the same labels does not pass the gate.

## Registry path (status 2026-10-23)

**No registry version is eligible.** Every group fails the pre-declared gates out of sample. See
[model-card.md](model-card.md) for the real numbers and [limitations.md](limitations.md). Paper only; nothing in
`atlas.ml` places, proposes or approves orders. Safe stop and the control plane are untouched.

The sections below are this older `src/atlas/ml` path (`scripts/ml_refresh.py`, `atlas.ml.train.GATES`, including four shadow weeks). That path still exists. `registry.load_eligible()` is still the only way a registered meta-model becomes a `predict()` model. It is separate from the island search above.

## Pipeline (`src/atlas/ml`, `scripts/ml_refresh.py`)

1. **Data**: confirmed bars from the feed store (`ATLAS_FEED_DB`), point-in-time via `feed.bars(..., as_of=)`; a
   bar enters only if `start + duration <= as_of`. Every series is hashed (sha256 over OHLCV), and the registry
   records the hashes. Universe: BTCUSDT, ETHUSDT (Coinbase BTC-USD/ETH-USD candles; evidence published before 2026-10-30 used Binance data), SPY, QQQ, IWM (15m, 1h).
2. **Primary model = setup library**: the four price-action detectors (`dual_band_breakout`, `orb_retest`,
   `prior_day_range_reversal`, `wick_reversal`) are replayed bar by bar (`features/price_action/replay.py`,
   conservative OHLC fills). Every filled setup becomes one event.
3. **Labels: triple barrier** (López de Prado 2018, §3.4). Upper = setup target, lower = setup stop, vertical =
   1 trading day (crypto 96×15m / 24×1h; equity 26×15m / 7×1h). `y = 1` iff the after-cost R multiple is > 0.
4. **Meta-labeling** (López de Prado 2018, §3.6): the detector picks side, and the ML model decides *take/skip and
   size*. Features (all causal, computed on bars that closed at or before detection): returns, realised volatility
   and its percentile, ATR, volume z-scores, EMA distance/slope, range position, session clock, a vol/trend regime
   proxy, setup geometry (reward:risk, cost in R, risk/ATR, entry type), detector one-hots, and direction-signed
   interactions. Full list: `atlas.ml.dataset.FEATURES` (also stored in each manifest).
5. **Costs** (`atlas/ai/ml/costs.py`): crypto spot 124 bp round trip (60 bp taker per side at Kraken Pro's $2.5K+ tier, plus 2 bp slippage per side; earlier evidence used a 24 bp Binance figure); US
   equity 4 bp + $0.01/share round trip. These are assumptions, not measured fills.
6. **Purged + embargoed walk-forward** (§7.4): expanding window, 5 test folds. A training event *i* is kept only
   if its exit `e_i < T0 − embargo` (T0 = first test start, embargo = 1 day). Inside each training window:
   fit 60% | calibration 20% | conformal 20%, each purged against the next block.
7. **Calibration**: isotonic (Zadrozny & Elkan 2002) when n_cal ≥ 200, else Platt (1999). The calibrator refuses
   any observation time ≤ its fit horizon (`LookupError` → predict() abstains).
8. **Conformal abstention**: split conformal (Vovk et al. 2005; Angelopoulos & Bates 2021) with the nonconformity
   score `1 − p̂(y)`, `q̂` = ⌈(n+1)(1−α)⌉/n quantile, α = 0.2. Prediction set `{y : 1 − p̂(y) ≤ q̂}`. **Take only if the
   set is the singleton {1}** *and* EV > 0 (reject option, cf. Hallberg Szabadvary & Löfström 2025; Johansson et
   al. 2023). Coverage ≥ 1−α holds marginally under exchangeability, and drift breaks that assumption (see limitations).
9. **EV and size**: `EV = p·W̄ − (1−p)·L̄` with per-detector mean winner/loser R from the fit block;
   size = ¼-Kelly `f = 0.25·(b·p − (1−p))/b`, `b = W̄/L̄`, clipped to [0,1]. This is a proposal input only.
10. **Variants (pre-declared before the run)**: {logit, HGB} × {EV-only, EV+conformal}; primary = `hgb_conformal`.
    `take_all` is the unfiltered setup library baseline.

## Metrics

- Brier `mean (p−y)²` and skill `1 − Brier/Brier(base rate of training fold)`; log loss vs base-rate log loss.
- ECE (10 equal-width bins) and a reliability diagram (UI: Models & testing → ML meta-labels).
- AUC (Mann–Whitney).
- Net-of-cost expectancy: mean and total R of taken setups, after costs.
- **DSR** (Bailey & López de Prado 2014): PSR of the daily R series against the expected maximum Sharpe of
  N = 20 trials (all variants × groups + take_all), with skew/kurtosis correction.
- **PBO** (Bailey, Borwein, López de Prado, Zhu 2017) via CSCV on daily R of the 5 strategies, 16 blocks.

## Gates (pre-declared; `atlas.ml.train.GATES`)

`n_oos ≥ 200`; Brier skill > 0; log loss < baseline; DSR > 0.95; PBO < 0.5; ≥ 4 shadow weeks
(`control/policy/schemas.py`). The shadow gate cannot be met offline, so the first eligible version can appear only
after 4 weeks of forward shadow records. The registry writes `status: eligible` only if all gates pass;
`registry.load_eligible()` is the only path into a `predict()` ModelRegistry.

## Registry (`var/ml/registry/<version>/`, git-ignored)

`manifest.json` (data hash, per-series hashes and providers, features, code sha, all metrics, folds, gates, status),
`model.pkl`, `model_card.md`, `drift.json`, `reference.json`. Version = `atlas-meta-<group>-<datahash10>-<sha7>`;
immutable, and re-registering the same version is a no-op.

## Refresh (`scripts/ml_refresh.py`)

`--backfill` fetches only bars after the last stored bar → rebuilds the PIT dataset → walk-forward retrain → registers
→ drift → shadow. **Shadow** records only *open* setups (filled, unresolved) detected after the calibrator's fit
horizon, so each record is a forward prediction made before its outcome existed. Records are resolved on later
runs and deduplicated by candidate id. File: `var/shadow/ml_meta_shadow.jsonl` (ShadowCollector format, so
`weekly()` works).

## Drift (`atlas/ml/drift.py`)

PSI per feature, last 30 days vs earlier history (< 0.1 stable, 0.1–0.25 moderate, > 0.25 significant). ADWIN
(Bifet & Gavaldà 2007), δ = 0.002, on the OOS squared-error and hit streams:
cut when `|μ0−μ1| ≥ sqrt(ln(4|W|/δ)/(2m))`, `m = 1/(1/n0+1/n1)`. Drift only reduces risk: it never promotes.

## Retrieval (`atlas/ml/retrieval.py`)

Okapi BM25 (k1 = 1.5, b = 0.75; Robertson & Zaragoza 2009) over `docs/**` (md/txt/csv/json, including
`docs/spec/evidence`) and the model cards, split into heading-delimited passages. `/api/ml/explain` returns a status
summary plus passages cited as `path#Lstart-Lend`.

## API (read-only, `/api/ml`)

`GET /registry`, `/models/{v}`, `/models/{v}/drift`, `/shadow`, `/refresh/last`, `/search?q=`, `/explain?version=`.

## Why gradient boosting, not deep sequence models

On tabular, low signal-to-noise features, tree ensembles match or beat deep nets (Grinsztajn et al. 2022).
Recent intraday studies find that deep sequence models do not survive costs (Kyhl 2025), while GBMs give at best weak
gains. With ~9k events, a TCN/LSTM would overfit. Revisit once there are ≥ 10× the events.
