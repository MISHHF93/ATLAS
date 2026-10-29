# Lola → ATLAS port plan

Branch `lola-port` (from local `main` @ 0956506). Source: the Lola trading platform (`trading-bot-app`, read-only).
Lola features are placed in ATLAS's own packages. There is no copied subfolder.
Everything stays **paper/simulation only**. Live trading is locked: Lola's `LIVE_ENABLED=false` and autonomy level 1 are kept.
Every AI/assistant/MCP output carries `execution_permission: "none"`.

## Safety and risk parity (priority 1)

| Lola feature | ATLAS location | Reused / added |
|---|---|---|
| RiskEngine, OrderIntent, RiskDecision, PortfolioState | `atlas.risk.engine`, `atlas.risk.models` (exported from `atlas.risk`) | Added. Sits beside ATLAS `risk` drawdown/heat/VaR modules, which are unchanged |
| 2% daily-loss Safe stop (owner policy) | `config/founder/risk_policy.yaml` (sha256-pinned, verbatim) + `atlas.control.founder_track` → `ActionableControlPlaneEngine.founder_rulebook` | Added `founder_capital` rulebook. ATLAS `TradingRuleBook` reused |
| Kill switch (persisted, fail-closed) | `atlas.risk.killswitch` | Added; see conflicts |
| Separate watchdog / heartbeat process | `atlas.risk.watchdog`, `atlas.risk.watchdog_proc` (`atlas-watchdog`) | Added |
| Approval queue + TTL + step-up | `atlas.risk.approvals`, `atlas.risk.stepup`, `atlas.control.owner_cli` (`atlas-owner`) | Added |
| AI may only shrink or veto | `atlas.risk.sizing`, `atlas.ai.assistant`, `atlas.mcp.trading` | Added. Matches ATLAS's existing `execution_permission: none` contract |
| Paper execution, adapters, scheduling | `atlas.execution.paper`, `atlas.execution.adapters`, `atlas.execution.scheduling` | Added. ATLAS `ControlPlaneExecutionGateway` stays the only order path in the API |
| Signed config, loader, schemas | `atlas.control.policy` (`atlas-validate`, `atlas-sign-policy`) | Added |
| Audit hash chain, entity, integrity | `atlas.governance.audit`, `atlas.governance.entity`, `atlas.governance.integrity` | Added under ATLAS governance |

### Founder capital track
- **Default for the founder's own capital: 2% daily loss** → Safe stop. Weekly loss is 4% and max drawdown is 10% (paper profile).
- The values are read from the signed founder policy.
- `build_founder_rulebook()` clamps them, so the founder track can only be *tighter* than 2% / 10%.
- If the policy is missing or fails its pin, it fails closed to the same 2% defaults.
- The **prop-competition rulebook keeps its configurable 4%** (`comp_rulebook`), because it mirrors published prop-firm rules. Open-market stays at 3%.
- `/api/control/rulebooks` now lists all three: `competition`, `open_market` and `founder_capital`.

## Canada: venues, broker restrictions, tax (priority 2)

| Lola | ATLAS |
|---|---|
| `venues.yaml` registration checks (CIRO / OSC / CSA), stale verification ⇒ fail closed, Alpaca paper-only for Canadians, crypto spot-only dealers, blocklists | `atlas.control.policy.venues`, `config/founder/venues.yaml`, `config/founder/blocklists/`, API `GET /api/founder/venues` |
| ACB, superficial loss guard, BoC FX (+ fetcher), T5008 / T1135 / Schedule 3 | `atlas.tax.*`, `config/founder/tax.yaml`, API `GET /api/founder/tax`, page `/tax` |
| Toronto time / TSX calendars | `atlas.ops.timez`, `atlas.marketdata.pit` (exchange_calendars) |

## Payments, investor wallet, compliance as the 8 non-custodial ledgers (priority 3)

`atlas.governance.LEDGER_IMPLEMENTATIONS` maps each entry of the existing `EIGHT_NON_CUSTODIAL_LEDGERS` to its module and page. The mapping is served by `GET /api/founder/ledgers`.

| ATLAS ledger | Implementation |
|---|---|
| 1 software subscription | `atlas.ledgers.ledger` (double-entry) |
| 2 broker account | `atlas.execution.adapters` (read-only, paper) |
| 3 exchange account | `atlas.execution.adapters` (Canadian-registered spot dealers) |
| 4 user external wallet | `atlas.ledgers.wallet` (investor wallet, no keys held) |
| 5 custodian (future only) | `atlas.ledgers.fund` |
| 6 prop-firm evaluation rules | `atlas.control.rules` (existing) |
| 7 founder treasury | `atlas.ledgers.treasury`, `atlas.ledgers.manual`, `atlas.ledgers.banking` (sandbox rails, two-person + step-up) |
| 8 double-entry customer ledger | `atlas.ledgers.db`, `atlas.ledgers.recon` |

- Trading reads payments only through `atlas.ledgers.readonly.BalanceView`, which opens SQLite in `mode=ro`.
- Compliance lives in `atlas.compliance`:
  - FINTRAC records (simulation only; nothing is filed)
  - SEMA / UN / OFAC sanctions screening, refreshed with `tools/fetch_sanctions_lists.py`
  - PIPEDA retention and legal hold

## UI (priority 4), in the ATLAS Next.js frontend

- New pages, registered in `pagesMap.ts` under a new **Money** group:
  - `/money`
  - `/payments`
  - `/portal` (investor portal)
  - `/tax`
  - `/compliance`
  - `/inbox` (Action needed; Desk group)
- Shared component: `src/components/founder/FounderPanel.tsx`. It uses ATLAS CSS variables and has the **SafeStopButton** in every founder page header.
- The Safe stop button can only *engage*. Reset returns 403 over HTTP and requires `atlas-owner` with step-up.
- `npm run test:routes` passes (3/3).

## ML extras and MCP (priority 5)

| Lola | ATLAS |
|---|---|
| HMM regime, HAR-RV / GARCH, conformal sizing, meta-labeling, registry, retrain | `atlas.models.quant` (`atlas-ml`) |
| CPCV / PBO / deflated Sharpe, walk-forward backtest | `atlas.research.backtest` (`atlas-backtest`), `atlas.strategies.sleeve_strategies` |
| Screener | `atlas.research.screener` |
| Portfolio construction, sleeves | `atlas.portfolio.construction`, `atlas.portfolio.sleeves` |
| MCP trading tools (read / propose only) | `atlas.mcp.trading` (`atlas-mcp`), beside ATLAS's read-only `atlas.mcp.server` |
| Ops: runner, sim, health, drill, summary, pipelines, dashboard | `atlas.ops.*` |
| Autopilot | `atlas.autopilot` |
| Owner console (stdlib HTTP, sessions, CSRF, step-up) | `atlas.console` (`atlas-console`), API-only |

## Conflicts and decisions

1. **4% prop daily loss vs 2% founder daily loss.** Both are kept. Prop stays configurable at 4% in `comp_rulebook`. The founder track defaults to 2%, cannot be loosened past it, and fails closed to 2%.
2. **TradingRuleBook.track literal.** It is `competition | open_market` in about 40 places. The founder rulebook is `track="open_market"` with its own `rulebook_id` (`founder-capital-2026-q4:v1`), so the literal was not widened.
3. **Two kill switches.** ATLAS `control_engine.kill_switch_engaged` (in-process, prop desk) and Lola `atlas.risk.killswitch.KillSwitch` (persisted, shared with the watchdog) both remain. The founder API uses the persisted one. Unifying them is left as a follow-up.
4. **Model registry.** Lola's registry in `atlas.models.quant` coexists with ATLAS `model_store` / `trial_log` / `uncertainty_calibration`. Nothing was merged, so ATLAS model artefacts are unaffected.
5. **Lola console SPA not ported.** The UI was rebuilt as ATLAS Next.js pages. `atlas.console` stays loopback-only and serves a local shell (security headers, known routes, no remote assets) so the old SPA tests run against that shell.
6. **Env prefix.** `TRADINGBOT_*` → `ATLAS_*`, `tradingbot-*` CLIs → `atlas-*`, and `tradingbot://` → `atlas://`. Lola config defaults `config` → `config/founder`.
7. **Docker packaging is paper-only.** `Dockerfile` and `docker-compose.yml` run offline, as non-root, with no baked-in secrets. The two static Docker tests check those files. No image is built in the test run.
8. **Pre-existing failures.** 8 ATLAS tests fail on `main` because `estimate_kyles_lambda` is undefined in `marketdata/live_stream.py`. They were left as is (not part of this port).
9. **Two dashboards.** Lola's stdlib dashboard is kept as `atlas.ops.dashboard` because its tests depend on it. The ATLAS frontend is the primary UI.

## How to run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e ".[dev,founder,ml,mcp]"
mkdir -p .test-runs && pytest -q
atlas-validate                  # verify signed founder policy
uvicorn atlas.api.app:app --port 8000      # /api/founder/* + existing ATLAS API
atlas-watchdog &                # separate heartbeat process (set ATLAS_STATE_DB)
cd frontend && npm install && npm run dev  # /money /payments /tax /compliance /portal /inbox
```

## Left to do
- Unify the two kill switches behind one control-plane flag.
- Wire live founder P&L into the `founder_capital` rulebook HUD (`get_remaining_room_hud` currently covers competition / open_market).
- Richer frontend views (tables and forms) for payments and wallet. Writes intentionally stay in the CLIs with step-up.
- Fix the 8 pre-existing `estimate_kyles_lambda` failures on `main`.
