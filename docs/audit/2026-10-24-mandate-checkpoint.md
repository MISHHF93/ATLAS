# Mandate checkpoint — 2026-10-24 (branch atlas-full-1, unmerged, not pushed)

## Repo state
Worktree `/workspace/atlas-full1`, branch `atlas-full-1` from main 87d24a0. var/ not committed. risk_policy.yaml untouched.

## Done
- Gap matrix: `docs/audit/2026-10-24-mandate-gap-matrix.md`.
- `library.py` (indicator + quant math), `structure.py` (causal structure events), `gold_models.py` (gold-only session models), indicator catalog, tests (14 new).
- Real-data run: `scripts/run_structure_evidence.py` → `/workspace/shots/full1/structure_evidence.json` (GC/ES 3,825 15m bars, BTC 70,105; GC 1m 6,843 bars, 5 days with 08:20–08:50 box built; Asian window never fully tiled by 1m bars → INSUFFICIENT_DATA).

## Tests
`PYTHONPATH=src OMP_NUM_THREADS=2 pytest -q` → 1523 passed, 9 skipped, 0 failed (263 s).
Frontend: no frontend changes, so tsc / next build / vertical-text check were not run on this branch.

## Pending (by priority)
1. Expose structure/gold-session/indicator outputs via `/api/quant/levels` + chart overlays and toggles in the Levels & sweeps tab; screenshots 1440/390.
2. Zone registry: add confluence_ids, breakout/rejection counts, provenance, plus MA/VWAP/psychological zone types, in `levels.py`.
3. ContractSpec contract (multiplier, tick, expiry/roll, hours, costs) consolidating `marketdata/futures.py` + `ml/costs.py`.
4. Reentry: verify/add cumulative-loss cap + no-size-up assertion.
5. Reconcile `ml/` and `models/quant` ML stacks (prediction contract + abstention set).
6. PA replay: partial fills/latency; snapback trailing/partial/time exits.
7. E2E journey demo (data→…→paper→outcome→chart) with evidence; correlation IDs; capability-tier registry.
8. Not possible without data: L2 microstructure, Event Box, macro §22, 08:20 box history beyond ~5 days.
