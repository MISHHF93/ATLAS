# ATLAS — Institutional Proprietary (Prop) Trading & Stock Quant Platform

ATLAS (**Autonomous Trading, Liquidity, Allocation & Strategy Intelligence**) is a founder-owned **Proprietary (Prop) Trading, U.S. Stock Trading, and Multi-Model Quantitative Research Platform** engineered around a strict architectural separation between **AI/Quantitative Research (`execution_permission: none`)** and a **Deterministic Control Plane (`ActionableControlPlaneEngine`)**.

ATLAS is specialized to operate seamlessly across **two distinct, synchronized trading tracks**:
1. **🏛️ Open-Market Stock & ETF Trading (`open_market` track)** — Trading U.S. Equities and Benchmark ETFs on **NYSE Arca & Nasdaq (`XNYS` / `XNAS`)** including **`SPY`**, **`NVDA`**, **`AAPL`**, **`MSFT`**, **`QQQ`**, and **`TSLA`** with regular-session calendars (`09:30–16:00 ET`), **SEC EDGAR Point-in-Time XBRL fundamentals** (`acceptance_time <= as_of`), **Databento / Polygon.io** SIP stock feeds, and **Alpaca / Interactive Brokers** execution routing.
2. **🏆 Prop Trading Competitions & Funded Evaluations (`competition` track)** — Participating in proprietary trading firm challenges, funded account evaluations, and 24/7 liquid derivative competitions (**`BTC-USD`**, **`ETH-USD`**, **`SOL-USD`**, and cross-asset prop books) governed by hard deterministic prop-firm rulebooks (**4.0% Daily Loss Circuit Breaker**, **8.0% Max Trailing Drawdown Floor**, **$\le 35\%$ Single-Day Profit Consistency Gate**, **$\ge 5$ Minimum Trading Days**, **0.50%–0.75% Per-Trade Risk Cap**, and **Mandatory ATR/Structure Stop-Loss Distance**).

The workspace is `C:\Users\borah\ATLAS`. The founder retains 100% ownership of source code, strategy logic, model artifacts, and signing keys; an infrastructure operator receives zero order discretion or ownership transfer.


> **Status correction (2026-10-23, branch `atlas-fix-1`).** The platform map below describes the original
> workbench catalogue. The UI now uses six sections (Home / Trade / Money / Research / Compliance / Settings);
> the old URLs still resolve by redirect (see `docs/reshape-decisions.md`). Items that are *not* implemented
> despite older wording: the visual automation scanner (`/api/automation/visual-scan`) and the
> "perfect-trader" model endpoints are **retired and answer 410 Gone**; live trading, live money movement and
> customer custody are **disabled** (paper/simulation only); A–Z "Implemented" labels mean code exists with
> tests, not production readiness. Full findings: `docs/broken-code-audit.md`.

---

## Complete Platform Map (16 Domain Workbenches & 19 Live Routes)

The terminal features an **Icon-Driven Domain Sidebar** (zero wizard/step numbering), a **Live Multi-Asset Ticker Tape** across the top (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`, `BTC-USD`, `ETH-USD`, `SOL-USD`), and a **Persistent Dockable Right-Hand Trading, L2 Orderbook DOM Ladder & Prop Risk Dock** alongside every workbench:

| Domain Workbench | Route(s) | Backend API Endpoint(s) | Institutional Capability |
| :--- | :--- | :--- | :--- |
| **Command Center** | `/` | `/api/platform/snapshot`, `/api/control/state` | Unified Bento Command Workbench with **Topbar Dual-Track Switcher (`Open-Market Stocks` ↔ `Prop Competition`)**, **1-Click Stock & Prop Ticker Strip**, **Prop Evaluation Scorecard**, Dual-Mode Live Chart, and Pre-Trade Risk-Checked Order Desk. |
| **Whale ML, SaaS & A–Z Roadmap** | `/roadmap` | `GET /api/master-roadmap`, `POST /api/master-roadmap/evaluate-whale`, `POST /api/master-roadmap/saas-action` | **Complete 7-Tab Master Roadmap & Technical Specifications Workbench**: **(1) `WF-01..WF-08` Whale Order Flow & Execution ML** (Kyle's Lambda, VPIN, Multi-Level OFI, Almgren-Chriss $\sinh$ Optimal Execution, GBDT Spread/Entropy, Predatory Square-Root Impact, Hawkes Process Hidden Liquidity, RL Execution Policy), **(2) `WSDM-01..05` Whale Signal Decision Matrix (When & Where to Buy/Sell)**, **(3) `SAAS-01..SAAS-10` Prop Firm B2B SaaS Verticals**, **(4) 5 Global Multi-Domain Architectures**, and **(5) All 26 `A–Z` Platform Subsystems (`Implemented`)**. |
| **Quant & Signal Matrix** | `/matrix` | `GET /api/matrix`, `POST /api/matrix/recompute` | **4-Tab Institutional Quant Matrix**: **(1) Multi-Horizon Signal Matrix (`9 Assets × 4 Horizons: 15m, 1h, 4h, 1D`)**, **(2) `9×9` Cross-Asset Realized Correlation Matrix** (`<= 0.80` gate), **(3) `5×5` Model Family × Causal Regime Attribution Grid**, and **(4) Multi-Venue L2 Depth-of-Market (DOM) Orderbook Ladders**. |
| **Live Listings** | `/listings` | `GET /api/listings`, `POST /api/listings/action` | Real-time multi-asset stock & prop watchlist (**`SPY`**, **`NVDA`**, **`AAPL`**, **`MSFT`**, **`QQQ`**, **`TSLA`**, **`BTC-USD`**, **`ETH-USD`**, **`SOL-USD`**), causal regime screener, custom listing onboarding, and 1-click order desk routing. |
| **Live Charts & Market PIT** | `/market` | `GET /api/market/candles`, `POST /api/market/ingest`, `POST /api/market/live-internet-sync` | **Dual-Mode Institutional Chart Engine**: toggle between **ATLAS Point-in-Time Candlestick + Volume + `t+1h`/`t+2h` Forecast Fan** and **TradingView Live Internet Chart** (`AMEX:SPY`, `NASDAQ:NVDA`, `NASDAQ:AAPL`, `NASDAQ:MSFT`, `NASDAQ:QQQ`, `NASDAQ:TSLA`, `COINBASE:BTCUSD`), plus 1-click live Internet candle sync. |
| **Enterprise API Data Warehouse** | `/warehouse` | `GET /api/warehouse`, `POST /api/warehouse/action` | **6-Node Institutional Data Lakehouse & Market API Hub**: **Google Cloud BigQuery & Analytics Hub**, **DuckDB + ZSTD Parquet Local PIT Engine**, **Databento L1/L2/MBO (`GLBX.MDP3`, `XNAS.ITCH`)**, **Polygon.io Multi-Asset**, **Coinbase Public Exchange Live API**, and **ClickHouse / TimescaleDB**, with an interactive Point-in-Time SQL Console. |
| **Execution & Risk Rules** | `/control`, `/rules` | `POST /api/control/order`, `POST /api/control/kill-switch`, `POST /api/control/flatten`, `POST /api/control/lifecycle` | Stateful `ActionableControlPlaneEngine` & versioned `TradingRuleBook` enforcing prop-competition and open-market risk limits, remaining-room proximity bars, emergency kill switch, auto-flatten, and human-reviewed model alias promotion/rollback. |
| **Governance & 8 Ledgers** | `/governance` | `POST /api/control/readiness-audit` | 9 Master-Spec Readiness Gates, 8 strictly separated non-custodial money ledgers, and ISO/IEC 42001, 23894, 27001, 22301, 31000, 9001, NIST AI RMF, and IOSCO alignment. |
| **Forecasts & Gemini Tick** | `/research` | `POST /api/research/continuous-tick`, `GET /api/research/demo` | Multi-model forecast comparison (`naive:last_value` vs. `local_tree:boosted_stump_v1`), empirical bin probability calibration, and paid-tier secret-screened Gemini & xAI ZDR research synthesis (`execution_permission: none`). |
| **Walk-Forward Evaluation Lab** | `/experiments` | `POST /api/research/walk-forward` | Purged & embargoed chronological walk-forward evaluation (`EXP-001`), track-specific paper simulation (`run_track_paper_simulation`), direct-vs-recursive multi-horizon gate, and feature ablation matrix. |
| **Models, MCP & SEC XBRL** | `/models` | `POST /api/research/train`, `POST /api/market/mcp-fetch` | From-scratch GBDT & linear model training lifecycle, allowlisted read-only MCP surface (`alpha_vantage_mcp`, `financial_datasets_mcp`, `fin_data_mcp`), `irohan0/quant-mcp` & FRED training blocks, whale microstructure filter, and SEC EDGAR as-filed XBRL fact selector. |
| **Data Syncing Center** | `/sync` | `GET /api/sync`, `POST /api/sync/run` | 6 point-in-time ingestion & state synchronization pipelines with configurable cadence (`5s`, `15s`, `60s`, `manual`), latency telemetry, and SHA-256 manifest verification. |
| **Integrations & MCP Hub** | `/integrations`, `/connectors` | `GET /api/connectors`, `POST /api/connectors/action` | 11 3rd-party integrations (Alpha Vantage, Financial Datasets, SEC EDGAR, FRED Guard, Gemini, xAI Grok, Chronos-2, NYSE/Nasdaq, Crypto Perp, SQLite Registry, and Quarantined MCP Guard) with bespoke SVG brand logos. |
| **Platform Configurations** | `/configurations`, `/settings` | `GET /api/configurations`, `POST /api/configurations` | Master Configuration Workbench with **1-Click Prop & Stock Desk Preset Templates (`$100K 2-Phase Prop`, `$50K Instant Funded`, `$250K Stock Desk`, `Strict Tournament`)**, prop notional caps, drawdown limits, challenger model families, walk-forward purge/embargo defaults, and provider rate budgets. |
| **User Profile & Keys** | `/profile` | `GET /api/profile`, `POST /api/profile` | Founder & Principal Architect operator identity, RBAC role switching (`founder_admin`, `researcher`, `monitoring`), SEC EDGAR User-Agent configuration, and 100% IP ownership boundary. |
| **Architecture & Specs** | `/docs` | `GET /api/docs` | Interactive in-app Markdown reader serving all 9 architecture, governance, research, and master specification documents directly from `docs/`. |

---

## Core Backend Modules (`src/atlas/`)

| Module | Implementation Summary |
| :--- | :--- |
| `src/atlas/api/app.py` | FastAPI production server exposing health, candles, capabilities, `/api/platform/snapshot`, actionable control-plane routes, live listings (`/api/listings`), data warehouse nodes (`/api/warehouse`), live Internet market candle sync (`/api/market/live-internet-sync`), pipeline sync (`/api/sync`), integrations (`/api/connectors`), global configurations (`/api/configurations`), operator profile (`/api/profile`), and markdown docs (`/api/docs`). |
| `src/atlas/control/rules.py` & `engine.py` | Stateful `ActionableControlPlaneEngine` and deterministic `TradingRuleBook` (`evaluate_trading_rules`, `RemainingRoomReport`) enforcing per-trade fractional risk, ATR/structure stops, VPIN flow-toxicity stop widening (`vpin_widening_threshold`, `vpin_stop_multiplier`) & adverse-selection quote pause (`vpin_pause_threshold`), daily loss circuit breaker, trailing/static drawdown, notional/leverage/correlation/sector caps, data quality/freshness/license gates, kill switch / auto-flatten, and prop-competition consistency & minimum trading days. Zero LLM imports. |
| `src/atlas/marketdata/microstructure.py` & `src/atlas/features/toxicity.py` | Institutional flow & toxicity engines: **Kyle's Lambda ($\lambda$)** (`estimate_kyles_lambda`), **Volume-Synchronized Probability of Informed Trading (VPIN)** (`compute_volume_synchronized_vpin`), **Multi-Level Order Flow Imbalance (OFI)** (`compute_multilevel_ofi`), and **Hawkes Self-Exciting Intensity Process** (`compute_hawkes_intensity`), plus point-in-time whale event normalization (`execution_permission: none`). |
| `src/atlas/execution/tactics/optimal.py` | **Almgren-Chriss Optimal Execution Trajectory** (`compute_almgren_chriss_trajectory`, `AlmgrenChrissSchedule`) solving $x_j = X \frac{\sinh(\kappa (T - t_j))}{\sinh(\kappa T)}$ with $\kappa = \sqrt{\frac{\lambda_{\text{risk}} \sigma^2}{\eta}}$, child-slice allocation, implementation shortfall cost/variance, and boundary verification (`execution_permission: none`). |
| `src/atlas/models/self_training.py` | **Autonomous Self-Training Loop ("Anti-Gravity" Module)**: **Triple-Barrier Labeling** (`label_triple_barrier_samples` with $+k \cdot \text{ATR}$, $-k \cdot \text{ATR}$, and vertical expiry), **Prop-Rulebook Objective Loss Function** (`compute_prop_aligned_loss`, $\mathcal{L}(\theta)$), and **Purged & Embargoed Walk-Forward OOS Gate** (`build_purged_embargoed_splits`, `run_autonomous_self_training_cycle`) proving zero lookahead leakage (`execution_permission: none`). |
| `src/atlas/models/calendars.py` & `regimes.py` | Authoritative `MarketCalendar` for NYSE/Nasdaq sessions (opening/closing auctions, holidays, early closes) and 24/7 crypto calendars (funding & maintenance windows), paired with strictly causal `classify_regime` across volatility, trend, liquidity, session, and macro-event dimensions. |
| `src/atlas/models/challengers.py` & `continuous.py` | From-scratch `LocalTreeChallengerProvider` (`boosted_stump_v1`, `gbdt_depth2_v1`), `FittedLinearBaseline` (`ridge_return_v1`), `FittedRegimeConditionedTree`, direct-vs-recursive horizon comparator, ensemble gate, `ContinuousResearchRunner`, `CentralResearchNode`, and `run_track_paper_simulation`. |
| `src/atlas/marketdata/` | `MCPDataSourceAdapter` with explicit tool allowlists, mutating server rejection (`irohan0/quant-mcp`), FRED training prohibition, `validate_market_data_batch` (`DataQualityReport`), SHA-256 frozen benchmark datasets (`frozen.py`), whale/microstructure normalization (`microstructure.py`), and SEC EDGAR as-filed XBRL fact selection (`sec_edgar.py`). |
| `src/atlas/feeds/` | **The one authoritative ATLAS feed** (paper/simulation only): a point-in-time SQLite bar store (`var/feeds/atlas_feed.sqlite`, git-ignored) that UDF charts, training, evidence and replay all read. Provider failover, rate limits, backoff, gap fill and quality flags (`predict()` abstains when a flag is set). 20 provider adapters, each with a capability manifest. Backfill with `scripts/backfill_feeds.py`. See `docs/data-feeds.md` and `docs/data-providers/`. |
| `src/atlas/models/model_store.py` & `experiments.py` | Durable SQLite model registry (`SQLiteModelRegistry`), scoped approvals with revocation audit history, persisted probability calibrators (`ProbabilityCalibrator`), and SQLite experiment checkpoints. |

---

## Authority, Non-Custodial & Data Boundaries

- **Strict AI vs. Control-Plane Separation**: Every forecast, model record, research signal, regime state, warehouse query, data batch, walk-forward study, and rule evaluation report carries `execution_permission: none`. Only the deterministic control plane (`ActionableControlPlaneEngine`) can authorize, size, or reject an order. LLMs cannot place, cancel, or size orders, override risk limits, or toggle the kill switch.
- **8 Non-Custodial Money Ledgers**: Software subscriptions, broker accounts, exchange accounts, external user wallets, custodians, prop-firm evaluation accounts, founder treasury, and any future double-entry customer ledger remain strictly separate records.
- **Data Warehouse & Licensing Discipline**: Point-in-time enforcement (`available_at <= as_of`) applies across BigQuery Analytics Hub, DuckDB + Parquet, Databento, Polygon.io, Coinbase Public REST, and SEC EDGAR XBRL facts. FRED data is blocked from ML training/archival per terms, and `irohan0/quant-mcp` is permanently quarantined.

---

## Founder Capital Track (Lola port)

The Lola platform's features are now part of ATLAS (see [docs/lola-port-plan.md](docs/lola-port-plan.md)):
- **2% daily-loss Safe stop** is the default for the founder's own capital. The prop-competition rulebook keeps its configurable 4%.
- Separate watchdog, approval queue with step-up, and Canadian venues and tax (ACB, superficial loss, BoC FX, T5008/T1135).
- Payments, investor wallet and compliance are mapped onto the 8 non-custodial ledgers.
- New pages: `/money`, `/payments`, `/portal`, `/tax`, `/compliance`, `/inbox`, plus a Safe stop button.

Paper only, and `execution_permission: none` everywhere. Install with `pip install -e ".[dev,founder,ml,mcp]"`.

## Quick Start & Run Commands

Python 3.11+ (workspace uses Python 3.12) and Node.js 18+:

```powershell
# 1. Run backend test suite (90 tests) and start FastAPI server on port 8000
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn atlas.api.app:app --host 127.0.0.1 --port 8000
```

```powershell
# 2. Typecheck, build, and start Next.js institutional terminal on port 3000
cd frontend
npm run typecheck
npm run build
npm run start -- -p 3000
```

```powershell
# 3. Inspect full production platform state via CLI
.\.venv\Scripts\python.exe -m atlas.models.platform_state
```

---

## Documentation Index

- [Master Spec](docs/ATLAS_MASTER_SPEC.md): Product, authority, prop-competition vs. open-market stock tracks, and non-custodial boundaries.
- [Universal AI Ecosystem Architecture](docs/architecture/UNIVERSAL_AI_ECOSYSTEM.md): Full implementation map, data warehouse topology, provider protocols, training pipelines, and evaluation.
- [Research Operating Contract](docs/architecture/RESEARCH_OPERATING_CONTRACT.md): Versioned research gates, causal regime handling, dual tracks, and deterministic control-plane rule fields.
- [ISO, NIST AI RMF & IOSCO Governance Alignment](docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md): Standards mapping for institutional governance readiness.
- [Current State](docs/architecture/CURRENT_STATE.md): Verified modules, 16 domain workbenches across 19 frontend routes, backend API endpoints, and test verification.
- [Decisions Log](docs/architecture/DECISIONS.md): Architectural decisions 1–43 binding the repository.
- [Agile Backlog](docs/backlog/AGILE_BACKLOG.md): Completed platform increments and external licensing roadmap.
- [AI Ecosystem Review](docs/research/AI_ECOSYSTEM.md) & [MCP Data Integration Review](docs/research/MCP_DATA_INTEGRATION.md).

---

## Verification Status (2026-10-20)

- **Backend Test Suite**: **`90 passed`** (`.\.venv\Scripts\python.exe -m pytest -q`) covering all 7 sheets of the Master Roadmap & Technical Specifications (`A–Z` 26 subsystems, `WF-01..WF-08` Whale Order Flow & Execution ML, `WSDM-01..WSDM-05` Whale Signal Decision Matrix, `SAAS-01..SAAS-10` Prop Firm B2B SaaS Verticals, 5 Global Multi-Domain asset classes), closed-loop Self-Training ML pipeline (`src/atlas/models/self_training.py`), institutional microstructure (Kyle's Lambda, VPIN, Multi-Level OFI, Hawkes intensity), Almgren-Chriss optimal execution trajectories, Triple-Barrier labeling & prop-aligned objective loss $\mathcal{L}(\theta)$, purged/embargoed walk-forward splits, VPIN-aware deterministic control-plane trading rules, allowlisted MCP & SEC EDGAR XBRL adapters, warehouse nodes, live Internet candle sync, SQLite registry, and all actionable control-plane endpoints.
- **Frontend Build**: **`0 errors`** on `npm run typecheck` (`tsc --noEmit`) and **`22/22 static pages generated`** on `npm run build` across all 19 application routes.
