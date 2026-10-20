# ATLAS — Institutional Proprietary (Prop) Trading & Stock Quant Platform

ATLAS (**Autonomous Trading, Liquidity, Allocation & Strategy Intelligence**) is a founder-owned **Proprietary (Prop) Trading, U.S. Stock Trading, and Multi-Model Quantitative Research Platform** engineered around a strict architectural separation between **AI/Quantitative Research (`execution_permission: none`)** and a **Deterministic Control Plane (`ActionableControlPlaneEngine`)**.

ATLAS is specialized to operate seamlessly across **two distinct, synchronized trading tracks**:
1. **🏛️ Open-Market Stock & ETF Trading (`open_market` track)** — Trading U.S. Equities and Benchmark ETFs on **NYSE Arca & Nasdaq (`XNYS` / `XNAS`)** including **`SPY`**, **`NVDA`**, **`AAPL`**, **`MSFT`**, **`QQQ`**, and **`TSLA`** with regular-session calendars (`09:30–16:00 ET`), **SEC EDGAR Point-in-Time XBRL fundamentals** (`acceptance_time <= as_of`), **Databento / Polygon.io** SIP stock feeds, and **Alpaca / Interactive Brokers** execution routing.
2. **🏆 Prop Trading Competitions & Funded Evaluations (`competition` track)** — Participating in proprietary trading firm challenges, funded account evaluations, and 24/7 liquid derivative competitions (**`BTC-USD`**, **`ETH-USD`**, **`SOL-USD`**, and cross-asset prop books) governed by hard deterministic prop-firm rulebooks (**4.0% Daily Loss Circuit Breaker**, **8.0% Max Trailing Drawdown Floor**, **$\le 35\%$ Single-Day Profit Consistency Gate**, **$\ge 5$ Minimum Trading Days**, **0.50%–0.75% Per-Trade Risk Cap**, and **Mandatory ATR/Structure Stop-Loss Distance**).

The workspace is `C:\Users\borah\ATLAS`. The founder retains 100% ownership of source code, strategy logic, model artifacts, and signing keys; an infrastructure operator receives zero order discretion or ownership transfer.

---

## Complete Platform Map (15 Domain Workbenches & 18 Live Routes)

The terminal features an **Icon-Driven Domain Sidebar** (zero wizard/step numbering), a **Live Multi-Asset Ticker Tape** across the top (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`, `BTC-USD`, `ETH-USD`, `SOL-USD`), and a **Persistent Dockable Right-Hand Trading, L2 Orderbook DOM Ladder & Prop Risk Dock** alongside every workbench:

| Domain Workbench | Route(s) | Backend API Endpoint(s) | Institutional Capability |
| :--- | :--- | :--- | :--- |
| **Command Center** | `/` | `/api/platform/snapshot`, `/api/control/state` | Unified Bento Command Workbench with **Topbar Dual-Track Switcher (`Open-Market Stocks` ↔ `Prop Competition`)**, **1-Click Stock & Prop Ticker Strip**, **Prop Evaluation Scorecard**, Dual-Mode Live Chart, and Pre-Trade Risk-Checked Order Desk. |
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
| `src/atlas/control/rules.py` & `engine.py` | Stateful `ActionableControlPlaneEngine` and deterministic `TradingRuleBook` (`evaluate_trading_rules`, `RemainingRoomReport`) enforcing per-trade fractional risk, ATR/structure stops, daily loss circuit breaker, trailing/static drawdown, notional/leverage/correlation/sector caps, data quality/freshness/license gates, kill switch / auto-flatten, and prop-competition consistency & minimum trading days. Zero LLM imports. |
| `src/atlas/models/calendars.py` & `regimes.py` | Authoritative `MarketCalendar` for NYSE/Nasdaq sessions (opening/closing auctions, holidays, early closes) and 24/7 crypto calendars (funding & maintenance windows), paired with strictly causal `classify_regime` across volatility, trend, liquidity, session, and macro-event dimensions. |
| `src/atlas/models/challengers.py` & `continuous.py` | From-scratch `LocalTreeChallengerProvider` (`boosted_stump_v1`, `gbdt_depth2_v1`), `FittedLinearBaseline` (`ridge_return_v1`), `FittedRegimeConditionedTree`, direct-vs-recursive horizon comparator, ensemble gate, `ContinuousResearchRunner`, `CentralResearchNode`, and `run_track_paper_simulation`. |
| `src/atlas/marketdata/` | `MCPDataSourceAdapter` with explicit tool allowlists, mutating server rejection (`irohan0/quant-mcp`), FRED training prohibition, `validate_market_data_batch` (`DataQualityReport`), SHA-256 frozen benchmark datasets (`frozen.py`), whale/microstructure normalization (`microstructure.py`), and SEC EDGAR as-filed XBRL fact selection (`sec_edgar.py`). |
| `src/atlas/models/model_store.py` & `experiments.py` | Durable SQLite model registry (`SQLiteModelRegistry`), scoped approvals with revocation audit history, persisted probability calibrators (`ProbabilityCalibrator`), and SQLite experiment checkpoints. |

---

## Authority, Non-Custodial & Data Boundaries

- **Strict AI vs. Control-Plane Separation**: Every forecast, model record, research signal, regime state, warehouse query, data batch, walk-forward study, and rule evaluation report carries `execution_permission: none`. Only the deterministic control plane (`ActionableControlPlaneEngine`) can authorize, size, or reject an order. LLMs cannot place, cancel, or size orders, override risk limits, or toggle the kill switch.
- **8 Non-Custodial Money Ledgers**: Software subscriptions, broker accounts, exchange accounts, external user wallets, custodians, prop-firm evaluation accounts, founder treasury, and any future double-entry customer ledger remain strictly separate records.
- **Data Warehouse & Licensing Discipline**: Point-in-time enforcement (`available_at <= as_of`) applies across BigQuery Analytics Hub, DuckDB + Parquet, Databento, Polygon.io, Coinbase Public REST, and SEC EDGAR XBRL facts. FRED data is blocked from ML training/archival per terms, and `irohan0/quant-mcp` is permanently quarantined.

---

## Quick Start & Run Commands

Python 3.11+ (workspace uses Python 3.12) and Node.js 18+:

```powershell
# 1. Run backend test suite (81 tests) and start FastAPI server on port 8000
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
- [Current State](docs/architecture/CURRENT_STATE.md): Verified modules, 17 frontend routes, backend API endpoints, and test verification.
- [Decisions Log](docs/architecture/DECISIONS.md): Architectural decisions 1–42 binding the repository.
- [Agile Backlog](docs/backlog/AGILE_BACKLOG.md): Completed platform increments and external licensing roadmap.
- [AI Ecosystem Review](docs/research/AI_ECOSYSTEM.md) & [MCP Data Integration Review](docs/research/MCP_DATA_INTEGRATION.md).

---

## Verification Status (2026-10-20)

- **Backend Test Suite**: **`81 passed`** (`.\.venv\Scripts\python.exe -m pytest -q`) covering schemas, calendars, causal regimes, deterministic prop & open-market trading rules, allowlisted MCP & SEC EDGAR XBRL adapters, warehouse nodes, live Internet candle sync, walk-forward studies, SQLite registry, and all actionable control-plane endpoints.
- **Frontend Build**: **`0 errors`** on `npm run typecheck` (`tsc --noEmit`) and **`20/20 static pages generated`** on `npm run build` across all 17 application routes.
