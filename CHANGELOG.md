
## atlas-full-1 (2026-10-24, unmerged)
- Added `features/price_action/library.py` (indicator + quant math library), `structure.py` (causal market-structure events), `gold_models.py` (gold-only Early Bird / range-bound / ORB alignment / Asian context).
- Added gap matrix, indicator catalog, checkpoint, `scripts/run_structure_evidence.py`, tests `tests/price_action/test_mandate_full1.py`.
- `gold_models.window_range` gap tolerance (Asian ≤10% missing 1m bars, early ≤5%, 08:00/08:20 boxes strict); every window reports `n/expected/coverage`. Gaps are never filled.
- `/api/quant/levels` now returns `overlays` (indicator series, structure events, gold-only session ranges from ATLAS feed 1m only, `freshness` label). Levels & sweeps chart gains SMA / trend band / Donchian / structure toggles, freshness badges and a Gold session ranges card.
- `atlas.ops.correlation`: `x-correlation-id` request/response header and JSON-line `atlas.request` logs.

## atlas-full-1 pass 3 (2026-10-24, unmerged, not pushed)
- `models/serving.py`: one serving path over the ml / quant / serving registries; statuses TRADE_CANDIDATE, LOW_CONFIDENCE, CONFLICTING_EVIDENCE, INSUFFICIENT_DATA, UNFAVORABLE_COSTS, NO_TRADE; PSI+ADWIN DriftGuard; `GET /api/ml/serving`. Only TRADE_CANDIDATE reaches the deterministic control plane.
- Correlation id (`ops.correlation.bind`) on control-plane decisions/intake reports, PaperConnector receipts, signal telemetry, autopilot audit decisions and paper exits.
- Fix: opportunity geometry is now directional (a long with stop above entry was accepted).
- Fix: gold `range_atr` uses the causal pre-Asian 15m ATR(14) (`atr_basis`); 1m basis rejected.
- `scripts/run_e2e_journey.py`: GC 15m replay → detection → logistic+Platt (research only) → serving → control plane → paper → exits → SVG chart, evidence in `/workspace/shots/full1/e2e/`.
- `feeds/contracts.py`: ContractSpec for GC/MGC/SI/ES on top of InstrumentMaster (expiry, roll before first notice for metals, hours, cost assumptions, `verified=False`). Control plane sizes futures by contracts × multiplier.
- Levels: confluence_ids, rejection/breakout/sweep/acceptance counts, last_event_ts, optional round-number levels.
- Replay: `latency_bars`, `limit_fill="trade_through"`, volume-capped partial fills (`fill_ratio`, weighted R); `scripts/run_replay_realism.py`.
- `GET /api/feeds/freshness` + shared `FreshBadge` / `DataFreshnessChip` in the header and curtain menu.
