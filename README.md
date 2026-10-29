# ATLAS

ATLAS (Autonomous Trading, Liquidity, Allocation & Strategy Intelligence) is a founder-owned research and **paper-trading** platform. It has a Python backend (`src/atlas/`, FastAPI) and a Next.js terminal (`frontend/`). It covers three tracks:

- **Founder capital** (paper). This is the default. It has a 2% daily-loss Safe stop, a 10% static drawdown limit and a 1-day maximum holding period.
- **Open market** (US equities and ETFs, paper).
- **Prop competition** (24/7 crypto, paper). This track has a 4% daily breaker, an 8% trailing drawdown limit, a 35% consistency gate and a 5-day minimum.

> **Status, 2026-10-28.** This checkout is `C:\Users\borah\ATLAS-main`, branch `main`, remote [github.com/MISHHF93/ATLAS](https://github.com/MISHHF93/ATLAS). That repository is this product. The directory named in the 2026-10-19 notes, `C:\Users\borah\ATLAS`, is not on this machine. Other public projects that use the name ATLAS are different software.
>
> The desk is paper only. The book of record is the append-only paper ledger `default_workspace_paper_capital`. Checked live on 2026-10-28: ledger cash `$0.00`, no open positions, `deposits_loaded` false. An operator can record a paper deposit, a paper order, a paper close, and a paper withdrawal inside that book. Customer custody, deposit addresses, and live withdrawals are unimplemented. A software subscription is not a trading deposit.
>
> The research hand is visible and cannot buy or sell (`execution_permission: none`). Stored genome: `ridge|full|none|time|htf` from `niches_1793235961` on the official 4h book (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, prior-day-range reversal, variant `atr2_rr2_cf15`). It beat its take-all baseline and failed gate `evo8-strict-1` (minimum taken trades per fold 1 vs 20, DSR 0.368 vs 0.95, one-sided t p-value 0.183 over 15 trials). LightGBM and XGBoost on the same features scored worse on that full book. Niche selection abstained. `champion.json` is absent. No registry model is eligible. The price-action "break of range level reaches the swing level" claim remains unproven ([evidence](docs/spec/evidence/)).
>
> The full pytest count recorded on 2026-10-23 was **1447 passed, 9 skipped**. That full suite was not re-run. On 2026-10-28 the modules that skip without `xmlschema`, `lightgbm`, `mapie`, `mcp`, `xgboost`, or `exchange_calendars`, plus the realistic backtest, ran as **119 passed, 0 skipped**.

## Safety invariants

1. **The deterministic control plane is the final authority.** `ActionableControlPlaneEngine` (`src/atlas/control/engine.py`) and `TradingRuleBook` (`control/rules.py`) decide every order, and nothing bypasses them. AI and research code carry `execution_permission: "none"`. The research hand can show a stance and cannot submit an order. On a cash-tracked paper book, an operator ticket cannot exceed free cash.
2. **Paper only.** `config/founder/risk_policy.yaml` sets `mode.default: paper` and autonomy level 1. Live adapters are paper-guarded and off by default. Live money movement raises by design.
3. **One Safe stop** (`risk/safe_stop.py`) is shared by the control plane, the founder API and the setup autopilot.
   - Founder limits are 2% daily and 10% static drawdown. They can never be loosened intraday.
   - Resetting over HTTP is refused (403). A reset needs the owner CLI with step-up.
4. **Founder policy is sha256-pinned.** `risk_policy.yaml.sha256` pins the file, and the owner chose `max_holding_seconds: 86400` (1 day) on 2026-10-23. If the pin is missing or fails, entries are denied (fail closed).
5. **Calibrated or abstain.** `models/predict.predict()` returns a probability only through an in-scope calibrator. The EV gate (`models/opportunity.py`) then rejects any setup whose edge does not cover its cost.
6. **Causal data only.** A bar is used only after it closes and is provider-confirmed. Live and replay share the same `PriceActionEngine.update`, and parity tests guard this.
7. **No fabricated evidence.** Results live in `docs/spec/evidence/`, together with the scripts that reproduce them.

## Architecture (pipeline)

```
ATLAS feed (src/atlas/feeds: one PIT bar store; official keyless crypto from Binance, OKX, Kraken, Coinbase. Yahoo is unofficial and is not the evolution book. Keyed adapters stay off until env keys exist.)
        │  bar_confirmed only after bar_end; refuse dup/out-of-order
        ▼
features/price_action ── indicators (EMA/RSI/ATR/BB/bar-VWAP) · sessions (DST) · Zone lifecycle
        │                detectors: ORB→breakout→retest · dual Bollinger · wick reversal · prior-day range reversal
        │                ContextTracker (regime/vol/time/levels) ─► technique selector [experimental, not registered]
        ▼
candidates (proposals, execution_permission none)
        ▼
models/predict.predict()  ── no eligible registry model ⇒ abstain; research hand abstains (evo8 not passed)
        ▼
models/opportunity EV gate  (EV = pG − (1−p)L − C; break-even; fractional Kelly, research only)
        ▼
ActionableControlPlaneEngine + TradingRuleBook (founder / open-market / competition) + Safe stop
        ▼
PaperConnector / paper broker ── fills & exits via replay model conservative_ohlc_v1
        │
        ├─► hash-chained audit log (governance/audit)
        └─► shadow-week collector (models/shadow.py) ─► ModelRegistry.record_shadow_week

Replay (/api/quant/replay) and research evidence (research/setup_evidence.py: walk-forward, Platt, DSR/PBO)
reuse the same engine. The paper setup autopilot (autopilot/setups.py) drives this loop and needs owner approval to switch on.
```

Agent access: API keys that are hashed, scoped, revocable and rate-limited (`keys/api_keys.py`), and a localhost read-only MCP endpoint at `POST /api/mcp`. See [docs/api-and-mcp.md](docs/api-and-mcp.md).

## Quick start

Requirements: Python 3.11+ and Node.js 18+.

```bash
# backend deps (editable install with extras)
python -m venv .venv && . .venv/bin/activate        # Windows: .\.venv\Scripts\activate
pip install -e ".[dev,founder,ml,mcp]"
python -m pytest -q                                  # 2026-10-23 count was 1447 passed, 9 skipped (tests/conftest.py creates .test-runs/)

# frontend + backend on ONE port (Node spawns FastAPI over stdio; binds 127.0.0.1 only)
cd frontend && npm install
npm run dev                                          # http://localhost:3000
PORT=3100 npm run dev                                # choose a port
ATLAS_PYTHON=/path/to/python npm run dev             # choose the interpreter
npm run build && npm run start                       # production; rebuilds if the page manifest is stale
npm run typecheck && npm run test:routes
```

`ATLAS_PYTHON` is used first when set. Otherwise the server tries the repo's `.venv`, then a sibling `../.atlas-venv`, then `python3` or `python` on PATH. These env names are useful:

- `ATLAS_API_KEYS_PATH`
- `ATLAS_SETUP_AUTOPILOT_STREAMS` (default `SPY:60:us_equity_rth`)
- `ATLAS_SETUP_AUTOPILOT_INTERVAL_S`
- `ATLAS_STATE_DB`
- `ATLAS_AUDIT_DB`
- `ATLAS_SHADOW_PATH`

Owner and agent commands:

```bash
python -m atlas.keys.cli create --name claude-desktop --scope read --rate 60   # key printed once
atlas-owner setup-autopilot-approve <request_id>                               # passphrase + TOTP
python scripts/fetch_public_history.py && python scripts/run_setup_evidence.py # reproduce setup evidence (cache in var/)
python scripts/fetch_public_history.py --15m                                  # 15m cache -> var/evidence_cache_15m (Yahoo 60d, Binance 730d)
python scripts/run_selector_evidence.py var/evidence_cache_15m                 # reproduce selector evidence
```

## Page map (`frontend/src/components/shell/pagesMap.ts`)

There are six sections. Old URLs still open the same pages as aliases.

| Section | Page | Route | Aliases |
|---|---|---|---|
| Home | Overview | `/` | |
| Home | Action needed | `/inbox` | |
| Trade | Trading desk | `/trade` | `/workbench`, `/trade/cockpit`, `/market` |
| Trade | Listings (fixture catalog) | `/listings` | |
| Trade | Estimated depth (not an exchange book) | `/trade/depth-dom` | |
| Trade | Positions | `/trade/blotter` | `/control/dealing-desk` |
| Trade | Account risk | `/control` | `/control/risk-hud`, `/profile` |
| Money | Money | `/money` | |
| Money | Payments | `/payments` | |
| Money | Partner wallet | `/portal` | |
| Money | Tax | `/tax` | |
| Research | Chart read | `/research` | `/research/central-node`, `/research/microstructure`, `/research/drift-dashboard`, `/matrix` |
| Research | Price-action zones | `/research/price-action` | |
| Research | Walk-forward | `/research/walk-forward` | `/experiments` |
| Research | Training status | `/models` | `/research/registry` |
| Research | Prediction ledger | `/research/prediction-ledger` | |
| Research | Bar query | `/data` | `/data/lakehouse`, `/warehouse` |
| Research | Reserve sleeve | `/governance` | `/data/governance` |
| Compliance | Compliance overview | `/compliance` | |
| Compliance | Audit log | `/control/surveillance` | `/trade/journal` |
| Compliance | Identity checklist | `/control/proctoring` | |
| Settings | Rulebook | `/control/rulebook` | `/rules`, `/settings`, `/configurations` |
| Settings | Connectors | `/data/pipelines` | `/connectors`, `/integrations`, `/sync` |
| Settings | Capability map | `/data/features-100` | `/roadmap` |
| Settings | Specifications | `/docs` | |

API-only surfaces:

- `/api/quant/{zones,setups,analyze,replay}`
- `/api/quant/autopilot*`
- `/api/quant/shadow`
- `/api/mcp`
- `/api/founder/*`
- `/api/founder/data/*`

## Status at a glance

| Capability | Status | Evidence |
|---|---|---|
| Control plane, rulebooks, unified Safe stop | Implemented+tested | `control/`, `risk/safe_stop.py` |
| Price-action engine (zones, ORB-retest, dual Bollinger, wick) | Implemented+tested (synthetic fixtures) | `features/price_action/`, `tests/price_action/` |
| predict() contract, EV gate, replay harness | Implemented+tested | `models/predict.py`, `models/opportunity.py`, `price_action/replay.py` |
| Real-data setup evidence | Ran: **0 of 21 configs passed**, nothing registered | [price-action-setups-2026-10-23](docs/spec/evidence/price-action-setups-2026-10-23.md) |
| Prior-day range reversal detector | Implemented+tested, **not validated** (negative after costs) | `price_action/prior_day.py` |
| Technique selector | Experimental: **failed gates**, not registered | [technique-selector-2026-10-23](docs/spec/evidence/technique-selector-2026-10-23.md) |
| Range-break → swing hypothesis | **Unproven** | same evidence file |
| Paper setup autopilot (owner approval, Safe stop, 1-day hold) | Implemented+tested (paper; abstains with empty registry) | `autopilot/setups.py` |
| API keys and localhost MCP endpoint | Implemented+tested | `keys/api_keys.py`, `api/agent.py` |
| Shadow-week collector | Implemented+tested (no live weeks yet) | `models/shadow.py` |
| Economic event ranges | Blocked: interface only, no data feed | `price_action/events.py` |
| Curtain navigation, functional console UI, responsive grids | Implemented+tested (merged) | `frontend/src/components/shell/`, [docs/ux-audit.md](docs/ux-audit.md) |
| One authoritative feed and provider adapter library | Implemented+tested (paper; keyless providers live, keyed adapters fixture-tested) | `src/atlas/feeds/`, [docs/data-feeds.md](docs/data-feeds.md) |
| TradingView widgets, UDF and Lightweight Charts | Implemented+tested (merged; UDF reads the ATLAS feed, labelled legacy fallback) | `api/udf.py`, [docs/tradingview-integration.md](docs/tradingview-integration.md) |
| Safe stop release | CLI-only with owner step-up (`atlas-owner reset`); HTTP release returns 403 | `api/app.py`, `control/owner_cli.py` |
| Live trading and live money | Blocked by design | `risk_policy.yaml` |

The row-by-row matrix (A–Z subsystems, track rules, pages, SaaS verticals, order-flow models, domains and decision matrix, each with a status, evidence and a changelog) is the root workbook **`ATLAS Platform Master Roadmap & Technical Specifications (A-Z).xlsx`**, last verified 2026-10-23.

## Documentation

Start at **[docs/README.md](docs/README.md)**, which indexes every document. The key documents are:

- [docs/spec/master-wrapper-summary.md](docs/spec/master-wrapper-summary.md): the governing spec.
- [docs/spec/audit-and-gap.md](docs/spec/audit-and-gap.md): the audit and gap map.
- [docs/spec/price-action.md](docs/spec/price-action.md): the price-action spec, slices 1–5.
- [docs/spec/evidence/](docs/spec/evidence/): real-data results.
- [docs/api-and-mcp.md](docs/api-and-mcp.md): API keys, the autopilot routes and MCP.
- [docs/reshape-decisions.md](docs/reshape-decisions.md): IA decisions and the owner's max-holding decision.
- [docs/ux-audit.md](docs/ux-audit.md) and [docs/broken-code-audit.md](docs/broken-code-audit.md).
- [docs/lola-port-plan.md](docs/lola-port-plan.md): the founder capital track.

Ownership: the founder keeps 100% of the source code, strategy logic, model artifacts and signing keys. Infrastructure operators have no discretion over orders.
