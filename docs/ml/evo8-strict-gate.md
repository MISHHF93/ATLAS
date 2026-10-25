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
- No genome in that run passes the strict gate; there is currently no research champion.

## UI / API
`/api/intel/evolution` adds `gate_version`, `strict_gate_rules`, `no_model_passes_strict_gate`, `demoted`. The ML models view shows "No research champion", the rules, demoted badges and a strict-gate column. Chart 1h overlays resample complete 15m hours when no stored 1h exists, labelled "1h resampled".
