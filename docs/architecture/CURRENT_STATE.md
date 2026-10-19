# Current state

Verified in `C:\Users\borah\ATLAS` on 2026-10-19. The user supplied this path.
It contains the ATLAS scaffold, universal research foundation, causal regime
classification, deterministic control-plane rule scaffolding, read-only MCP data
contracts, frozen dataset verification, and baseline-versus-tree walk-forward
evaluation. It is not a live trading engine. No live execution behavior is
inferred from the project name.

## Running source

- FastAPI: health, fixture candle, research capability and synthetic research demo GET routes; trading disabled.
- Candle validation: finite nonnegative decimals, OHLC ranges, aware timestamps.
- Next.js: responsive research terminal with fixture plot/table, causal regime overlay strip, data quality/freshness gate table, deterministic control-plane rule remaining-room bars and KPIs, baseline-versus-tree disagreement & calibration panel, purged walk-forward study viewer (separate Competition vs Open-Market tabs), read-only MCP surface inventory, ISO governance alignment panel, and role-based view switcher (`Founder / Admin`, `Quant Researcher`, `Risk & Ops Monitor`).
- Gemini: existing paid-tier, secret-screened research provider and CLI. Mocked tests.
- `src/atlas/models/schemas.py`: frozen typed instrument, horizon, data provenance (`DataProvenance`, `MarketDataRequest`, `MarketDataBatch`), forecast, training, model, usage and eligibility contracts.
- `providers.py` / `registry.py`: capability-specific protocols (including `ReadOnlyDataProvider` under `Capability.DATA_SOURCE`), discovery, immutable metadata/model revisions and in-memory and durable SQLite research-alias rollback.
- `model_store.py`: durable local SQLite model revisions and alias audit history.
- `runtime.py`: async deadline, bounded retry/backoff, local request/token budgets, circuit breaker and per-attempt cost/latency records.
- `adapters.py`: offline last-value/zero-return baseline and bridge to existing Gemini research. The bridge does not add training or tools.
- `calendars.py`: `SessionSchedule` plus authoritative `MarketCalendar` supporting traditional exchange sessions (opening/closing auctions, holidays, early closes, maintenance windows) and 24/7 crypto calendars (funding windows, maintenance windows) with `construct_authoritative_targets`.
- `regimes.py`: deterministic, causal, point-in-time regime detector (`classify_regime`, `RegimeConfig`, `RegimeState`, `ScheduledMacroEvent`) across volatility, trend, liquidity, session, and macro-event dimensions with explicit `unknown` preservation.
- `challengers.py`: deterministic `LocalTreeChallengerProvider` (`boosted_stump_v1`) and purged chronological walk-forward comparison (`run_baseline_vs_tree_study`, `WalkForwardStudyResult`, `OutcomeFeedbackRecord`) against naive and no-trade baselines without automatic promotion or in-place weight mutation.
- `src/atlas/control/rules.py`: deterministic control-plane rulebook (`TradingRuleBook`, `AccountRiskSnapshot`, `ProposedTradeCheck`, `evaluate_trading_rules`, `RemainingRoomReport`) covering per-trade fractional risk (0.5–1% equity) with ATR/structure stops, daily loss circuit breaker, static/trailing drawdown, position/notional/leverage/correlation/sector caps, data quality/freshness/license gates, session/funding/time-based exit rules, kill switch / auto-flatten, and competition consistency & minimum trading days. Unconfigured fields default to deny; structurally isolated from `atlas.ai`.
- `src/atlas/marketdata/`: read-only MCP adapter contract (`MCPDataSourceAdapter`) with explicit tool allowlists (`alpha_vantage_mcp`, `financial_datasets_mcp`, `fin_data_mcp`), write/execution tool rejection, `irohan0/quant-mcp` mutating server block, FRED training/archival prohibition, deterministic `validate_market_data_batch` (`DataQualityReport`), SHA-256 verified frozen benchmark datasets (`build_frozen_benchmark_dataset`), and whale/microstructure covariate normalization (`normalize_microstructure_covariates`).
- `continuous.py`: deterministic 24/7 research tick runner (`ContinuousResearchRunner`) that halts and marks a scope `unavailable_halted` on provider/quality/calendar/hash anomalies without silent fallback.
- `orchestrator.py`: scope/license/quality/freshness checks, forecast identity validation, optional held-out calibration, disagreement and research candidates.
- `evaluation.py`: predictive/return/calibration/cost/drawdown/tail metrics, exploratory block bootstrap, segmented evaluation, multi-horizon lead-time & joint interval coverage scoring (`score_multi_output_forecasts`), hierarchical coherence verification (`verify_hierarchical_coherence`), and operational summaries.
- `experiments.py` / `training.py`: SQLite experiment history, reproducibility manifests and separate submission coordinator with unknown-outcome recording.

Research signals, model records, regime states, data batches, walk-forward studies,
and rule evaluation reports always have `execution_permission: none`.
No ensemble combiner is enabled. No API route submits/cancels/modifies orders.

## Not installed or connected

New cloud adapters, cloud jobs, external identity provider, live venue feeds,
networked MCP server processes, live execution engine, whale collectors, external
C/GPU tree/neural libraries, foundation weights, durable shared cloud model registry,
production deployer, wallets, billing and customer funds remain absent.
SQLite is local research bookkeeping only.

## Evidence and next work

- [Architecture and implementation map](UNIVERSAL_AI_ECOSYSTEM.md)
- [Official-source AI ecosystem review](../research/AI_ECOSYSTEM.md)
- [MCP and read-only data review](../research/MCP_DATA_INTEGRATION.md)
- [Research Operating Contract](RESEARCH_OPERATING_CONTRACT.md)
- [ISO, NIST AI RMF, and IOSCO Governance Alignment](ISO_GOVERNANCE_ALIGNMENT.md)
- [Backlog](../backlog/AGILE_BACKLOG.md)

## Final verification — regime, control rules, MCP contracts & walk-forward increment

On 2026-10-19: **76 tests passed** (up from 68 in the foundation pass and 65 prior to session-calendar tests) with
`python -m pytest -q -p no:cacheprovider --basetemp <unique workspace test directory>`.
`python -m atlas.models.demo` completed successfully using synthetic frozen data,
and `npm run typecheck` + `npm run build` in `frontend/` passed with zero errors.
