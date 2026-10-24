# Evo6: setup redesign research (2026-10-24)

Research evidence from the local ATLAS feed snapshot (real bars), not a performance claim. Paper realism throughout
(1-bar latency, trade-through limits, 10% volume cap, ambiguous bars count as stops), venue costs from `atlas.ml.costs`
(Binance 24 bp round trip; US ETFs 4 bp + $0.01/share). Gross R = net R + cost R.

Reproduce:
- `ATLAS_FEED_DB=… PYTHONPATH=src python scripts/run_setup_variants.py` → `docs/research/evo6-setup-variants.{md,json}`
- `… python scripts/ml_diagnose.py --universe evo6` and `… python scripts/evolve_models.py --universe evo6 --generations 4`

## What was added (all new and toggleable; legacy setups unchanged)
- `ReplayConfig.stop_atr_mult / target_rr / max_cost_r` (default None = old behaviour): stop = entry ∓ k·ATR(14) on closed
  bars at detection, target = rr·risk, and a cost filter that skips (never fills) a setup with round-trip cost / risk above the threshold.
- `research/setup_variants.py`: 5 variants (`base`, `base_cf15`, `atr2_rr2`, `atr2_rr2_cf15`, `atr3_rr1.5_cf15`) × 15m / 1h / 4h
  (4h = complete UTC buckets of closed feed 1h bars, crypto only) × BTCUSDT, ETHUSDT, SPY, QQQ, IWM. 230 configs, 48,753 resolved trades.
- Strategy registry: 16 `research` specs `<detector>__<variant>` (off by default, toggleable, never run by the live suite).
- `RESEARCH_RETIRED[("orb_retest","15m")]`: research-retired by default, reversible (`set_retired`, `POST /api/quant/strategies/orb_retest/retired/15m`).
  `enabled_detectors(interval)` honours it; interval-agnostic callers are unchanged.

## Findings (pooled over symbols; full per-symbol table in docs/research/evo6-setup-variants.md)
| detector | tf | variant | n | gross R | net R | median cost R |
|---|---|---|---|---|---|---|
| orb_retest | 15m | base (legacy) | 1187 | −0.318 | −1.267 | 0.663 |
| orb_retest | 15m | atr3_rr1.5_cf15 | 273 | −0.097 | −0.203 | 0.110 |
| orb_retest | 1h | atr3_rr1.5_cf15 | 1433 | −0.211 | −0.277 | 0.055 |
| dual_band_breakout | 15m | base | 3920 | −0.233 | −0.793 | 0.430 |
| dual_band_breakout | 4h | base_cf15 | 219 | −0.076 | −0.158 | 0.078 |
| wick_reversal | 15m | base | 3696 | −0.256 | −0.965 | 0.548 |
| wick_reversal | 1h | atr3_rr1.5_cf15 | 1057 | −0.032 | −0.109 | 0.078 |
| prior_day_range_reversal | 15m | base | 728 | −0.057 | −0.422 | 0.305 |
| prior_day_range_reversal | 1h | atr3_rr1.5_cf15 | 1334 | −0.024 | −0.077 | 0.039 |
| **prior_day_range_reversal** | **4h** | **atr2_rr2** | 457 | **+0.069** | −0.009 | 0.072 |
| prior_day_range_reversal | 4h | atr2_rr2_cf15 | 433 | +0.070 | −0.003 | 0.069 |
| prior_day_range_reversal | 4h | atr3_rr1.5_cf15 | 456 | +0.051 | −0.002 | 0.049 |

- Wider ATR stops and the cost filter do what the evo5 diagnosis predicted for costs: median cost falls from 0.33–0.66 R to 0.04–0.12 R,
  and net R improves for every detector (e.g. wick_reversal 15m −0.97 → −0.26 R). **But gross R stays negative for 3 of 4 detectors on every
  timeframe**, so the setups still lose before costs.
- The only family positive before costs is prior_day_range_reversal on 4h crypto with ATR stops (+0.05 to +0.07 R gross; base_cf15 +0.008). Its gross 95% bootstrap CI
  still spans 0 (atr2_rr2: [−0.022, +0.164]), and it is about break-even after costs.
- Gates (n ≥ 200, net CI low > 0, DSR ≥ 0.95 over 230 trials, PBO ≤ 0.5): **0 of 230 configs pass**. PBO (CSCV, 16 blocks, daily R) = 0.06.
- Purged walk-forward selection (pick the best TRAIN config per detector, 1-day embargo, score on TEST): OOS net R is negative for all 4 detectors
  (dual_band −0.02, orb_retest −0.26, PDR −0.05, wick −0.11). Small OOS n, wide CIs.
- orb_retest 15m: the worst gross R of any legacy setup (−0.32 R) and no variant is positive before costs. Research-retired (reversible).

## ML on the positive-before-cost variant (PDR 4h atr2_rr2, BTCUSDT+ETHUSDT, 457 rows)
- Diagnosis: base rate 0.473, gross +0.069 R, net −0.009 R, median cost 0.072 R. lgbm full AUC 0.485, BSS −0.028; shuffled-label AUC 0.481 (no leakage, no signal).
- Evolution run de86779da75c (4 generations, seed 11, context + bar-type genes): best hgb/no_setup/vol_conditioned/time fitness +0.077,
  EV +0.058 R/opportunity, but Brier skill −0.031 < 0 → **no challenger beats baseline**. Small sample (4 folds of ~76 test rows).
- Nothing promoted; ML execution_permission none.

## Next
- More history for 4h (Binance 1h starts 2024-10-23) and futures/ETF 4h equivalents before trusting the PDR 4h result.
- Redesign entries for the breakout/wick families; parameter changes alone do not create gross edge.
