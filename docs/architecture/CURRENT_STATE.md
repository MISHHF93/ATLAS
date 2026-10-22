# Current State — ATLAS Institutional Prop Trading & Stock Quant Platform

Verified in `C:\Users\borah\ATLAS-main` on **2026-10-21**. The operating plan is [EXECUTION_PLAN.md](EXECUTION_PLAN.md).

ATLAS is a dual-track research and paper desk: a deterministic Python control plane (`src/atlas/`) and a Next.js terminal (`frontend/`). The shell is six primary destinations (Desk, Markets, Trade, Risk, Research, Data). Older routes still exist. Public crypto and equity candles load when Coinbase or Yahoo answer. Otherwise the chart stays on the labeled fixture. The whale policy trains on those candles for both books and cannot send an order.

---

## 1. Dual-Track Operating Architecture & 4-Role Client RBAC

1. **Open-Market Stock & ETF Trading Desk (`open_market` track)**
   - **Universe**: U.S. Equities & Benchmark ETFs on NYSE Arca & Nasdaq (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`).
   - **Calendars & Fundamentals**: Regular NYSE/Nasdaq session schedules (`src/atlas/models/calendars.py`) and SEC EDGAR as-filed XBRL facts (`src/atlas/marketdata/sec_edgar.py`, `acceptance_time <= as_of`). Equity chart bars come from Yahoo's public chart API when it answers. Polygon, Databento, and broker sessions are not configured.
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

- **Backend (`pytest`)**: **`168 passed`** (`.\.venv\Scripts\python.exe -m pytest -q`).
- **Frontend (`tsc` & `next build`)**: **`0 errors`** on `npm run typecheck` and **`43/43 static pages generated`** on `npm run build`.
- **Strict AI Air-Gap**: Zero `atlas.ai` imports in `src/atlas/control/`; all research, ML, MCP, and streaming payloads enforce `execution_permission: "none"`.
- **Public candles**: `GET /api/market/bars` uses Coinbase or Yahoo when `public_fetch_enabled` is on, and names that source. A miss stays `labeled_synthetic_fixture`.
- **Training path** `desk-public-candle-walk-forward:v1`: one pass reads daily public candles, labels printed closes, runs the walk-forward gate, fits a competition vector and an open-market vector, scores both books, and withholds orders. `GET /api/ml/chart-read` uses the book vector on the timeframe on screen.
- **Range garden** `range-garden:v1`: the paper harvest in `docs/roadmap/range_garden.md`. A one-second tender buys the lower rail and sells the upper rail only when the box clears cost and the print is fresh. Crypto last trades are Coinbase public. Equity minute bars are too old for the 2000 ms open-market rule, so that book watches. The control plane papers the bracket. The signal stays `execution_permission: none`.
- **Charts**: the desk, markets, trade cockpit, and market terminal embed TradingView's Advanced Chart plus their quote, technical rating, profile, financials, and news for the same symbol. The desk and markets page also show the nine-name ticker tape. None of those widgets feed the model. The model reads the public-candle path for that same symbol and resolution. `EQ####` and `PERP###-USD` are not given a substitute chart.
- **Reserve sleeve** `reserve-yield:v1`: a paper target that splits cumulative paper profit 40/30/20/10 across munis, T-bills, `VOO`/`QQQ`, and `VNQ`/`CPT`. No order is submitted. Bond-scanner and TRACE sessions are not connected. `pos-001` stays open.
- **Catalog**: Markets embeds TradingView's US stock screener, crypto screener, US ETF heatmap, and forex screener. A click opens `/?tvwidgetsymbol=` on this host only. The desk charts that qualified symbol. The model reads Coinbase, Yahoo, or a mapped futures root when the listing has one, and otherwise says the listing has no public-candle series. The local synthetic catalog is not replaced with a downloaded symbol list.
