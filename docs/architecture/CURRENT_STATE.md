# Current State — ATLAS Institutional Prop Trading & Stock Quant Platform

Verified in `C:\Users\borah\ATLAS` on **2026-10-21**.

ATLAS is a fully integrated **Dual-Track Proprietary (Prop) Trading, U.S. Stock Trading, and Multi-Model Quantitative Research Platform** comprising a deterministic Python control-plane & quant backend (`src/atlas/`) and a 41-route Next.js institutional operating terminal (`frontend/`).

---

## 1. Dual-Track Operating Architecture & 4-Role Client RBAC

1. **Open-Market Stock & ETF Trading Desk (`open_market` track)**
   - **Universe**: U.S. Equities & Benchmark ETFs on NYSE Arca & Nasdaq (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`).
   - **Calendars & Fundamentals**: Regular NYSE/Nasdaq session schedules (`src/atlas/models/calendars.py`), SEC EDGAR as-filed XBRL facts (`src/atlas/marketdata/sec_edgar.py`, `acceptance_time <= as_of`), and SIP/Polygon/Databento point-in-time bars.
2. **Prop Trading Competition & Funded Challenge Desk (`competition` track)**
   - **Universe**: 24/7 Prop Competition Perpetuals (`BTC-USD`, `ETH-USD`, `SOL-USD`) and funded evaluation books.
   - **Deterministic Prop Rulebook (`src/atlas/control/rules.py` & `engine.py`)**: Enforces `$100,000` evaluation tracking (`$101,850` current equity), `4.0%` daily loss circuit breaker, `8.0%` trailing drawdown floor, `<= 35%` single-day profit consistency rule, `>= 5` minimum trading days, `0.50%–0.75%` per-trade fractional risk cap, mandatory ATR/structure stop-loss distances, and a `500ms` feed staleness circuit breaker.
3. **4-Role Client Taxonomy & RBAC (`src/atlas/api/rbac.py` & `frontend/src/context/RoleContext.tsx`)**
   - `prop_firm_admin`: B2B Enterprise Prop Operator (`/control`, `/rules`, `/governance`, `/warehouse`, `/listings`).
   - `quant_researcher`: Institutional Quant Researcher (`/research`, `/experiments`, `/models`, `/market`, `/warehouse`; `execution_permission: none`).
   - `funded_trader`: Challenge & Funded Desk Trader (`/`, `/market`, `/listings`, `/profile`, `/trade/*`; blocked from kill switch & risk parameter mutations).
   - `compliance_auditor`: External Auditor & Regulatory Officer (`/governance`, `/docs`, `/sync`, `/data/governance`; `execution_permission: none`).

---

## 2. Frontend Operating Terminal (`frontend/` — 41 Static Routes & 4-Pillar Institutional Shell)

- **4-Pillar Institutional Navigation (`InstitutionalWorkspacesView.tsx`)**:
  1. **Trading & Execution (`/trade/cockpit`, `/trade/depth-dom`, `/trade/blotter`, `/trade/journal`)**: Live Chart + VWAP/EMA-9 + Volume Profile (`VAH`/`VAL`/`POC`), Autonomous Whale ML Trainer (`WhalePolicyModel`), Pre-Trade Bracket Order Desk, and Live Remaining-Room HUD.
  2. **Prop Risk & Surveillance (`/control/risk-hud`, `/control/rulebook`, `/control/surveillance`, `/control/proctoring`, `/control/dealing-desk`)**: Real-time cushion gauges, Sybil/latency-arbitrage behavioral proctoring, and B-Book to A-Book dealing desk copier.
  3. **Quant & AI Lab (`/research/central-node`, `/research/walk-forward`, `/research/microstructure`, `/research/registry`)**: `QM-01..QM-08` Canonical Institutional Quantitative Measurements, Preregistered Feature Ablations (`ABL-01..ABL-04`), Purged Walk-Forward Lab (`EXP-001`), and Challenger Model Registry.
  4. **Data & 100 Features (`/data/lakehouse`, `/data/pipelines`, `/data/governance`, `/data/features-100`)**: DuckDB/Parquet/BigQuery PIT SQL console, 100-Feature Matrix (`tab9_100_feature_matrix.csv`), Visual Automation Scanner (`AUTO-01..AUTO-10`), and 8 Separated Non-Custodial Ledgers.
- **`/listings` (`Module02ListingsView.tsx`)**: Real-time WebSocket (`/ws/market-stream`) & snapshot (`/api/market/module02-snapshot`) dual-track workbench with 10,000-slot ring buffer telemetry, directional tick flashes, Rolling VPIN, Top-5 L2 OFI (`ofi` & `ofi_z`), and Kyle's $\lambda$.

---

## 3. Backend Modules & Endpoints (`src/atlas/`)

- **`src/atlas/marketdata/live_stream.py` & `src/atlas/api/ws.py`**: 10,000-slot lock-free `OrderBookRingBuffer` (`collections.deque(maxlen=10000)`), `LiveMarketDataGateway`, and `/ws/market-stream` WebSocket broadcaster (`execution_permission: none`).
- **`src/atlas/models/whale_policy.py` & `src/atlas/control/engine.py`**: Custom Microstructure & Whale Policy Model (`WhalePolicyModel`) trained with Triple-Barrier labeling and purged walk-forward CV, paired with deterministic `ActionableControlPlaneEngine.submit_whale_signal()` bracket intake.
- **`src/atlas/features/microstructure.py`**: Canonical mathematical kernels for Rolling VPIN, Multi-Level L2 OFI, Streaming & Ridge Kyle's $\lambda$, Hawkes Self-Exciting Intensity $\lambda(t)$, and `compute_institutional_quantitative_measurements()` (`QM-01..QM-08`).
- **`src/atlas/backlog_tracker.py`**: Master To-Do & Agile Backlog Execution Engine verifying `M01..M06` and `TODO-01..TODO-07` (`GET /api/backlog/todos` and `POST /api/backlog/todos/verify`).

---

## 4. Verification Summary (2026-10-21)

- **Backend (`pytest`)**: **`117+ passed`** (`.\.venv\Scripts\python.exe -m pytest -q`).
- **Frontend (`tsc` & `next build`)**: **`0 errors`** on `npm run typecheck` and **`41/41 static pages generated`** on `npm run build`.
- **Strict AI Air-Gap**: Zero `atlas.ai` imports in `src/atlas/control/`; all research, ML, MCP, and streaming payloads enforce `execution_permission: "none"`.
