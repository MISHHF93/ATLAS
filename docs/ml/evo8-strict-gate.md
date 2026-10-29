# evo8: strict evolution gate (gate_version evo8-strict-1)

Stricter only; no existing gate or risk rule was loosened. execution_permission stays `none`, paper only.

A genome may be crowned research champion only if ALL hold (`atlas.ml.evolution.strict_gate`):

| Check | Rule |
|---|---|
| beats_baseline | unchanged evo rule (EV > max(0, take_all) and BSS > 0) |
| all_folds_evaluated | every purged walk-forward fold produced a result |
| min_trades_per_fold | >= 20 taken trades in every fold |
| majority_folds_positive | positive taken R in > n_folds/2 folds |
| dsr | deflated Sharpe >= 0.95, trials = all ok genomes in the run |
| bonferroni | one-sided t-test p x n_trials < 0.05 |

`scripts/regate_evolution.py` re-evaluates an existing run on identical data (hash-checked) and demotes a champion that fails (`demoted_<run>.json`, status `research_only`, reasons recorded).

## Re-evaluation of 432dba69a77e (evo7 1h)
Reproduced exactly (fitness 0.0498, data hash f3dc0c85…, 1903 rows). **Demoted to research-only.**
- Failed: min_trades_per_fold (min 2 < 20; fold counts 127/2/11/4/275), dsr (0.0015 < 0.95; SR/trade 0.054 vs expected max 0.198 over 36 trials), bonferroni (p 0.134 x 36 -> 1.0).
- Passed: beats_baseline, all folds evaluated, 4/5 folds positive.
- No genome in that run passes the strict gate.

## Stored run niches_1793221168 (2026-10-28)

Official 4h book, variant `atr2_rr2_cf15`, 710 rows, seed 16. Island genome `ridge|full|none|time|htf` beat its take-all baseline (EV per opportunity +0.0160, take-all −0.0311, Brier skill +0.00063, AUC 0.524, 117 takes out of 594 out-of-sample rows) and failed the strict gate: minimum taken per fold 1, DSR 0.489, one-sided t p-value 0.183 at 12 trials. Niche selection abstained (`ny_pm`, vol low) because no open niche elite beat its own baseline. `promoted_to_execution` is false. No champion file was written. There is no research champion.

## Stored run niches_1793235961 (2026-10-28)

Same official book, 710 rows, seed 18, time bars only. The compact seed list now includes the stored ridge genome plus the LightGBM and XGBoost challengers on the same full feature set and higher-timeframe context. The island elite is still `ridge|full|none|time|htf` (fitness +0.0267, Brier skill +0.00063, 117 takes). It still fails: minimum taken per fold 1, DSR 0.368 (15 trials; per-trade Sharpe 0.084 against an expected maximum of 0.115), Bonferroni p 1.0. LightGBM fitness on the full book was −0.049 and XGBoost −0.106. One coarse cell, `CRYPTO_24_7|ny_pm|all`, had a LightGBM elite with fitness +0.089 that did not pass the strict gate. The open session at the end of the run was Asia with low volatility, and that cell's elite did not beat its own baseline, so selection abstained. `champion.json` was not written.

## UI / API
`/api/intel/evolution` adds `gate_version`, `strict_gate_rules`, `no_model_passes_strict_gate`, `demoted`. The ML models view shows "No research champion", the rules, demoted badges and a strict-gate column. Chart 1h overlays resample complete 15m hours when no stored 1h exists, labelled "1h resampled".
