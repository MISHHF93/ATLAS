# Current State — ATLAS Institutional Prop Trading & Stock Quant Platform

Verified in `C:\Users\borah\ATLAS` on **2026-10-20**.

ATLAS is a fully integrated **Dual-Track Proprietary (Prop) Trading, U.S. Stock Trading, and Multi-Model Quantitative Research Platform** comprising a deterministic Python control-plane & quant backend (`src/atlas/`) and a 14-layer Next.js institutional operating terminal (`frontend/`).

---

## 1. Dual-Track Operating Architecture

1. **Open-Market Stock & ETF Trading Desk (`open_market` track)**
   - **Universe**: U.S. Equities & Benchmark ETFs on NYSE Arca & Nasdaq (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`).
   - **Calendars & Fundamentals**: Regular NYSE/Nasdaq session schedules (`src/atlas/models/calendars.py`), SEC EDGAR as-filed XBRL facts (`src/atlas/marketdata/sec_edgar.py`, `acceptance_time <= as_of`), and SIP/Polygon/Databento point-in-time bars.
2. **Prop Trading Competition & Funded Challenge Desk (`competition` track)**
   - **Universe**: 24/7 Prop Competition Perpetuals (`BTC-USD`, `ETH-USD`, `SOL-USD`) and funded evaluation books.
   - **Deterministic Prop Rulebook (`src/atlas/control/rules.py`)**: Enforces `$100,000` evaluation tracking (`$101,850` current equity), `4.0%` daily loss circuit breaker, `8.0%` trailing drawdown floor, `<= 35%` single-day profit consistency rule, `>= 5` minimum trading days, `0.50%–0.75%` per-trade fractional risk cap, and mandatory ATR/structure stop-loss distances.

---

## 2. Frontend Operating Terminal (`frontend/` — 14 Layers & 17 Static Routes)

- **`/` (`01 · Command Center`)**: Topbar Dual-Track Switcher (`Open-Market Stocks` ↔ `Prop Competition`), 1-Click Stock & Prop Ticker Selector Strip (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`, `BTC-USD`, `ETH-USD`, `SOL-USD`), Prop Evaluation Scorecard, Dual-Mode Chart, 10-card Platform Directory, and Pre-Trade Risk-Checked Order Desk.
- **`/listings` (`02 · Live Listings`)**: 9 live stock & prop listings with track filtering, quote refresh, enable/disable toggles, custom listing onboarding, and 1-click order desk routing.
- **`/market` (`03 · Live Charts & Market PIT`)**: Dual-Mode Institutional Chart Engine (**ATLAS PIT Candlestick + Volume + `t+1h`/`t+2h` Forecast Fan** vs. **TradingView Live Internet Chart**), plus 1-click live candle synchronization (`POST /api/market/live-internet-sync`) and point-in-time bar ingestion.
- **`/warehouse` (`04 · Enterprise API Data Warehouse`)**: 6 connected warehouse & market API nodes (**Google Cloud BigQuery & Analytics Hub**, **DuckDB + Parquet Local Vectorized PIT Store**, **Databento L1/L2/MBO ITCH**, **Polygon.io Multi-Asset**, **Coinbase Public Exchange Live API**, and **ClickHouse / TimescaleDB**) with an interactive Point-in-Time SQL Console.
- **`/control` & `/rules` (`05 · Deterministic Control Plane`)**: Pre-trade order authorization, risk proximity progress bars, emergency kill switch, position flatten-all, and human-reviewed challenger promotion/rollback.
- **`/governance` (`06 · Governance & 8 Ledgers`)**: 9 Master-Spec Readiness Gates, 8 separated non-custodial money ledgers, and ISO/IEC 42001, 23894, 27001, 22301, 31000, 9001, NIST AI RMF, and IOSCO alignment.
- **`/research` (`07 · AI Forecasts & Gemini 24/7 Node`)**: Multi-model forecast fan, empirical bin probability calibration, and paid-tier secret-screened Gemini & xAI ZDR synthesis (`execution_permission: none`).
- **`/experiments` (`08 · Walk-Forward Lab`)**: Purged & embargoed walk-forward evaluator (`EXP-001`), paper trading simulator (`run_track_paper_simulation`), and direct-vs-recursive horizon gate.
- **`/models` (`09 · Models, MCP & SEC XBRL`)**: Scratch GBDT (`boosted_stump_v1`, `gbdt_depth2_v1`) & linear (`ridge_return_v1`) training lifecycle, allowlisted MCP fetch, whale microstructure filter, and SEC EDGAR XBRL fact viewer.
- **`/sync` (`10 · Data Syncing Center`)**: 6 point-in-time synchronization pipelines with cadence controls (`5s`, `15s`, `60s`, `manual`) and SHA-256 manifests.
- **`/integrations` & `/connectors` (`11 · Integrations & MCP Hub`)**: 11 3rd-party connectors with bespoke SVG brand logos and connection testing.
- **`/configurations` & `/settings` (`12 · Platform Configurations`)**: Master configuration workbench + universal `⚙ Quick Config` inline drawer accessible from every page.
- **`/profile` (`13 · User Profile & Keys`)**: Founder operator identity, RBAC role switching (`founder_admin`, `researcher`, `monitoring`), SEC User-Agent, and 100% IP ownership boundary.
- **`/docs` (`14 · Architecture & Specs`)**: Live Markdown documentation reader for all repository specs.

---

## 3. Backend Modules & Endpoints (`src/atlas/`)

- **`src/atlas/api/app.py`**: FastAPI application serving `/api/health`, `/api/market/candles`, `/api/research/capabilities`, `/api/research/demo`, `/api/platform/snapshot`, `/api/control/state`, `/api/control/order`, `/api/control/kill-switch`, `/api/control/flatten`, `/api/control/lifecycle`, `/api/control/readiness-audit`, `/api/research/train`, `/api/research/walk-forward`, `/api/research/continuous-tick`, `/api/market/mcp-fetch`, `/api/market/ingest`, `/api/market/live-internet-sync`, `/api/listings`, `/api/listings/action`, `/api/warehouse`, `/api/warehouse/action`, `/api/sync`, `/api/sync/run`, `/api/connectors`, `/api/connectors/action`, `/api/configurations`, `/api/profile`, and `/api/docs`.
- **`src/atlas/control/`**: `ActionableControlPlaneEngine` (`engine.py`) and `TradingRuleBook` (`rules.py`).
- **`src/atlas/models/`**: `schemas.py`, `providers.py`, `registry.py`, `model_store.py`, `runtime.py`, `adapters.py`, `calendars.py`, `regimes.py`, `challengers.py`, `continuous.py`, `orchestrator.py`, `evaluation.py`, `experiments.py`, `training.py`, and `platform_state.py`.
- **`src/atlas/marketdata/`**: `mcp_adapters.py`, `quality.py`, `frozen.py`, `microstructure.py`, and `sec_edgar.py`.

---

## 4. Verification Summary (2026-10-20)

- **Backend (`pytest`)**: **`81 passed`** (`.\.venv\Scripts\python.exe -m pytest -q`).
- **Frontend (`tsc` & `next build`)**: **`0 errors`** on `npm run typecheck` and **`20/20 static pages generated`** on `npm run build`.
- **Platform State CLI**: `.\.venv\Scripts\python.exe -m atlas.models.platform_state` executes cleanly and outputs verified JSON telemetry.
