# Changelog

## 2026-10-24: branch `atlas-sfp-1` (not merged)
- Added a price-level suite: CME/COMEX calendar, liquidity level registry, shared level interaction engine, SFP, gold opening box ORB and snapback (GC/MGC only), HTF bias, re-entry governor, unified candidate contracts with resolve.
- Added a strategy registry with per-technique toggles (`/api/quant/strategies`). New techniques default to off.
- Added a strategy selector (`ml/selector.py`): context features plus per-family calibrated meta-labels, purged walk-forward, and baselines. Added xgb/lgbm challengers.
- Added `/api/quant/levels` and the Research → "Levels & sweeps" tab.
- Added the NO_TRADE reason `COST_TOO_HIGH` (cost/risk > 0.5).
- Fixed: the re-entry per-level limit never applied (wrong key).
- Research: no technique or selector beats NO_TRADE on the available data (`docs/research/levels-2026-10-24.md`).
