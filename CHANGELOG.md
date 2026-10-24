
## atlas-full-1 (2026-10-24, unmerged)
- Added `features/price_action/library.py` (indicator + quant math library), `structure.py` (causal market-structure events), `gold_models.py` (gold-only Early Bird / range-bound / ORB alignment / Asian context).
- Added gap matrix, indicator catalog, checkpoint, `scripts/run_structure_evidence.py`, tests `tests/price_action/test_mandate_full1.py`.
- `gold_models.window_range` gap tolerance (Asian ≤10% missing 1m bars, early ≤5%, 08:00/08:20 boxes strict); every window reports `n/expected/coverage`. Gaps are never filled.
- `/api/quant/levels` now returns `overlays` (indicator series, structure events, gold-only session ranges from ATLAS feed 1m only, `freshness` label). Levels & sweeps chart gains SMA / trend band / Donchian / structure toggles, freshness badges and a Gold session ranges card.
- `atlas.ops.correlation`: `x-correlation-id` request/response header and JSON-line `atlas.request` logs.
