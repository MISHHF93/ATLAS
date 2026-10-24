# Changelog

## 2026-10-24: branch `atlas-evo-5` (from main 771863a; not merged, not pushed)
- §22 macro data: `feeds/providers/fred_public.py` reads keyless FRED `fredgraph.csv` (DGS10, DGS2, VIXCLS, DTWEXBGS, CPIAUCNS, chosen because they are rarely or never revised). Every value gets a conservative availability date as `realtime_start`:
  - daily series: next business day + 1 day
  - H.10 dollar index: + 10 days
  - CPI: first day of M+2

  Values are stored through `FeedStore.ingest_observations` (`scripts/fetch_fred_public.py`).
- `ml/context.py`:
  - HTF features come from closed UTC-day and 4h buckets of the series itself: d1 returns, trend in ATR, daily ATR, position in the prior-day range, 4h return and trend, and risk relative to the daily ATR.
  - Macro features (10y level and 20d change, 2s10s, VIX level and z-score, 20d USD return, CPI YoY) are joined only from 00:00 UTC of the availability date. With no observations they are NaN, and the genome is gated as unavailable.
- Evolution adds the gene `context` (none|htf|macro|htf_macro) with 4 seeds. Old genomes default to `context=none`. `--universe extended` adds 1h bars for the same 5 symbols.
- `scripts/ml_diagnose.py` and `docs/ml/evo5-diagnosis.md`: why nothing beats baseline.
  - The primary setups lose before costs (gross −0.24 R), costs are about 0.48 R median, and the meta-label AUC is about 0.53.
  - The shuffled-label check shows no leakage.
  - Fixed the biased permutation importance from the scratch analysis (calibrated base vs raw permuted score).
- Evolution:
  - 44f40efd9e65 (default, 9,531 rows) and 30721a3ccb32 (extended, 15,157 rows): **no challenger beats baseline**.
  - On extended data, HTF context improves hgb fitness from −0.027 to −0.008, but EV stays negative.
  - Nothing promoted; execution_permission none. Chart markers now come from 30721a3ccb32.
- `ml/features.py`: `dt.dayofweek` → `dt.day_of_week` (pandas deprecation).

## 2026-10-24: branch `atlas-evo-4` (from main b299511; not merged, not pushed)
- Control plane reduce-only partial close: `close_position(position_id, exit_price, fraction=…)`. 0 < fraction ≤ 1 only (else `invalid_fraction_reduce_only`); books P&L on the closed slice, frees gross and correlated exposure, keeps the remainder open; audited `position_reduced` / `position_closed` with closed and remaining notional. No risk check changed.
- Setup autopilot: a volume-capped partial entry now cancels the unfilled remainder through that partial close at the booked entry price (zero P&L, audit `setup_autopilot.partial_fill`), so exits book the real filled quantity. The evo3 fill-ratio exit-price approximation is removed.
- `research/backtester.py` (`StrategyBacktester`) uses the same paper realism as replay by default (1-bar latency, trade-through entry/target limits, 10% participation, zero volume no fill, fill-weighted net P&L, `fill_ratio` on `TradeOutcome`); `realism=None` keeps the legacy model. `scripts/backtester_realism_compare.py` prints before/after.
- Fixed `strategies/snapback.py`: `SnapbackSetup` subclassed the frozen pydantic `Record`, so the detector raised on its first bar and the backtester/coordinator snapback path could never run.
- §6: `feeds/universe.py` FUTURES and `feeds/instruments.py` ES read tick/multiplier from `feeds/contracts.CONTRACT_TERMS` (the duplicates were there, not in `marketdata/futures.py`/`models/quant/multi.py`).
- Before/after on real feed bars (3,000 bars each, cost_bps 0): BTCUSDT 15m 8→8 trades, +35.2 bps expectancy both; ETHUSDT 15m 6→6, +30.8 both; ES 1m 20→19 trades (1 unfilled), net +1,161→+1,101 bps; GC 1m 9→9 (1 unfilled signal that legacy had expired). Samples are tiny and say nothing about edge; on these liquid markets realism removes little.
- ML not re-run: dataset labels come from PA replay, which did not change in this pass.

## 2026-10-24: branch `atlas-evo-3` (from main 62bf221; not merged, not pushed)
- §13 cumulative-loss cap for re-entry. `ReentryConfig` adds `max_loss_r_per_family_day`, `max_loss_r_per_day` and `max_consecutive_losses`. They load from the new tighten-only overlay `config/risk_overlays/reentry_tighten.yaml` (2.0 R, 3.0 R, 2) via `load_reentry_config`. A looser, null, unknown or non-positive overlay value is ignored and listed in `overlay_notes`. `config/founder/risk_policy.yaml` is unchanged.
  - Feedback: replay feeds each exit's after-cost, fill-weighted R to `PriceActionEngine.record_outcome` before the bar reaches the detectors (causal). The setup autopilot feeds realized paper exits to an OMS-level governor and refuses new proposals with the audited decision `reentry_loss_cap`. `risk_view` shows the governor state.
- §6 one contract-spec source. `feeds/contracts.py` is the source. `intel.data.SPEC` futures rows and `scripts/run_level_research.py` now derive from it. The new `risk.sizing.contracts_for_risk` sizes from it. Where two duplicates disagreed, the more conservative cost was kept: MGC $3.5 RT (was 2.5 in contracts), ES $30 (was 25), SI price-unit cost 0.025 (was 0.015 in intel). Every spec is still flagged `verified: false`.
- §25 paper realism by default. `PAPER_REALISM` / `paper_replay_config` (1-bar latency, trade-through limits, 10% participation; zero or unknown volume does not fill) is now used by the intel lab, `/api/intel` replays, the ML dataset and the setup autopilot. The autopilot sets the real order quantity per trade. A partial fill is booked as the exit price that gives fill_ratio × full P&L, because the control plane closes whole positions only (documented limitation).
  - `PaperBroker` gains opt-in `ExecRealism` (latency in price updates, trade-through, volume-capped partials with the remainder left working). The default is unchanged.
- API `/api/intel/contracts` and `/api/intel/reentry`. Risk → Track rules now shows "Re-entry loss caps" and "Contract specs" cards.
- ML labels changed (realism in the dataset), so evolution was re-run: run acfd9abb65cc, **no challenger beats baseline** (details in the checkpoint, pass 9). Nothing promoted; execution_permission none.

## 2026-10-24: branch `atlas-evo-2` (from main 727975f; not merged, not pushed)
- Chart opportunity markers: categories are now accurate per class.
  - Rule-only markers no longer say "rejected"; their risk status reads "gate abstained, no validated model (not a risk rejection)".
  - `/api/intel/markers` returns `classes` with count, `applicable` and a note per category. The legend shows "n/a" (disabled, with the reason on hover) for categories that cannot occur on that chart, e.g. ML take/skip where there are no out-of-sample predictions.
  - "Gate rejected (geometry/costs)" now states that its count is out of N rule candidates checked, and that the edge check needs a validated model.
  - Labels: ML take / ML skip (out-of-sample), Rule setup with no model verdict, Gate rejected (geometry/costs).
- New causal bar types `kagi_atr` and `pnf_atr` (3-box reversal, ATR box frozen per column) in `features/representations`. Only completed lines/columns are emitted. Prefix-invariance (no-lookahead) tests and fixed-size worked examples were added.
- Both are in the evolution `bar_type` gene and seeds, and in the chart bar-type switcher (Levels chart, desk chart).
- Evolution run 3bdaaf38ba24 (same data snapshot and seed as d6a35224ceef): **no challenger beats baseline**. Best kagi genome fitness -0.053, best P&F -0.065; both are below renko (-0.034) and time bars (-0.039). Nothing was promoted, and execution_permission stays none.
- Removed the dead pathname-to-workspace map in `InstitutionalWorkspacesView.tsx`. Legacy paths 308 before render. On canonical hub paths it overrode the tab's workspace view (e.g. `/settings` → rulebook, `/data?tab=reserve` → lakehouse).
- Gap matrix re-audited (pass 8).

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
