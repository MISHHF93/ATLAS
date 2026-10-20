# Preregistered Experiment Protocol: EXP-001 (Baseline vs From-Scratch Tree Challenger)

Status: **Preregistered & Executed on Synthetic Frozen Point-in-Time Corpus (2026-10-19)**
Execution Permission: `none` (`execution_permission: "none"` enforced across all artifacts).

## 1. Objective & Hypothesis

Evaluate whether a from-scratch gradient-boosted depth-2 regression tree (`gbdt_depth2_v1`)
trained strictly on causal point-in-time features (`lag_return_1`, `lag_return_2`,
`rolling_vol_4`) outperforms:
1. **Naive Baselines**: `last_value` (price) and `zero_return` / `no_trade` (0% net return).
2. **Linear Baseline**: From-scratch L2-regularized coordinate-descent ridge regression
   (`fit_scratch_linear_baseline`) fitted on the exact same feature matrix.

## 2. Separate Evaluation Tracks (No Cross-Track Score Pooling)

| Track | Instrument ID | Calendar Reference | Dataset ID | Assumed Cost (bps) |
| --- | --- | --- | --- | --- |
| **Competition** | `comp:btc-perp:v1` | `crypto:perp:24x7:v1` | `frozen:comp:btc-perp:1h:v1` | `4.0 bps` |
| **Open Market** | `open:spy-etf:v1` | `us-equity:xnys:v1` | `frozen:open:spy-etf:1h:v1` | `2.5 bps` |

## 3. Chronological Splits, Purge/Embargo, and Lifecycle Controls

- **Content Integrity**: Verified via `DatasetManifest.verify_content` (SHA-256) prior to training submission in `LocalScratchTrainingProvider.submit_training`.
- **Disjoint Splits**:
  - `train`: bars `0..23` (`available_at <= train_end`)
  - `validation`: bars `24..35` (`validation_start .. validation_end`)
  - `test`: bars `36..47` (`test_start .. test_end`)
  - Walk-forward evaluation enforces `purge_bars >= 1` and `embargo_bars >= 1` after `train_end`.
- **Immutable Challenger & Alias Rollback**:
  - Submitted through `TrainingCoordinator.submit` and recorded in `ExperimentStore` (SQLite).
  - Registered as an immutable `ModelRecord` in `SQLiteModelRegistry`.
  - Alias transitions (`set_research_alias` and `rollback_research_alias`) are recorded in `alias_events`.
  - `auto_promoted` is hardcoded `False`; `weights_mutated_in_place` is hardcoded `False`.

## 4. Regime-Aware Variant Gating Rule

Per Objective 7, regime-conditioned tree variants remain **locked** unless the unconditioned
from-scratch tree challenger first demonstrates independent out-of-sample MAE improvement
over **both** the naive baseline (`overall.mae < overall.naive_mae`) and the from-scratch
linear baseline (`overall.mae <= linear_baseline_report.mae`).
