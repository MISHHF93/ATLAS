
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

## atlas-full-1 pass 4 (2026-10-24, unmerged, not pushed)
- Control plane: lot-sized orders now report whole-contract `quantity` (0 on a zero-lot rejection; previously a fractional value derived from the 0.01 placeholder notional). Tests: `tests/test_control_futures_sizing.py` (GC/MGC/SI/ES whole contracts, notional = qty x entry x multiplier, 1 GC > open-track cap rejected, unknown symbol -> lot metadata unavailable).
- Levels: dynamic `ma<N>` (shared `indicators.EMA`) and `vwap` (shared `indicators.BarVWAP`, session reset, absent without volume) zone types; one live level per type, valid one bar; `priority_of()`. Off by default (`RegistryConfig.ma_periods=()`, `session_vwap=False`).
- `vertical-text.check.mjs`: pages and tabs read from `pagesMap.ts` (30 pages x 4 widths = 120 combos); load failures / near-empty pages are counted and exit 2. The earlier "0 page/width combos" line counted only failing combos and the run had no server on the default port, so it covered nothing. Rerun: 120/120 checked, 0 instances, 0 load failures.
- UI: curtain merged into 4 sections (Home & trading, Research & models, Money & compliance, Settings, help & tools incl. advanced); `Card fresh=` prop renders the shared freshness badge on Levels, Gold sessions, Candidates, Inspect, No-trade, Setup candidates, Zones and Paper replay cards; market AssetCard shows only symbol/name/price/change/quote status (fixture microstructure details removed).
- Research `scripts/run_mgc_sizing_eval.py` -> `shots/full1/e2e/mgc_sizing_eval.json`: MGC does not make the E2E candidates pass. All 6 have stops of 2.4-12.1 bps vs the 30 bps open-track minimum, and one MGC (~$41.2k-42.3k) already exceeds the $40k open-track position cap. GC and MGC: 0/6 authorized. No rule changed.
- Exchange holidays: no holiday/exchange-calendar library installed in the venv; not added. `last_trade_date` remains weekday-only.

## atlas-full-2 pass 5 (2026-10-24, branch from 17ea2cc, unmerged, not pushed)
- `atlas.intel`: research lab (DSR, PBO, bootstrap, cost sensitivity, reproducible report IDs), causal regimes + strategy-by-regime, portfolio exposure/correlation/VaR/CVaR/stress, track rulebook diff + enforcement probes, grounded evidence-ID assistant (LLM never used), market memory/attribution/governance view, microstructure tier gating, Four-Box scan. `/api/intel/*`.
- UI: `/research/lab` hub (6 tabs) and Risk tabs Portfolio risk / Track rules, with freshness chips.
- Exchange holidays via `exchange_calendars` (COMEX/CMES) for futures last-trade/roll dates.

## atlas-ext-1 (2026-10-24, unmerged, not pushed)
- Seven-repo gap audit: `docs/audit/2026-10-24-seven-repo-gap.md`.
- `atlas.ext`: Black-Scholes greeks/IV, parametric/historical/component VaR+ES, DCF (FCFF/FCFE), SEC EDGAR point-in-time fundamentals, VWAP/volume profile/S-R/scan, Pine v5 export, conviction dossier, rule-based investor personas, a deterministic analyst-debate-trader-risk-PM pipeline (never submits), an Alpaca PAPER broker (live refused, control plane first), alerts (off by default), and a read-only MCP tool server (`scripts/atlas_mcp_stdio.py`). `/api/ext/*`.
- Control plane: `preview_order` (no booking) shares `_evaluate_request` with `submit_order`. Rules are unchanged.
- UI tabs: Research Lab gets Valuation / Dossier & agents / Options; Research gets Scan & Pine; Settings gets Broker & alerts.
- Blocked: live option chains, news/sentiment, maritime. Deferred to evo-5: yield curve/macro.

## atlas-unify-1 (2026-10-24)
- AI consolidated into one node (`atlas.ai`, `/api/ai/*`); dead code and unused deps removed. Details in docs/CHANGELOG.md and docs/audit/2026-10-24-repo-streamline.md.
