# Master mission 2026-10-24: price levels, SFP, gold slice, strategy selector

Branch `atlas-sfp-1` (base `main` 69e2baf). Research and paper trading only.
- Not merged and not pushed.
- `var/` is never committed.

## Binding rules
- ML and LLM outputs carry `execution_permission: none`. `ActionableControlPlaneEngine` alone authorizes, rejects or sizes orders.
- Holds are capped at 1 day.
- Every capability has a math definition, tests, live/replay parity and stated limitations.
- TradingView is used for rendering only, never as a data source.
- Gold rules apply only to GC/MGC.
- No fabricated evidence.

## First response (10 items)
1. **Scope understood.** Generic level engine shared by SFP, snapback and ORB; gold slice; unified candidates; ML comparison; strategy registry and selector; UI tab; docs.
2. **Audit.** See `docs/audit/2026-10-24-repo-audit.md` for what existed, what was missing and the test baseline.
3. **Data reality.** Futures and equities have ~8 weeks of 15m bars. 1m covers only ~5 days, and there is no 5m. No order book and no economic calendar.
4. **Discrepancy recorded.** The transcript says both "8:20–8:50" and "8:30" for the gold box. Both are configured. The 08:20 box needs ≤10-minute bars, so on 15m data it returns INSUFFICIENT_DATA and is never approximated.
5. **Shared contracts.** Bar → PriceLevel → LevelEvent → Candidate → UnifiedCandidate → resolve() (dedupe, conflict, abstain).
6. **Causality.** Each level carries `available_ts`. Daily bars count only after they close. Swings are confirmed k bars later. Live `update()` and replay `run_batch()` produce identical candidates (tested).
7. **Mutual exclusion.** Continuation and reversal on the same evidence both become NO_TRADE(CONFLICTING_CANDIDATES).
8. **Selector.** Strategies are toggled in the registry. Context plus per-family calibrated meta-labels give EV-ranked picks or NO_TRADE. Validated with purged walk-forward against simple baselines.
9. **Honest result.** No technique or selector beats NO_TRADE on the available data (`docs/research/levels-2026-10-24.md`). New techniques ship disabled.
10. **Blockers.** The 08:20 box needs 1m/5m history; four-box levels have no definition; order flow and the economic calendar are missing; the COMEX maintenance break is not modelled.

## Deliverable map
| Item | Location |
|---|---|
| Calendar | `src/atlas/features/price_action/calendar.py` |
| Contracts | `contracts.py` |
| Levels and interaction | `levels.py` |
| HTF | `htf.py` |
| Re-entry | `reentry.py` |
| Suite (SFP and gold) | `suite.py` |
| Registry | `strategies.py` |
| Selector | `src/atlas/ml/selector.py` |
| xgb/lgbm challengers | `ml/train.py` |
| API | `src/atlas/api/quant.py`: `/levels`, `/strategies` |
| UI | `frontend/src/components/market/LevelsView.tsx` (Research → Levels & sweeps) |
| Research | `scripts/run_level_research.py`, `docs/research/levels-2026-10-24.{md,json}` |
| Plan | `docs/spec/implementation-plan-13-phases.md` |
| Catalogs | `docs/strategies/strategy-catalog.md`, `docs/strategies/indicator-catalog.md`, `docs/strategies/sfp.md` |
| Tests | `tests/test_level_suite.py` (+ earlier price-action tests) |
