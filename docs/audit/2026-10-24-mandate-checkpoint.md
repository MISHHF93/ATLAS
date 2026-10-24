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

## Pass 3 (2026-10-24, atlas-full-1, unmerged, not pushed)

Done: (3) unified serving path + 6 statuses + drift; (5) E2E replay journey with correlation ids end to end; (4) latency / trade-through / partial fills (worst-case intrabar was already in place: ambiguous bars resolve to stop); (2) contract specs + zone evidence fields + round-number levels; (6) partial: platform-wide freshness chip (header + curtain), shared FreshBadge. range_atr unit mismatch fixed (now 4.3–11.0).

Evidence (deterministic replay, atlas-feed GC 15m, 3825 bars 2026-08-26..10-23 UTC; not a profitability claim):
- Baseline: 126 candidates, 123 filled, 35 target / 88 stop, mean R +0.137. 1-bar latency: 103 filled, mean R −0.499. Trade-through limits: mean R +0.088. Both: −0.546. (`/workspace/shots/full1/replay_realism.json`)
- ML (logistic + Platt, chronological split): test n=29, Brier 0.219 vs base-rate 0.215 (skill −0.018), AUC 0.42. No skill; status research_only_not_promoted.
- E2E OOS segment: 21 LOW_CONFIDENCE, 2 UNFAVORABLE_COSTS, 6 TRADE_CANDIDATE → all 6 rejected by the control plane (stop_distance_too_tight + insufficient_remaining_room_for_one_lot: one GC contract ≈ $400k notional exceeds the cap). 0 paper receipts. Dev segment abstains with calibration_unsupported (leak guard). Correlation ids present on every record.

Not done: MA/VWAP zone types; curtain section restructuring / asset-card redesign; freshness labels inside every individual card (only header/curtain + Levels); SVG→PNG render of the journey chart (headless render timed out); holidays in contract expiry calc.

## Pass 4
- Control plane: lot-sized orders now report whole-contract `quantity` (0 on a zero-lot rejection; previously a fractional value derived from the 0.01 placeholder notional). Tests: `tests/test_control_futures_sizing.py` (GC/MGC/SI/ES whole contracts, notional = qty x entry x multiplier, 1 GC > open-track cap rejected, unknown symbol -> lot metadata unavailable).
- Levels: dynamic `ma<N>` (shared `indicators.EMA`) and `vwap` (shared `indicators.BarVWAP`, session reset, absent without volume) zone types; one live level per type, valid one bar; `priority_of()`. Off by default (`RegistryConfig.ma_periods=()`, `session_vwap=False`).
- `vertical-text.check.mjs`: pages and tabs read from `pagesMap.ts` (30 pages x 4 widths = 120 combos); load failures / near-empty pages are counted and exit 2. The earlier "0 page/width combos" line counted only failing combos and the run had no server on the default port, so it covered nothing. Rerun: 120/120 checked, 0 instances, 0 load failures.
- UI: curtain merged into 4 sections (Home & trading, Research & models, Money & compliance, Settings, help & tools incl. advanced); `Card fresh=` prop renders the shared freshness badge on Levels, Gold sessions, Candidates, Inspect, No-trade, Setup candidates, Zones and Paper replay cards; market AssetCard shows only symbol/name/price/change/quote status (fixture microstructure details removed).
- Research `scripts/run_mgc_sizing_eval.py` -> `shots/full1/e2e/mgc_sizing_eval.json`: MGC does not make the E2E candidates pass. All 6 have stops of 2.4-12.1 bps vs the 30 bps open-track minimum, and one MGC (~$41.2k-42.3k) already exceeds the $40k open-track position cap. GC and MGC: 0/6 authorized. No rule changed.
- Exchange holidays: no holiday/exchange-calendar library installed in the venv; not added. `last_trade_date` remains weekday-only.

## Pass 5 (2026-10-24, branch atlas-full-2 from 17ea2cc, unmerged, not pushed)
New package `atlas.intel` (EXECUTION_PERMISSION="none") + `/api/intel/*` router + UI hub `/research/lab` and Risk tabs `portfolio`, `tracks`.
- Research lab (`intel/lab.py`): variant replays on shared `ReplayEngine`, after costs; DSR/PBO via `ml.metrics`; seeded bootstrap CI of mean R; cost sensitivity at 0/1/2/3x; report_id = hash(data, code sha, settings); JSONL ledger + markdown report in `var/lab` (`ATLAS_LAB_DIR`). GC 15m (3,825 bars): sfp_only 123 trades, mean R 0.137, 95% CI -0.35..0.81, P(mean<=0)=0.34; cost 0x/1x/2x/3x = 0.22/0.14/0.05/-0.03; DSR 0.705, PBO 0.571. snapback_only and orb_only produced 0 trades on this run (not investigated). No edge is claimed.
- Regimes (`intel/regime.py`): causal EMA20/50 spread in ATR units x ATR percentile (200 bars, 60-bar warmup); test proves prefix invariance. Strategy x regime table flags n<20.
- Portfolio (`intel/portfolio.py`): exposure, daily-return correlation, historical VaR/CVaR per $10k, book VaR, historical + labelled hypothetical stress. The control engine's only open position is its seeded demo `pos-001` (`comp:btc-perp:v1`), which has no feed series, so the book reports `partial` with no VaR. The value is not estimated.
- Tracks (`control/tracks.py`): rulebook diff and probes on throwaway engines. A 28 bps SPY stop is authorized on competition and rejected on open_market (min stop 25 vs 30 bps). A 100 bps stop is authorized on both, with different sizes (83 vs 66 shares).
- Assistant (`intel/assistant.py`): reuses `ml.retrieval` BM25 over docs + lab reports; evidence IDs `EV-<sha10>`; extractive answers only; `no_evidence` when nothing matches; the LLM is never called (state `disabled_no_key` without a key).
- Memory (`intel/memory.py`): replay-trade memory, causal kNN analogues (only trades resolved before the query), attribution by detector/regime/direction/hour/outcome (each sums to total), read-only `ModelRegistry` governance summary. Overlaps `research/memory.py` (ledger CBR); consolidating them is a follow-up.
- Microstructure (`intel/microstructure.py`): tiers bars/l1/trades/l2. The feed has bars only, so the four bar-based estimates (Corwin-Schultz, Amihud, Parkinson, volume z) are computed and the l1/trades/l2 metrics show as `gated`.
- Four-Box (`intel/fourbox.py`): Opening=orb_retest, Breakout=dual_bollinger, Anchor=wick_reversal (zone counts reported; these emit zones, not candidates), Event disabled (no verified calendar). Metals use the `us_equity_rth` session preset as an approximation. BTC has no Opening (24/7). `four_box` strategy spec stays `reserved`.
- Holidays: `exchange_calendars` 4.13.2 (COMEX/CMES) in `feeds/contracts.py`; weekday fallback; `/api/intel/holidays`. Contract specs still `verified=False`.
- Freshness: market-data cards use shared `quant.freshness`. Lab runs are labelled `historical`. Track rules are configuration, so they carry no market freshness chip. Note: the portfolio's daily-bar freshness shows `live · 28 h old` on a Saturday because the shared rule treats a daily bar within its bucket as live. This was left unchanged.
- Checks: pytest 1570 passed / 9 skipped (ATLAS_FEED_DB unset); tsc clean; next build ok; pages test 4/4; vertical-text 152/152 combos (38 pages x 4 widths), 0 instances, 0 load failures, after fixing a wrapped freshness chip at 390px (`.ux-chip` nowrap); screenshots in `/workspace/shots/full2/` (16 page shots + 2 curtain shots, no page errors).

## Pass 6 / evo1 (2026-10-24, branch atlas-evo-1 from 97bf58f, unmerged, not pushed)
- Evolution run d6a35224ceef:
  - Universe: BTCUSDT, ETHUSDT, SPY, QQQ and IWM on 15m. 11,249 rows, 24 genomes, 3 generations, about 69 s.
  - Decision: **no_challenger_beats_baseline**. Taking every opportunity gives EV -0.70 R.
  - Best genome: hgb + renko_atr, fitness -0.034, EV -0.0109 R, BSS +0.0069.
  - Best time-bar genome: xgb, fitness -0.0387.
- Markers:
  - GC 15m: 126 rule_only markers, all rejected with no_validated_model.
  - BTCUSDT 15m: 586 ml_skip, 1 ml_suggested and 13 rule_only. These come from a genome that does not beat baseline, and the UI says so.
- Zero trades for snapback_only and orb_only: this is timeframe_mismatch on GC 15m, not a detector bug. On GC 1m, snapback had 3 trades and ORB had 4, which is too few to say anything.
- Checks:
  - pytest with ATLAS_FEED_DB unset: 1580 passed, 9 skipped.
  - tsc, next build and pages test (4/4) pass.
  - Vertical-text check: 156/156 page and width combinations, 0 instances.
  - Screenshots are in `/workspace/shots/evo1/`.
- Pending:
  - Kagi and P&F bars are not built (they were optional).
  - Tick bars need trade prints.
  - The desk TradingView widget can't take ATLAS markers, so the markers are on an ATLAS feed chart under it.
  - The legacy LiveChartEngine is unchanged.

## Pass 8 / evo2 (2026-10-24, branch atlas-evo-2 from 727975f, unmerged, not pushed)
- Evolution run 3bdaaf38ba24. Same data hash as d6a35224ceef (11,249 rows; BTCUSDT, ETHUSDT, SPY, QQQ, IWM 15m); 26 genomes, 3 generations, seed 11.
  - Decision: **no_challenger_beats_baseline**. Take-all EV -0.70 R. Best overall is unchanged: hgb + renko_atr, fitness -0.034, EV -0.0109 R, BSS +0.0069.
  - Kagi: best hgb/no_setup/vol_conditioned, fitness -0.053, EV -0.0133 R, BSS -0.010.
  - P&F: hgb/full, fitness -0.065, EV -0.0166 R, BSS +0.002.
  - No profitability claim. Nothing promoted; execution_permission none.
- Markers after refresh:
  - GC 15m: 126 rule setups (gate abstained, no validated model), gate-rejected 0 of 126 checked; ML take/skip n/a.
  - BTCUSDT 15m: 1 ML take, 586 ML skip, 13 rule setups, 0 gate-rejected.
- Checks: pytest 1585 passed / 9 skipped (ATLAS_FEED_DB unset, 2 threads); tsc clean; next build clean; pages test 5/5; prod server: 36 canonical URLs 200, 43 redirects 308; vertical-text 144/144, 0 instances. Screenshots in `/workspace/shots/evo2/`.

## Pass 9 / evo3 (2026-10-24, branch atlas-evo-3 from 62bf221, unmerged, not pushed)
- Done: §13 tighten-only re-entry loss caps with causal outcome feedback (replay + autopilot OMS); §6 one contract-spec source; §25 paper realism default in every PA replay caller, plus opt-in PaperBroker realism. See CHANGELOG.
- Evolution re-run because labels changed: run acfd9abb65cc (same feed DB, 3 generations, seed 11), 9,531 rows (was 11,249: realism leaves unfilled setups out).
  - Decision: **no_challenger_beats_baseline**. Take-all EV -0.92 R (was -0.70 R under idealized fills).
  - Best: lgbm/no_setup/time, fitness -0.021, EV +0.0001 R (effectively zero), BSS -0.011. Renko best now -0.035 (was -0.034).
  - Not comparable one-to-one with 3bdaaf38ba24 because fills and rows differ. No profitability claim; nothing promoted; execution_permission none.
- Checks: pytest (ATLAS_FEED_DB unset, 2 threads) 1596 passed / 9 skipped; tsc clean; next build clean; pages test 5/5; vertical-text 144/144, 0 instances; prod server curl 200 for /control?tab=tracks, /api/intel/reentry and /api/intel/contracts. Screenshots in `/workspace/shots/evo3/`.
- Open: control-plane partial close; legacy multipliers in `marketdata/futures.py` and `models/quant/multi.py`; §22 macro data; contract specs remain unverified.

## Pass 10 / evo4 (2026-10-24, branch atlas-evo-4 from b299511, unmerged, not pushed)
- Done: control-plane reduce-only partial close + real partial-fill booking in the autopilot; backtester paper realism by default; snapback detector made runnable; last contract-term duplicates removed (universe/instruments). See CHANGELOG.
- ML: not re-run; replay labels unchanged. Latest run remains acfd9abb65cc (no challenger beats baseline; execution_permission none).
- Verify: pytest 1605 passed / 9 skipped (ATLAS_FEED_DB unset, 2 threads); tsc ok; next build ok; route tests 5/5; local prod curl 200 + /api/health ok; screenshots /workspace/shots/evo4/.
- Open: §22 macro data (no observations in the feed).

## Pass 11 / evo5 (2026-10-24, branch atlas-evo-5 from 771863a, unmerged, not pushed)
- Done:
  - §22 macro from keyless FRED with release-lag availability dates, stored in feed observations (local feed DB: 44,659 rows).
  - HTF and macro `context` gene, extended 15m+1h universe option, ML diagnosis script and doc. See CHANGELOG.
- Diagnosis (default data, 9,531 rows):
  - Base rate 0.249; net −0.89 R, gross −0.24 R; median cost 0.48 R.
  - lgbm AUC 0.526, BSS −0.003. Shuffled-label AUC 0.500 (no leakage).
  - Root cause is the negative gross edge of the primary setups plus costs, not the model.
- Evolution:
  - 44f40efd9e65 (default, 3 generations, seed 11): best hgb/no_signed/vol_conditioned/heikin_ashi, fitness −0.027, EV −0.0003, BSS +0.003. Context genomes: htf −0.036, macro −0.051, htf_macro −0.050.
  - 30721a3ccb32 (extended, 15,157 rows, take-all −0.78 R): best hgb/heikin_ashi, fitness −0.004, EV −0.002, BSS +0.009. htf beats none on time bars (−0.008 vs −0.027).
  - Decision for both runs: **no_challenger_beats_baseline**. Nothing promoted; execution_permission none.
- Markers: BTCUSDT 15m shows 389 ML skips and 11 rule-only setups, from run 30721a3ccb32.
- Verify:
  - pytest 1611 passed / 9 skipped (ATLAS_FEED_DB unset, 2 threads)
  - tsc ok; next build ok; route tests 5/5
  - vertical-text 0 instances
  - local prod curl 200
  - screenshots in /workspace/shots/evo5/
- Open: ALFRED vintages (needs a FRED key); primary-strategy changes (wider stops / higher timeframe, retire 15m orb_retest) need a founder decision.
