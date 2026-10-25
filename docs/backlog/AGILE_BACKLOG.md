# ATLAS backlog

The 2026-10-19 universal AI directive and 2026-10-21 Master System Objectives authorize isolated research infrastructure and deterministic control-plane gating. Research runs continuously and supports separate prop-competition (`competition`) and open-market (`open_market`) evaluation tracks; all AI, ML, MCP, and streaming outputs carry `execution_permission: "none"`, and only `ActionableControlPlaneEngine` sizes, gates, and brackets orders.

## Complete: initial scaffold and robustness

Gemini research interface and mocked tests; paid-tier/context checks; read-only
fixture API; decimal/timestamp validation and response/error handling; responsive
research terminal with baseline discovery, synthetic approval demonstration and
integration readiness; read-only capability and demo routes.

## Complete: universal research foundation

Official-source ecosystem review; separate provider protocols and discovery;
typed market/horizon/data/model contracts; bounded runtime controls; immutable
research metadata and alias rollback; baseline forecasting; scoped orchestration;
held-out probability calibration; evaluation helpers; reproducible manifests and
local experiment history. See the [implementation map](../architecture/UNIVERSAL_AI_ECOSYSTEM.md).

## Complete: regime awareness, deterministic control rules, MCP contracts & walk-forward baseline-vs-tree study

1. Separate competition (`comp:btc-perp:v1`) and open-market (`open:spy-etf:v1`)
   frozen point-in-time dataset bundles with SHA-256 content verification
   (`src/atlas/marketdata/frozen.py`).
2. Read-only data provider contract (`Capability.DATA_SOURCE`, `ReadOnlyDataProvider`),
   allowlisted MCP adapter (`MCPDataSourceAdapter` for `alpha_vantage_mcp`,
   `financial_datasets_mcp`, and `fin_data_mcp`), mutating server rejection
   (`irohan0/quant-mcp`), FRED training prohibition, and deterministic
   `DataQualityReport` (`src/atlas/marketdata/quality.py`).
3. Authoritative `MarketCalendar` (`src/atlas/ai/models/calendars.py`) for traditional
   exchange sessions (auctions, holidays, early closes, maintenance) and 24/7 crypto
   calendars (funding windows, maintenance), plus causal regime classification
   (`src/atlas/ai/models/regimes.py`).
4. Deterministic control-plane rulebook and remaining-room engine
   (`src/atlas/control/rules.py`) with default-deny on unconfigured fields and
   strict isolation from LLMs.
5. Deterministic local tree challenger (`LocalTreeChallengerProvider`) and purged
   walk-forward evaluation (`run_baseline_vs_tree_study`) with per-regime slicing
   and non-promoting `OutcomeFeedbackRecord`.
6. ISO/IEC 42001, 23894, 27001, 22301, 31000, 9001, NIST AI RMF, and IOSCO
   governance alignment (`docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md`).

## Complete: Dual-Track Prop Trading & U.S. Stock Desk, Whale Order Flow ML (`WF-01..08`), Prop B2B SaaS (`SAAS-01..12`) & A–Z Master Roadmap (2026-10-20)

1. Stateful `ActionableControlPlaneEngine` (`src/atlas/control/engine.py`) for deterministic pre-trade order authorization, kill-switch override, auto-flatten, and human-gated challenger promotion/rollback.
2. Dual-Track Prop Trading & Stock Desk specialization across **Open-Market U.S. Stocks & ETFs (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`)** and **Prop Competition Challenges (`BTC-USD`, `ETH-USD`, `SOL-USD`)**.
3. Complete implementation of all 9 sheets of `ATLAS Platform Master Roadmap & Technical Specifications (A-Z)` (`src/atlas/whale_saas_az.py`, `src/atlas/proctoring_and_features100.py`, `src/atlas/lifecycle.py`).

## Complete: Module 02 Real-Time Streaming Engine, Autonomous Whale Policy Intake, 4-Role Client RBAC, `QM-01..08` Measurements & Backlog Verification (`TODO-01..07`) (2026-10-21)

1. **Module 02 Real-Time Market Composition & Streaming Engine (`src/atlas/marketdata/live_stream.py` & `src/atlas/api/ws.py`)**:
   - 10,000-slot lock-free `OrderBookRingBuffer` (`collections.deque(maxlen=10000)`) with causal `exchange_timestamp <= system_receipt_timestamp <= as_of` verification.
   - Streaming Rolling VPIN, Top-5 L2 OFI (`ofi` and `ofi_z`), Kyle's $\lambda$, and 500ms `competition` staleness circuit breaker over `/ws/market-stream`.
2. **Custom Microstructure & Whale Policy Model (`src/atlas/ai/models/whale_policy.py`) & Bracket Order Bridge (`src/atlas/control/engine.py`)**:
   - Triple-Barrier labeling + Purged/Embargoed Walk-Forward CV outputting air-gapped `StrategySignal` intents (`execution_permission == "none"`).
   - `ActionableControlPlaneEngine.submit_whale_signal()` enforcing 0.50%–0.75% equity risk sizing, Remaining-Room HUD cushions, mandatory ATR stops, 1.5x VPIN stop widening (`VPIN > 0.45`), and toxicity quote pause (`VPIN > 0.70`).
3. **4-Role Client Segment Taxonomy (`src/atlas/api/rbac.py` & `frontend/src/context/RoleContext.tsx`)**:
   - Implemented `prop_firm_admin`, `quant_researcher`, `funded_trader`, and `compliance_auditor` across backend and 41 frontend routes.
4. **Canonical Institutional Quantitative Measurements (`QM-01..QM-08`) & Visual Automation Scanner (`AUTO-01..AUTO-10`)**:
   - Implemented `compute_institutional_quantitative_measurements()` in `src/atlas/features/microstructure.py` and `/api/automation/visual-scan` in `src/atlas/api/app.py`.
5. **Engineering Backlog Milestones (`TODO-01..TODO-07` in `src/atlas/backlog_tracker.py`)**:
   - Preregistered microstructure feature ablations (`ABL-01..ABL-04`) and multi-holdout validation (`comp:btc-perp:v1`, `comp:eth-perp:4h:v1`, `open:nvda-eq:1h:v1`).
   - Native async Gemini token/cost/latency metering and xAI ZDR privacy contract gate.
   - Cloud training job reconciler with budget/wall-clock caps and SHA-256 checkpointing.
   - Apache-2.0 foundation model gate (`Chronos-2` allowed; `TimesFM 3.0` and `Moirai 2.0` blocked) and costed multi-horizon ensemble weight gate.

## Live integration track: external legal & venue audit gates

Public identity, external customer account linking, live broker/exchange capital routing, and regulated billing retain their external legal counsel, partner underwriting, and venue sign-off gates per `docs/ATLAS_MASTER_SPEC.md`. Customer custody, deposit addresses, and withdrawals remain permanently rejected by architecture.
