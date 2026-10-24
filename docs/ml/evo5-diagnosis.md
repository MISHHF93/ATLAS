# Why no challenger beats baseline (evo5, 2026-10-24)

Reproduce: `ATLAS_FEED_DB=… PYTHONPATH=src python scripts/ml_diagnose.py [--universe extended]`. All numbers are
from the local feed DB snapshot (real bars) with paper realism. They are not live results.

## Dataset (default universe: 15m BTCUSDT, ETHUSDT, SPY, QQQ, IWM)
- 9,531 resolved setups. Base rate (after-cost R > 0) is 0.249, mean net R is −0.891 and mean **gross** R (before costs) is −0.239. Median cost is 0.48 R.
- 6,978 rows stopped out (mean −1.69 R), with only about 110 rows per ETF. BTC and ETH dominate the sample.
- By detector (net / gross R):
  - dual_band_breakout: −0.79 / −0.23
  - orb_retest: −1.27 / −0.32
  - prior_day_range_reversal: −0.42 / −0.06
  - wick_reversal: −0.97 / −0.26
- By regime: no regime and no quarter is positive. The base rate is stable at 0.24–0.27 every quarter.
- Gross R is about −0.2 in every cost quintile, so the setups lose even before costs. The tight 15m stops make the costs heavy.

## Model checks
- lgbm on the full feature set: AUC 0.526, Brier skill −0.003, EV −0.0003 R per opportunity at 0.2% coverage. Take-all is −0.917 R.
- Leakage: with shuffled labels, AUC is 0.500 and Brier skill −0.011, so there is no leakage signal.
- Raw out-of-sample AUC per fold: 0.484, 0.532, 0.519, 0.534, 0.556.
- Permutation importance (AUC drop): risk_atr 0.013, cost_r 0.006, dist_lo64_atr 0.005. The model mostly learns that wider stops relative to ATR, and lower cost per R, do slightly better.
- Fixed in the committed script: the scratch version scored permuted data with the raw score and the baseline with the calibrated score. That biases the importances.

## Conclusion
The root cause is the primary setups, not the model choice. They have negative gross expectancy, costs of about 0.5–0.65 R per trade, and the meta-label signal is weak (AUC about 0.53). With every opportunity at about −0.9 R, the best a filter can do is abstain. That is why the best genomes take almost nothing and score EV ≈ 0, which is below the `ev > max(0, take_all)` gate.

## Improvements made in evo5 and their results (same data, folds and seed for every genome in a run)
- **§22 macro** (keyless FRED: DGS10, DGS2, VIXCLS, DTWEXBGS, CPIAUCNS) is stored in the feed `observations` table with conservative availability dates (`feeds/providers/fred_public.py`). Features are joined only from 00:00 UTC of the availability date (`ml/context.py`).
- **HTF context**: closed UTC-day and 4h buckets of the series itself, plus risk relative to the daily ATR.
- The new gene `context` takes the values none, htf, macro and htf_macro.
- Run 44f40efd9e65 (default universe, 9,531 rows): **no challenger beats baseline**.
  - Best: hgb, no_signed, vol_conditioned, heikin_ashi. Fitness −0.027, EV −0.0003, Brier skill +0.003.
  - The context genomes are no better: htf −0.036, macro −0.051, htf_macro −0.050.
- Run 30721a3ccb32 (extended: the default universe plus 1h for the same 5 symbols, 15,157 rows): **no challenger beats baseline**.
  - Adding 1h lowers the median cost to 0.35 R and raises the 1h base rate to 0.31, with 1h net R −0.49. Gross R is unchanged at −0.23.
  - The full-feature AUC rises to 0.543 and Brier skill turns positive (+0.002 to +0.009), but EV stays negative.
  - HTF context helps a little on this data: hgb/time fitness goes from −0.027 to −0.008. Macro alone does not help (−0.056).
- Nothing is promoted, and ML execution_permission stays none.

## What would actually move the needle (not done; these are changes to the primary strategy and need a founder decision)
- Wider, ATR-scaled stops or a higher timeframe, so that cost per R falls below about 0.15.
- Retire orb_retest on 15m.
- Re-label with triple barriers on primary signals that have positive gross R before any meta-labelling.
- More ETF and futures history: 15m equities start 2026-08-26 and futures 2026-08-25.
