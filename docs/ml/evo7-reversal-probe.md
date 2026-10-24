# evo7: prior_day_range_reversal probe and ML meta-label filter

Paper research only. `execution_permission: none`. No profitability claim.

## Probe (docs/research/evo7-reversal-probe.md)
- Candidates come from the evo6 `prior_day_range_reversal__atr2_rr2` replay. It uses 1-bar latency, trade-through limits, a 10% volume cap, and treats an ambiguous bar as a stop.
- The grid has 540 trials: entries {stop, limit_0.25, limit_0.5} x exits {rr2, rr1.5, partial_1_2, rr2_tstop} x filters {none, htf_with, htf_counter, vol_low, vol_high} x costs {taker, maker_assumed}.
  - Filters use closed bars only: the daily EMA20 from completed UTC days, and the ATR% percentile over the last 200 bars.
  - `maker_assumed` is an assumption, not a measured fill rate: 2 bp per maker leg and 12 bp per taker leg, crypto only.
- Universes:
  - crypto_core: BTC and ETH.
  - crypto_alts: 28 alts. Their 15m data starts on 2026-04-27; 1h is derived from complete 15m hours.
  - us_etf: SPY, QQQ and IWM, 1h.
  - Futures and FX were excluded because their intraday data only starts on 2026-08-26.
- Result: 0 of 540 trials pass. PBO is 0.109 and DSR is 0.0 for every top cell. The baseline reproduces evo6 exactly: 457 trades, gross +0.069 R, net -0.009 R.
  - Best core 4h cell: stop/rr2/vol_low. 259 trades, gross +0.173 R [+0.046, +0.295], net +0.091 R (maker) / +0.082 R (taker). The net CI spans 0.
  - Purged walk-forward OOS net R:
    - core 4h: +0.039 [-0.109, +0.186], n 209
    - alts 4h: -0.105
    - core 1h: -0.147
    - alts 1h: -0.150
    - ETF 1h: -0.119
  - The lead does not generalize to the alts. Limit entries never ranked on top. Maker costs change results only slightly.

## ML (universes `evo7` 4h and `evo7_1h`, 30 crypto symbols, PDR atr2_rr2 labels)
| run | rows | full-model AUC | shuffled AUC | decision |
|---|---|---|---|---|
| 489861863694 (4h) | 1379 | 0.473 | 0.502 | no challenger beats baseline (take-all EV -0.041 R) |
| 432dba69a77e (1h) | 1903 | 0.513 | 0.488 | research champion under the existing gates |

- The 1h champion is `logit|no_signed|regime=none|time|context=macro`.
  - OOS EV is +0.019 R per opportunity vs take-all -0.170 R. Brier skill is +0.0009, ECE 0.041 and AUC 0.552. It takes 419 of 1586 trades (coverage 0.26).
- **Fragile.** Fold EVs are -0.035, +0.007, +0.008, +0.005 and +0.108. Folds 1-3 take only 2-11 trades, and almost all of the edge comes from the last fold. Brier skill is barely above 0. 36 genomes were tried, and the evolution gate does not deflate for that.
- This is a research champion only. `promoted_to_execution: false`, `execution_permission: none`.
- Chart markers follow the latest run, 432dba69a77e, so they show on crypto 1h charts. The earlier 15m markers from f8e7de55c108 are no longer the latest.
