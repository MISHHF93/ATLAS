# Changelog

## 2026-10-24: branch `atlas-routes-1` (from main 8cabd13; not merged, not pushed)
- Consolidated pages that did the same job under different names. Audit: `docs/audit/2026-10-24-route-consolidation.md`.
  - Risk & positions: the "Positions" tab (former `/trade/blotter`, `/control/dealing-desk`) is merged into "Account & positions". It keeps the exposure, recorded-decision and stop-protection figures and the full positions table, with one Flatten button.
  - Research lab "Microstructure" moved into Research → Chart read, next to the candle measurements.
  - Research lab "Four-Box" moved into Research → Price zones, next to the opening-range and wick-zone detectors.
  - Overview and Money → Summary now share one P&L strip (`src/ui/PnlTiles.tsx`) instead of two copies.
- Old addresses are now permanent (308) redirects generated from `pagesMap.ts` in `next.config.ts`. The 40 stub `redirect()` page files and `scripts/gen-redirects.mjs` are gone. Retired tabs (`/control?tab=positions`, `/research/lab?tab=microstructure`, `/research/lab?tab=fourbox`) redirect to the tab that took them over.
- No backend, API or risk-rule changes.

## 2026-10-24: branch `atlas-evo-1` (from atlas-full-2 97bf58f; not merged, not pushed)
- Added alternative bar builders in `features/representations`: Heikin-Ashi (features and display only), Renko (ATR), range (ATR), volume and dollar bars. They are causal and indexed by completion time. Tick bars are gated as unavailable because the feed stores bars only.
- Added a governed model-evolution loop in `ml/evolution.py`, run with `scripts/evolve_models.py`:
  - Genes: model (hgb/ridge/xgb/lgbm), regime conditioning, feature ablations and bar type.
  - Evaluation uses shared purged/embargoed walk-forward folds.
  - Fitness = OOS EV after costs + Brier skill + stability.
  - Lineage and the champion are recorded in the ML registry. There is no auto-promotion, and execution_permission is none.
- New API routes: `/api/intel/evolution`, `/evolution/run`, `/markers` and `/bars_alt`.
- Research lab now has a "Model evolution" tab. It shows "No model beats baseline" when that is the case, which it is for run d6a35224ceef.
- Opportunity markers now appear on the Levels & sweeps chart and on the desk "Model opportunities" chart:
  - Classes: ML-suggested, rule-only, risk-rejected and ML-skip.
  - Each tooltip shows probability or "uncalibrated/LOW_CONFIDENCE", EV, model, risk status and outcome.
  - Markers can be toggled, and they carry the label "research signal, paper only, not advice".
- Both charts can switch the display bar type between candles, HA, Renko, range and volume, on the real time axis.
- Lab variants now report `zero_trade_reason`. Gold snapback/ORB on 15m give `timeframe_mismatch`, because the 08:20–08:50 box is not tiled by 15m bars.
- Fixed: daily data no longer shows as "live" on weekends. "Live" now requires the last bar to be at most min(2×bucket, 1h) old.
- Merged `intel/memory.py` into `research/memory.py`.

## 2026-10-24: branch `atlas-sfp-1` (not merged)
- Added a price-level suite: CME/COMEX calendar, liquidity level registry, shared level interaction engine, SFP, gold opening box ORB and snapback (GC/MGC only), HTF bias, re-entry governor, unified candidate contracts with resolve.
- Added a strategy registry with per-technique toggles (`/api/quant/strategies`). New techniques default to off.
- Added a strategy selector (`ml/selector.py`): context features plus per-family calibrated meta-labels, purged walk-forward, and baselines. Added xgb/lgbm challengers.
- Added `/api/quant/levels` and the Research → "Levels & sweeps" tab.
- Added the NO_TRADE reason `COST_TOO_HIGH` (cost/risk > 0.5).
- Fixed: the re-entry per-level limit never applied (wrong key).
- Research: no technique or selector beats NO_TRADE on the available data (`docs/research/levels-2026-10-24.md`).
