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

## Pass 2 (2026-10-24, atlas-full-1, unmerged, not pushed)

Done:
- (1) partial: `/api/quant/levels` now returns `overlays` (SMA50/200, trend band, Donchian, BOS/CHoCH structure events, gold-only session ranges, freshness label). The Levels & sweeps chart has toggles for them, freshness badges, and a Gold session ranges card. The gold 1m windows come only from ATLAS feed 1m. The API's 1m projection for GC is a labeled synthetic fixture and is never used for boxes.
- Gap fix: Asian ≤10% missing, early ≤5% missing, 08:00/08:20 strict. Coverage is reported per window and gaps are never filled. GC 2026-10-19..23: Asian coverage 0.980/0.994/0.963/0.989/0.991. Early coverage 1.0/0.961/1.0/1.0/0.978. 2026-10-18 (Sunday) is INSUFFICIENT.
- (7) partial: `x-correlation-id` middleware and JSON `atlas.request` logs. The ID is not yet propagated into control-plane or paper-execution records.
- (8) partial: CHANGELOG and the roadmap xlsx changelog row.

Checks: pytest 1526 passed / 9 skipped (with ATLAS_FEED_DB unset; with it set, `test_quote_route_stays_off_under_pytest...` fails by design of that guard). `tsc --noEmit` exit 0, `next build` exit 0, vertical-text 0 instances. Screenshots: /workspace/shots/full1/ui/levels-{1440,390}.png (no horizontal overflow).

Not done: (2) zone registry fields and the instrument contract spec; (3) ML registry merge, prediction contract, abstention statuses and drift; (4) partial fills, latency and intrabar replay; (5) E2E journey; (6) curtain-menu merge and asset-card redesign. No metric labels exist yet outside Levels.
Known defect: `asian_context.range_atr` in the evidence uses the 1m ATR, so the ratios (18–67) are not comparable to the 15m ATR.
