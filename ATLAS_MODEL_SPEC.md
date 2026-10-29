# ATLAS model specification (v1, evo-14)

Status: research. Paper only. Every model here has `execution_permission = none` and can only **propose**; the control plane sizes and the unchanged `risk_policy.yaml` decides. Nothing below is a claim that any model makes money. Where a model fails a gate it is shown as **research / below gate**.

## 0. What exists, what evo-14 adds, what is deferred

| Area | Today (already in the repo) | evo-14 adds (`src/atlas/ai/ml/directional/`) | Deferred |
|---|---|---|---|
| Targets | Meta-label per setup: triple barrier from a rule-based detector (`ai/ml/dataset.py`) | Detector-free direction: CUSUM events, vol-scaled triple barrier, vol-normalised forward return (`labels.py`) | Multi-horizon heads |
| Features | `ai/ml/features.py` bar features incl. VWAP/session, `vwap_features.py`, `context.py` | HAR-RV, multi-timeframe, regime, cross-asset (`features.py`) | Macro/calendar features (evo-17) |
| Models | HGB, logit, ridge, xgb, lgbm (`train.make_model`) | HGB primary, logit challenger, quantile HGB for the forward-return interval (`pipeline.py`) | Sequence models, frozen foundation-model embeddings (evo-21) |
| Meta-labelling | `train.fit_meta` per setup | Direction model is the primary; the existing meta-model still gates setups | Meta-model on top of directional side |
| Calibration | Platt/isotonic, split conformal (`calibration.py`) | Same calibrators with a probability floor; adaptive conformal (`aci.py`) | Venn-Abers |
| Ensemble / QD | `evolution.py` governed loop, `niche_archive.py` MAP-Elites, `market_islands.py` | Reuses the same trial accounting | QD over directional genomes (evo-21) |
| Validation | Purged + embargoed walk-forward (`cv.py`), DSR/PBO (`metrics.py`), `GATES` (`train.py`) | Same splits and gates, plus an ACI coverage gate and a quantile-skill gate | Combinatorial purged CV |
| Costs | Flat per-venue bps (`costs.py`) | Same, converted to R per event | Spread + impact model |
| Account-aware | `broker_state/`, read-only snapshots | Read-only sizing-feasibility context at inference (`features.account_context`), **not** a training column | Phases 2-3 (evo-16) |

## 1. Notation

Bars `i = 0..n-1` with end time `e_i`, open `o_i`, high `h_i`, low `l_i`, close `c_i`, volume `v_i`. Log return `r_i = ln(c_i / c_{i-1})`. A quantity "at bar i" uses bars `<= i` only. `H` is the vertical-barrier horizon in bars. `Phi` is the standard normal CDF.

Volatility estimate (labels): `sigma_i = sqrt( EWMA_span(r^2)_i )`, span 100, `adjust=False`, backward-looking. Features use the EWMA standard deviation of `r` with the same span.

## 2. Targets

### 2.1 Event sampling (symmetric CUSUM)
```
S+_i = max(0, S+_{i-1} + r_i)        S-_i = min(0, S-_{i-1} + r_i)
event at i  iff  S+_i > h_i  or  S-_i < -h_i ,   h_i = m * sigma_{i-1},  m = 2
on an event: S+ = S- = 0
```
The threshold uses `sigma_{i-1}` so the decision at `i` never sees a later bar.

### 2.2 Triple barrier (long-side view)
For an event at `i`, entry `c_i`, width `w_i = k * sigma_i * sqrt(H)` (k = 1, log units).
```
U_i = c_i * exp(+w_i)       D_i = c_i * exp(-w_i)       vertical barrier: bar i+H
scan j = i+1..i+H:   hit_up = [h_j >= U_i]    hit_dn = [l_j <= D_i]
label  y_i =  +1  first hit is up only            ret_i = +w_i
              -1  first hit is down only          ret_i = -w_i
               0  both in one bar (ambiguous)     ret_i = ln(c_j / c_i)
               0  none by the vertical barrier    ret_i = ln(c_{i+H} / c_i)
```
Training target for the direction classifier: `y_up = 1[ret_i > 0]`. Events whose horizon runs past the data are dropped (unresolved). `exit_at_i = e_{i+H}`, the latest bar the label could have used, which is what purging uses.

### 2.3 Forward-return target (volatility-normalised)
```
fwd_i = ln(c_{i+H} / c_i) / ( sigma_i * sqrt(H) )
```
A quantile forecast of `fwd_i` gives the interval shown on the chart: `price_tau = c_i * exp( q_tau * sigma_i * sqrt(H) )`.

### 2.4 Sample weights (overlapping labels)
Average uniqueness (AFML 4.4): with `1_{t,i} = 1[bar t in (i, i+H]]` and concurrency `c_t = sum_i 1_{t,i}`,
```
u_i = mean over t in (i, i+H] of ( 1 / c_t ),   w_i = u_i / mean(u)
```
(`train.average_uniqueness`). Weights enter every fit; metrics are unweighted.

### 2.5 Meta-label (existing pipeline, per setup)
For a rule-based setup with side `s in {+1,-1}`: `R_net = s * ret / w - cost / w` and `y_meta = 1[R_net > 0]` where `cost` is the round-trip cost as a log-return fraction (section 9).

## 3. Features

Every feature at bar `i` uses only bars `<= i`. Cross-asset values at own bar `i` use the last reference bar whose **end** is `<= e_i` (`merge_asof`, backward). Tests perturb every bar after `i` and require identical features and events.

1. **Base (existing)** `BAR_FEATURES`: returns, ATR-scaled range/body/wick, EMA distance, volume z-scores, session/time, VWAP distance and session-anchored VWAP regime, vol percentile.
2. **HAR-RV (Corsi 2009).** With `d` bars per day for the venue calendar (24x7 or RTH):
   `RV^{(n)}_i = sum_{t=i-n+1..i} r_t^2`, `log_rv_d = ln RV^{(d)}`, `log_rv_w = ln RV^{(5d)}`, `log_rv_m = ln RV^{(22d)}`; ratios `log_rv_d - log_rv_w`, `log_rv_w - log_rv_m`.
   The classical forecast regression `RV_{t+1} = b0 + b_d RV_t + b_w RV^w_t + b_m RV^m_t + eps` is the volatility baseline that any learned volatility head must beat.
3. **Multi-timeframe.** For `k in {4,16,64,256}`: `z_ret_k = ln(c_i/c_{i-k}) / (sigma_i sqrt(k))`. For `k in {16,64,256}`: `range_pos_k = (c_i - min l) / (max h - min l)` over the last `k` bars.
4. **Regime.** `trend_strength_64 = z_ret_64`; `drawdown_256 = c_i / max_{256} h - 1`; `volvol_64 = std_{64}(sigma) / mean_{64}(sigma)`; `high_vol_flag = 1[sigma_i > expanding median of sigma up to i]`. A Markov-switching filtered probability `P(s_i = high | r_{<=i})` (Hamilton 1989; `statsmodels.MarkovRegression`) is specified for evo-21 and is not used yet.
5. **Cross-asset** (reference per group: crypto -> BTCUSDT, equity -> SPY, gold -> GLD; the reference itself gets none):
   `x_R_ret_L = ln(C^R_i / C^R_{i-L})` for `L in {1,4,16}` on the aligned reference series, and `x_R_corr_64 = corr_{64}(r_i, r^R_i)`.
6. **Account-aware (read-only).** From a broker snapshot: equity `E`, buying power `BP`, open risk `OR`, currency. Only the bar-derived stop distance is a training feature (section 3A); the snapshot values are used only at inference for **sizing feasibility**: `stop_frac = w_i`-implied stop distance, `max_units = floor( min(risk_cap * E / (stop_frac * c_i), BP / c_i) )`. The snapshot values are never model inputs because an account snapshot has no history in the feed; training on them would learn fabricated history.

## 3A. Layer features and the features inventory (evo-14, 25 chart layers)

The chart now has 25 layers (15 existing plus 10 new, all off by default, each with an honest `status` and `reason`). One implementation
(`src/atlas/ai/ml/directional/layers25.py`) produces both the number on the chart and the number the model trains on. Every value at bar `i`
uses bars `<= i`, reference bars with `end <= e_i`, and schedules published ahead of time. A value that cannot be computed is `NaN`, never `0`.
Rows that are `NaN` in a column stay `NaN` for tree models (native missing-value handling); the logistic challenger imputes with medians fitted on the fold's training rows only; a column with no finite value anywhere in a fold's fit window is set to a constant for that fold (`_dead_to_zero`: it carries no information and is not a claim that the value is zero), and `layer_feature_coverage` in every run report states which columns were all-NaN.

### 3A.1 Equations of the ten new layers

Let `c_i` close, `r_i = ln(c_i/c_{i-1})`, `sigma_i = EWMA std of r (span 100, min 20)`, `H` = horizon bars, `e_i` = bar end time.

1. **Conformal forecast band** (`cb_qhat, cb_halfwidth_pct, cb_cover_64`). Score of the band issued at `j`, known only at `j+H`:
   `s_j = |ln(c_{j+H}/c_j)| / (sigma_j sqrt(H))`. At bar `i`, `qhat_i` is the `min(1, (1-alpha)(1+1/W))` quantile (higher interpolation) of the last `W = 250` scores with `j + H <= i` (min 60), `alpha = 0.2`.
   Half-width `h_i = qhat_i sigma_i sqrt(H)`; band `[c_i e^{-h_i}, c_i e^{+h_i}]`. `cb_cover_64` is the share of the last 64 bands **already issued** (at `i-H`) that contained the realised move.
   This is split-conformal with a rolling calibration set (Vovk et al.; Angelopoulos and Bates 2021). It is marginal, not conditional, and exchangeability only holds approximately for overlapping windows; the measured coverage is shown for that reason.
2. **Multi-timeframe confluence** (`mtfc_score, mtfc_agree, mtfc_n_up, mtfc_slope_score`). `z^{(k)}_i = ln(c_i/c_{i-k}) / (sigma_i sqrt(k))`, `k in {4,16,64,256}` **bars of the chart's own interval** (bar multiples, not calendar timeframes).
   `score = mean_k sign(z^{(k)})`, `agree = |score|`, `n_up = #{z>0}`. `slope_score = mean over spans {20,80,320} of sign(EMA_span(c)_i - EMA_span(c)_{i-5})`.
3. **Economic events** (`ev_hrs_to_next, ev_hrs_since_last, ev_in_window`). From the official schedules already in the app (BLS, Treasury; FRED when keyed): `ev_hrs_to_next = (min{t_e : t_e > e_i} - e_i)/3600` and `ev_hrs_since_last` likewise, capped at 168 h, `ev_in_window = 1[ an event within ±1 h ]`.
   **NaN outside the schedule's coverage window** `[min t_e, max t_e]`: we never extrapolate a calendar we do not hold. In training the calendar is fetched with an 800-day lookback; if the sources do not return that much history the columns are mostly NaN and the run says so (`events_note`). Earnings dates are **not** covered: no key-free source lists upcoming earnings; the chart layer says so (`earnings.status = unavailable`).
4. **Global market clock** (`clk_n_open, clk_us_open, clk_eu_open, clk_asia_open`). For each of NYSE, TSX, LSE, Xetra, TSE, HKEX: open at `e_i` iff local weekday is Mon-Fri and local time is inside the regular session (TSE and HKEX have lunch breaks), using `zoneinfo`, so daylight-saving shifts are handled. `n_open` is the count; the three bloc flags are `1[any venue of the bloc open]`.
   **Exchange holidays and early closes are not modelled** (stated on the layer). The chart renders the same table in the user's timezone (`tz` query parameter, default America/Toronto).
5. **Cross-asset correlation** (`xcl_{usd,gold,btc,spy}_{corr,beta}_64`). Roles resolve to the first stored symbol: usd -> DXY else UUP; gold -> GLD else XAUUSD; btc -> BTCUSDT else BTC-USD; spy -> SPY; the instrument is never its own proxy.
   Proxy bar for own bar `i` is the last proxy bar with `end <= e_i` (`merge_asof`, backward). `corr = corr_{64}(r, r^P)`, `beta = cov_{64}(r, r^P)/var_{64}(r^P)`. Missing proxy data -> NaN and the layer lists which proxies are missing. DXY itself is not stored; UUP is the proxy when present.
6. **Volatility cone** (`vc_pct_{4,16,64,256}, vc_term_slope`). `rv^{(h)}_i = sqrt( mean_{t=i-h+1..i} r_t^2 )`; `vc_pct_h` = mid-rank percentile of `rv^{(h)}_i` within its own last 500 values; `vc_term_slope = ln(rv^{(16)}/rv^{(256)})`. The chart holds about 600 bars, so the on-screen cone uses the history it has (at least 100 values) and states the window; the training feature uses the full 500 and is NaN until it exists.
7. **Liquidity and spread cost** (`liq_cs_spread, liq_amihud, liq_dvol_z, liq_cost_r`). Corwin-Schultz (2012) high-low spread: `beta = ln(h_t/l_t)^2 + ln(h_{t-1}/l_{t-1})^2`, `gamma = ln(max(h_t,h_{t-1})/min(l_t,l_{t-1}))^2`, `alpha = (sqrt(2 beta) - sqrt(beta))/(3-2sqrt2) - sqrt(gamma/(3-2sqrt2))`, `S = 2(e^alpha - 1)/(1 + e^alpha)` floored at 0, EMA-20, in bps.
   Amihud illiquidity `EMA20(|r|/dollar volume)` (log10); `liq_dvol_z` = z-score of `ln(dollar volume)` over 64 bars; `liq_cost_r = (cost_bps/1e4) / (sigma_i sqrt(H))` = assumed round-trip cost as a fraction of one stop distance.
   **These are OHLCV estimates. There is no quote or order-book feed, so a measured spread does not exist here. US per-share fees are not modelled.** Zero-volume bars give NaN for Amihud and dollar volume.
8. **Model disagreement** (`dis_net_vote, dis_vote_std, dis_agree_frac`). Six fixed, untrained rule experts vote `{-1,0,+1}`: `mom_4, mom_16, mom_64` (sign of `z^{(k)}`), `rev_pos_64` (`-sign(position in 64-bar range - 0.5)`), `ema_cross` (`sign(EMA20 - EMA50)`), `rsi_rev` (`-sign(RSI14 - 50)`). `net_vote = mean`, `vote_std = std`, `agree_frac = max(#up,#down)/6`.
   The spread of the **learned** models (HGB vs logit vs quantile) is a model output; feeding it back as a feature would be circular and would need nested out-of-sample stacking. It is displayed on the chart when 2+ learned models have a score and is **not** a training feature.
9. **Account-aware size** (`acct_stop_frac, acct_notional_per_1pct_risk`). Only the bar-derived part is a feature: `stop_frac_i = sigma_i sqrt(H)` and `notional / equity that risks 1% at that stop = min(0.01/stop_frac_i, 50)`. The account snapshot (equity, buying power, minimum order, fractional support) is **read-only chart context and inference-time sizing feasibility**; it has no history, so training on it would teach the model today's account for every past bar. The chart card shows the policy-sized notional `equity * 0.005 / stop_frac` and whether it clears the broker minimum. Nothing here sets a limit, places an order or changes `risk_policy.yaml`.
10. **Drift alert** (`dr_vol_ratio, dr_mean_shift_z, dr_range_ratio`). `ln(std_{32}(r) / std_{256 prior}(r))`; `(mean_{64}(r) - mean_{256 prior}(r)) / (std_{256 prior}(r)/sqrt 64)`; `ln(mean_{64}(range/c) / mean_{256 prior}(range/c))`. Level: `alert` if `|vol|>0.5` or `|z|>3` or `|range|>0.5`; `watch` at 0.3 / 2 / 0.3. This is **market-data drift** only. Model drift (live errors, ADWIN) needs resolved live predictions and is reported elsewhere.

**Existing layers whose numbers were not yet model inputs** (`ex_avwap_dist_atr, ex_vp_poc_dist_atr, ex_vp_va_pos, ex_pd_range_pos`): distance from the anchored VWAP of the latest swing pivot **confirmed by bar `i`** (pivot `p`, `n = 5`, known at `p+5`); distance to the volume-profile point of control and the position inside the value area from the trailing 300 bars (24 bins, refreshed every 8 bars and held, so it is stale by less than 8 bars and never ahead); position within the previous UTC day's range.

### 3A.2 Which of the 25 layers train the model

| Layer | Contributes features | Where |
|---|---|---|
| vwap | yes | `VWAP_FEATURES` (5) in `BAR_FEATURES` |
| anchored_vwap | yes | `ex_avwap_dist_atr` |
| sessions | yes | `hod_*`, `dow_*` (time) and `clk_*` (venue hours) |
| volume_profile | yes | `ex_vp_poc_dist_atr`, `ex_vp_va_pos` |
| regimes | yes | `rv_pctile_480`, `trend_sign` and the 4 regime features |
| zones | yes | `ex_pd_range_pos`, `dist_hi64/lo64_atr` |
| setups | yes (meta stack only) | `SETUP_FEATURES` (9) in the meta-label stack; the directional model has no setup |
| 10 new layers | yes | 39 columns (table 3A.3) |
| ml_markers, ml_probability, predictions, prediction_zone, outcomes, conviction, trade_lines, marker_details | **no** | These are model outputs, realised outcomes, or drawing aids. Using them as features would be circular (model output feeds the model) or leak the label (outcomes). |

So the model trains on every layer that is an input (17 of 25). The other 8 are outputs or outcomes by definition and are excluded on purpose; claiming otherwise would be false. `directional_prediction` is an extra output layer and is not one of the 25.

### 3A.3 Inventory: exact counts, enumerated from the code

`PYTHONPATH=src python scripts/feature_inventory.py --json` prints these from the tuples the trainers import (a test pins them).

| Feature set (where used) | Before evo-14 | After evo-14 |
|---|---|---|
| Directional research pipeline (evo-14, one reference instrument) | 51 | **94** |
| Meta-label stack `dataset.FEATURES` (registered models store their own list) | 45 | 45 (unchanged) |
| Vertical-slice research stack `RESEARCH_FEATURE_NAMES` | 21 | 21 (unchanged) |
| Representation genome `REP_FEATURES` (per bar type, evolution genome) | 6 | 6 (unchanged) |

Directional breakdown, before (51): bar base 26 (`BASE_BAR_FEATURES`) + VWAP 5 + HAR-RV 5 + multi-horizon 7 (`z_ret_{4,16,64,256}`, `range_pos_{16,64,256}`) + regime 4 + cross-asset 4 (for one reference instrument; more references add 4 each).

Directional breakdown, added (+43): conformal bands 3, multi-timeframe confluence 4, events 3, market clock 4, cross-asset correlation 8, volatility cone 5, liquidity 4, model disagreement 3, account-aware size 2, drift alert 3, existing-layer gaps 4. 51 + 43 = 94.

Meta stack (45) = 26 bar + 5 VWAP + 9 setup (`dir_long, reward_risk, cost_r, risk_atr, entry_is_stop`, 4 detector flags) + 5 signed interactions (`*_x_dir`). It is not retrained or extended by evo-14: a registered model carries its own feature list, so changing the stack would break loading. Vertical-slice stack (21) = 12 bar + 4 session + 5 cross-asset.

How the added columns behave when data is missing: events are NaN wherever the schedule does not cover; cross-asset columns are NaN unless the proxy is stored at the same interval; liquidity volume terms are NaN on zero-volume feeds; the account and clock columns need only OHLC and time. The run report lists `layer_feature_coverage` (per group: columns that are entirely NaN, and the share of rows that are NaN), so a model trained on missing inputs says so.

### 3A.4 Leak controls specific to layer features

Tests perturb every bar after `k` (prices, volume) and every proxy bar after `k` and require the first `k+1` rows of all 43 columns to be identical (the event columns are checked separately because they depend on the published schedule window). A separate test shifts proxy bar ends half a bar late and shocks one proxy bar to prove an own bar never sees a proxy bar that closes after it. Conformal scores are shifted by `H` so a band's score is only read once the move it forecast has resolved.

## 4. Models

All models output a probability that the **upper** barrier is reached first (`y_up`), then calibration (section 6).

1. **Baseline (primary, pre-declared): gradient-boosted trees.** `sklearn.HistGradientBoostingClassifier(max_iter=200, lr=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2=1.0)`, sample weights `w_i`. Logistic loss `L = -sum w_i [ y ln p + (1-y) ln(1-p) ]`.
2. **Challenger: L2 logit.** Median imputation, standardise, `C = 0.05`. Same data and folds.
3. **Interval head: quantile GBM.** For `tau in {0.1, 0.5, 0.9}` minimise the pinball loss `rho_tau(u) = max(tau u, (tau-1) u)`, `u = fwd - q_tau(x)`, with `HistGradientBoostingRegressor(loss="quantile")`. Skill vs the unconditional training quantile: `1 - mean_tau rho(model) / mean_tau rho(baseline)`.
4. **Sequence models (specified, deferred).** A GRU/TCN over the last `L` normalised feature vectors `x_{i-L+1..i}`: `h_t = GRU(h_{t-1}, x_t)`, `p = sigma(w^T h_L + b)`, trained with the same loss, weights, folds, calibration and gates. Entry condition: it must beat the GBM on the **same** out-of-sample rows, with the extra trials counted in DSR. No torch on the current box, so none is trained yet.
5. **Frozen foundation-model embeddings (specified, deferred).** `z_i = f_theta(c_{i-L+1..i} / c_i)` with `theta` frozen (Chronos-2, TimesFM 2.5 or similar), reduced by PCA fitted on the training block to `d <= 8` dimensions, appended to the feature vector. No fine-tuning. Licence checks first (Moirai is non-commercial; TimesFM 3.0 terms not verified). Recent finance benchmarks find general time-series foundation models do not reliably beat simple baselines out of the box, so this is a challenger and nothing more.

## 5. Meta-labelling (López de Prado 2018, ch. 3)

Two stages: a primary rule or model proposes a side `s`; a secondary model estimates `P(R_net > 0 | x, s)` and gates whether to act and how large. In ATLAS the existing `fit_meta` is the secondary model for rule setups (`ai/ml/train.py`). The directional model here is a primary only; a meta layer on its side is a later item. Expected value used for a decision:
```
EV_R = p * W - (1 - p) * L - cost_R
```
with `W`, `L` the mean winning and losing R from the fit block (never the test block).

## 6. Calibration and conformal intervals

**Calibration.** Fit on a block strictly after the model-fit block and purged against it: isotonic if the block has >= 200 rows, else Platt with soft targets and shrinkage `p = (n p_hat + 40 s) / (n + 40)`. Output clipped to `[0.02, 0.98]` in the directional pipeline because isotonic is a step function and emits 0/1 on small blocks.

**Split conformal.** Score of label `c`: `s(x, c) = 1 - p(c | x)`. With `n` held-out scores, `q_hat` = the `ceil((n+1)(1-alpha)) / n` empirical quantile; set `C(x) = { c : s(x, c) <= q_hat }`. Coverage `>= 1 - alpha` under exchangeability. Financial series are not exchangeable, so validation uses the adaptive form below. A **singleton** set is a confident call; `{0,1}` or `{}` abstains.

**Adaptive conformal inference (Gibbs and Candès 2021).** `err_t = 1[y_t not in C_t]`, `alpha_{t+1} = alpha_t + gamma (alpha - err_t)`. The set uses `q_hat` at level `alpha_t` over the last `W` **resolved** scores (a score enters only once its label has resolved, `resolved_at <= t`). Finite-sample guarantee for any sequence:
```
| (1/T) sum_t err_t - alpha |  <=  ( max(alpha_1, 1 - alpha_1) + gamma ) / ( gamma T )
```
Defaults `alpha = 0.2`, `gamma = 0.01`, `W = 500`. Reported with the empirical coverage, the gap and the bound.

## 7. Ensemble and quality-diversity evolution

**Ensemble.** Average of calibrated probabilities only among members that pass the gates individually: `p_ens = sum_m a_m p_m` with `a_m >= 0`, `sum a_m = 1`, weights set on the **calibration** block by minimising Brier, never on test. A member that fails a gate has weight 0.

**MAP-Elites (Mouret and Clune 2015).** Genome `g` (model kind, feature groups, horizon multiplier `k`, CUSUM multiplier `m`, bar type). Descriptor `d(g)` = cell `(island, session, vol tercile)` (`niche_archive.py`). Archive `A: cell -> (g, fitness)`; insert a child iff `f(g') > f(A[d(g')])`. Fitness is computed on **inner** folds only; the held-out test rows are used once, for the final report. Every evaluated genome counts as a trial `N` in the DSR below, including losers.

## 8. Validation

**Walk-forward with purge and embargo.** Train block `Tr`, test block `Te` (time-ordered). Purge: keep a training row `i` only if `exit_at_i < min_{j in Te} t_j - embargo` (embargo 1 day). Inside `Tr`, three further blocks, each purged against the next: fit (60%), calibration (20%), conformal (20%). 5 folds; the out-of-sample set is the concatenation of the test blocks. (`cv.walk_forward_splits`, `cv.inner_split`.)

**Deflated Sharpe Ratio (Bailey and López de Prado 2014).** Let `SR_hat` be the per-period Sharpe of the pre-declared primary strategy's daily net-R series, `T` its length, `g3`, `g4` its skewness and kurtosis, `N` the number of trials tried (all variants x all groups), `V` the cross-trial variance of Sharpe ratios, `gamma_E = 0.5772`:
```
SR0 = sqrt(V) * [ (1 - gamma_E) Phi^{-1}(1 - 1/N) + gamma_E Phi^{-1}(1 - 1/(N e)) ]
DSR = Phi( (SR_hat - SR0) sqrt(T - 1) / sqrt( 1 - g3 SR_hat + ((g4 - 1)/4) SR_hat^2 ) )
```
Gate: `DSR > 0.95`.

**Probability of Backtest Overfitting (Bailey et al. 2017, CSCV).** Split the trials' return matrix (rows = days, columns = variants) into `S = 16` blocks; for each of the `C(16, 8)` train/test splits take the in-sample best variant `n*`, its out-of-sample relative rank `omega`, and `lambda = ln( omega / (1 - omega) )`. `PBO = P(lambda <= 0)`. Gate: `PBO < 0.5`.

**Gate list** (`GATES` inherited unchanged, two added; all must pass for the label "offline gates passed; shadow pending"):
`n_oos >= 200` | `Brier_skill > 0` vs the training base rate | `logloss < baseline` | `DSR > 0.95` | `PBO < 0.5` | ACI coverage `>= 0.75` at target 0.80 | quantile pinball skill `> 0` | `shadow weeks >= 4`. The shadow gate cannot pass at training time, so **no model is ever marked eligible by this pipeline**; failing any other gate yields **research / below gate**.

## 9. Costs and slippage

Net R of a taken event with side `s`:
```
R_net = s * ret / w  -  cost_R ,    cost_R = ( c_rt_bps * 1e-4 ) / w
```
`c_rt_bps` is the round-trip cost from `ai/ml/costs.py` (crypto 24 bps, gold 4 bps, US equity 4 bps plus a per-share fee that is **not** modelled here, so equity R is slightly optimistic and says so). Specified but not implemented: half-spread plus square-root impact, `slip = 0.5 * spread + Y * sigma * sqrt( Q / ADV )` with `Y ~ 1`, and FX conversion cost for non-CAD instruments (evo-17). Costs are charged on every taken event, including losers.

## 10. Sizing hand-off (the ML only proposes)

The model emits a **proposal**: `(direction, p_hat, EV_R, sigma_hat, conformal set, q_10/q_50/q_90 band, label)` and nothing else. The control plane then:
1. Rejects unless the label is not "no model" and the conformal set is a singleton agreeing with the direction (otherwise abstain; cash is valid).
2. Computes a fractional-Kelly **cap**: `f = c * ( p_hat * b - (1 - p_hat) ) / b`, `b = W / L`, `c = 0.25`, clipped to `[0, 1]` (`train.KELLY_FRACTION`).
3. Converts to units using the stop distance and the read-only account snapshot (section 3.6), then applies `risk_policy.yaml` (unchanged), which can only shrink or reject.
No ML output can place, modify or cancel an order. Everything stays paper.

## 11. Reporting rules

Only out-of-sample numbers are shown: `n_oos`, base rate, Brier and its baseline, log loss, AUC, ECE, ACI coverage/gap/bound, pinball skill, per-instrument rows, and net R **after assumed costs, with the trial count**. No annualised return, win-rate headline or "profit" wording. Synthetic-data tests prove the machinery (leakage, coverage bound, gates reject noise); they say nothing about markets.

## 12. References

- López de Prado, *Advances in Financial Machine Learning* (2018): CUSUM 2.5, triple barrier and meta-labelling ch. 3, uniqueness 4.4, purged k-fold ch. 7.
- Bailey and López de Prado, "The Deflated Sharpe Ratio" (2014). Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" (2017).
- Gibbs and Candès, "Adaptive Conformal Inference Under Distribution Shift" (2021), arXiv:2106.00170. Angelopoulos and Bates, "A Gentle Introduction to Conformal Prediction" (2021). Zaffran et al., AgACI (2022).
- Corsi, "A Simple Approximate Long-Memory Model of Realized Volatility" (2009). Hamilton (1989) regime switching.
- Mouret and Clune, "Illuminating search spaces by mapping elites" (2015), arXiv:1504.04909.
- Koenker and Bassett (1978) quantile regression; Platt (1999); Zadrozny and Elkan (2002).
