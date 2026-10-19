# ATLAS

ATLAS is **Autonomous Trading, Liquidity, Allocation & Strategy Intelligence**:
a founder-owned platform for extensible AI research, training, evaluation and
forecasting across permitted markets. Extensibility does not imply that one model
predicts every market or that adding models improves performance.

The research objective is continuous, regime-aware work across two separately
evaluated tracks: named prop-competition rules and open-market forecast horizons.
24/7 research scheduling is not 24/7 trading authority. No live execution engine
or order path is implemented here.

The workspace is `C:\Users\borah\ATLAS`. It contains a read-only scaffold and a
universal research foundation. It contains no live execution engine. The founder
retains source, strategy logic, model artifacts and signing keys; an infrastructure
operator receives no order discretion or ownership transfer.

## What is built

| Module | Current behavior |
| --- | --- |
| FastAPI | Read-only health, fixture candles, discovered research capabilities, and synthetic research demo GET routes; trading disabled |
| Market fixtures & frozen datasets | Invented BTC-USD 1h candles plus SHA-256 verified frozen point-in-time benchmark datasets (`src/atlas/marketdata/frozen.py`) |
| Next.js | Research terminal with fixture plot/table, causal regime overlay, quality/freshness status, control-plane rule remaining-room bars, baseline-vs-tree disagreement & calibration, walk-forward study viewer, MCP inventory, ISO governance readiness, and role-based views |
| Gemini research | Existing screened, paid-tier provider and research CLI; no tools |
| Provider contracts | Separate research, forecast, prediction, training, embedding, retrieval, registry, read-only data (`ReadOnlyDataProvider`), and optional deployment/batch/stream protocols |
| Discovery/runtime | Advertised capability checks, configurable request/token budgets, deadline/retry/backoff, circuit breaker, cost and latency events |
| Instrument/horizon & calendars | Nine asset classes; versioned `MarketCalendar` (`src/atlas/models/calendars.py`) for traditional sessions (auctions, holidays, early closes) and 24/7 crypto (funding & maintenance windows) |
| Causal regime detection | Point-in-time `classify_regime` (`src/atlas/models/regimes.py`) across volatility, trend, liquidity, session, and macro-event dimensions with explicit `unknown` fallback |
| Control-plane rules | Versioned `TradingRuleBook` & `evaluate_trading_rules` (`src/atlas/control/rules.py`) for per-trade risk, daily loss breaker, static/trailing drawdown, exposure caps, quality/freshness/license gates, session/time exits, kill switch, and competition consistency rules (default-deny, zero LLM imports) |
| Read-only MCP data | `MCPDataSourceAdapter` (`src/atlas/marketdata/mcp_adapters.py`) with allowlisted tools (`alpha_vantage_mcp`, `financial_datasets_mcp`, `fin_data_mcp`), write/execution rejection, `irohan0/quant-mcp` block, FRED training block, and `DataQualityReport` |
| Walk-forward & tree challenger | Deterministic `LocalTreeChallengerProvider` and purged walk-forward comparison (`src/atlas/models/challengers.py`) against naive/no-trade baselines with non-promoting `OutcomeFeedbackRecord` |
| Evaluation & lifecycle | Predictive, return, calibration, cost, drawdown and tail metrics; block bootstrap; immutable model metadata, SQLite research-alias rollback, and SQLite experiment history |

## Authority and data boundaries

Models produce research records. Every forecast, model record, research signal,
regime state, data batch, walk-forward study, and rule evaluation report has
`execution_permission: none`. The deterministic control plane alone may authorize
future orders. LLMs cannot place/cancel/size orders, override risk, or control a
kill switch. Research approval is per model revision, instrument, horizon, target
and unit; it does not grant execution authority.

The customer keeps funds at their existing venue. Software subscriptions, broker
accounts, exchange accounts, external wallets, custodians, prop rules, founder
treasury and any future customer-funds ledger remain separate records. No custody,
deposit address, withdrawal or live order change is implemented. See the
[master spec](docs/ATLAS_MASTER_SPEC.md) for the full boundary.

Secrets do not belong in prompts, frontend bundles, logs or this repository.
Gemini remains the preferred generative provider behind a replaceable interface.
Its research confidence is uncalibrated and never enters forecast combination.
No OpenAI SDK or API dependency is added. Allora Topic 38 remains out of scope.

Training produces an immutable research challenger, not an automatic deployment.
Unknown data quality, missing approval or an unverified model license prevents
forecast selection. No ensemble combiner is enabled without independent evidence.
No evaluation performed here establishes profitability or universal superiority.

## Run

Python 3.11+; this workspace uses Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,gemini]"
pytest -q
uvicorn atlas.api.app:app --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

The page reads `NEXT_PUBLIC_ATLAS_API`, defaulting to `http://localhost:8000`.
It shows invented fixtures, not market prices.

An offline ecosystem demonstration requires no keys or model downloads:

```powershell
.\.venv\Scripts\python.exe -m atlas.models.demo
```

The existing research CLI needs a paid Gemini account configured outside source:
`GEMINI_API_KEY` and `ATLAS_GEMINI_TIER=paid`. It refuses empty/oversized context
and recognizable secrets.

```powershell
atlas-research "plain observations with no secrets" --workload frequent
```

## Documentation

- [Master spec](docs/ATLAS_MASTER_SPEC.md): product and authority boundaries.
- [Universal AI architecture](docs/architecture/UNIVERSAL_AI_ECOSYSTEM.md): implementation map, interfaces, pipelines, evaluation and limitations.
- [Research operating contract](docs/architecture/RESEARCH_OPERATING_CONTRACT.md): versioned research gates, regime handling, two tracks, and control-plane rule fields.
- [ISO, NIST AI RMF & IOSCO governance alignment](docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md): standards mapping for future certification readiness (no certification claimed).
- [Provider research](docs/research/AI_ECOSYSTEM.md): official-source capability, privacy and commercial review.
- [MCP data integration review](docs/research/MCP_DATA_INTEGRATION.md): candidate servers, vendor/data rights, and bounded ingestion plan.
- [Current state](docs/architecture/CURRENT_STATE.md): verified code and checks.
- [Backlog](docs/backlog/AGILE_BACKLOG.md): completed foundation and remaining external licensing/live integration tracks.
- [Decisions](docs/architecture/DECISIONS.md): recorded choices and scope updates.

## Verification

Universal foundation, regime classification, deterministic control rules, MCP
contracts, walk-forward baseline-vs-tree study, and expanded research terminal:
**73 tests passed** on 2026-10-19; the frontend type check and production build
also passed, and the offline demo ran successfully.
