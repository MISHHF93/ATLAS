# evo9: 2-year history backfill, wider ATR / cost-filtered variants, and trend-conditioned regime gene

Source: `scripts/evolve_models.py` -> `docs/research/evo9-longer-history-and-variants.json`. Purged walk-forward folds (`n_folds=5`, `embargo=100`). Strict champion gate (`evo8-strict-1`) unchanged: beats baseline (`ev_r_per_opportunity > max(0, take_all_ev)` and `brier_skill > 0`), all folds evaluated, `>= 20` taken trades per fold, positive EV in a majority of folds (`>= 3/5`), Deflated Sharpe Ratio `>= 0.95` across all genomes tried, and Bonferroni-adjusted `p < 0.05`. No profitability claim; `execution_permission: none`.

## Changes tested in Round 9
1. **Full 2-year multi-symbol history (`2024-10-25..2026-10-25`)**: Backfilled 730 days of `15m` (`~70,080` bars/symbol) and `1h` (`~17,519` bars/symbol) plus 1,095 days of `1d` bars across all 34 crypto symbols (`EVO9_SYMBOLS`). Previously, 32 of 34 altcoins only started on `2026-04-27`.
2. **Causal HTF/Macro join alignment**: Fixed `build_population_data` in `src/atlas/ml/evolution.py` so `htf_frame(sd.bars)` is re-indexed by bar close (`b.end`) rather than bar open (`b.start`) before joining on `t = detected_at = b.end`, and `add_macro` queries `end = data.t` directly.
3. **Cost-aware setup variants (`src/atlas/research/setup_variants.py`)**: Added wider-stop, tighter cost-filter variants (`atr2.5_rr2_cf10`, `atr3_rr2_cf08`, `atr2_rr1.5_cf12`) to reduce round-trip spread/slippage drag relative to stop distance (`median cost_r` drops from `0.042 R` on `atr2_rr2` to `0.034 R` on `atr2.5_rr2_cf10` and `0.028 R` on `atr3_rr2_cf08` on `4h`).
4. **Trend-conditioned regime gene (`regime=trend_conditioned`)**: Added `reg_trend_with`, `reg_trend_counter`, and signed feature interactions `{s}_x_trend` alongside `vol_conditioned`.
5. **Explicit `research-only` chart marker labelling (`src/atlas/intel/markers.py`)**: When `champion()` is `None` (no genome passes `strict_gate`), OOS evolution markers carry `"research_only": True`, `probability_label` includes `"research-only"`, `risk_status` states `"research-only (no research champion; failed strict gate; ML cannot authorize)"`, and class summaries explicitly note that no model passed the strict champion gate.

## Walk-forward results across 2-year history
- **`evo7_1h_full_2y_history` (`run_id=ae9f7c4dbbe2`, `variant=atr2_rr2`, `n_rows=46,249`, 25 genomes)**:
  - On the full 2-year altcoin history (vs. the 6-month `2026-04..2026-10` window in `evo7`/`evo8`), the unconditioned `1h` `prior_day_range_reversal` take-all baseline is `-0.2817 R`.
  - Best genome: `model=xgb|features=full|regime=none|bar_type=time|context=none` (`fitness=-0.0181`, `ev_r_per_opportunity=-0.0026`, `mean_r_taken=-0.1556`, `brier_skill=-0.0055`, `auc=0.5185`, `n_taken=647`, `min_taken_per_fold=28 >= 20`, `2/5` positive folds, `dsr=6.7e-8`, `bonferroni_p=1.0`).
  - Confirms `evo8`'s finding that the prior `1h` candidate `432dba69a77e` was concentrated in the late-2026 window and does not hold over a 2-year multi-regime cycle.
- **`evo9_4h_atr3_rr2_cf08` (`run_id=62ab9b27a61f`, `variant=atr3_rr2_cf08`, `n_rows=13,417`, 25 genomes)**:
  - Take-all baseline improves from `-0.2817 R` (`1h` `atr2_rr2`) to `-0.1178 R` on `4h` with `3.0x ATR` stops and `max_cost_r=0.08`.
  - Best genome: `model=hgb|features=no_setup|regime=none|bar_type=time|context=none` (`fitness=-0.0578`, `ev_r_per_opportunity=-0.0112`, `mean_r_taken=-0.0905`, `brier_skill=-0.0166`, `auc=0.5150`, `1/5` positive folds). Fails `beats_baseline`, `min_trades_per_fold`, `majority_folds_positive`, `dsr`, `bonferroni`.
- **`evo9_4h_atr2.5_rr2_cf10` (`run_id=9ddc89415d40`, `variant=atr2.5_rr2_cf10`, `n_rows=13,462`, 25 genomes)**:
  - Take-all baseline: `-0.1408 R`.
  - Best genome uses the new `trend_conditioned` gene: `model=hgb|features=full|regime=trend_conditioned|bar_type=time|context=none`, achieving **positive fitness (`+0.0012`)**, **majority positive folds (`3/5` folds positive)**, and **`auc=0.5290`** (`ev_r_per_opportunity=-0.0075` vs. `-0.1408` take-all, `brier_skill=-0.0013`, `n_taken=1,061`, `min_taken_per_fold=0`, `dsr=4.0e-6`, `bonferroni_p=1.0`).
  - On the `prior_day_range_reversal`-only `4h` subset (`n=5,395`), `hgb|full|vol_conditioned|time|none` reaches `4/5` positive folds (`fitness=+0.0064`, `ev_r_per_opportunity=-0.0107`, `min_taken_per_fold=7`), and on `atr3_rr2_cf08` (`n=5,370`), `logit|full|none|time|htf` passes both `min_trades_per_fold` (`39 >= 20`) and `majority_folds_positive` (`3/5`), but remains slightly negative after costs (`ev_r_per_opportunity=-0.0151`, `dsr=0.0123`).

## Conclusion
0 models pass all 6 checks of `evo8-strict-1`. `champion()` remains `None`, `promoted_to_execution` is `False`, and all ML markers on `AtlasChart` stay explicitly labelled `research-only`.

