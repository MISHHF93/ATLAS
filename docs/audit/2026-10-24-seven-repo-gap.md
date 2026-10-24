# Seven-repo gap audit (atlas-ext-1, 2026-10-24)

Reference repos: OpenBB, TradingView MCP, FinceptTerminal, multi-market analysis, TradingAgents, ai-hedge-fund, Alpaca MCP.
Statuses: **have** (was already in ATLAS), **built** (added on this branch), **partial**, **missing**, **blocked**.
All new code is research or paper only. No risk rule was changed. `config/founder/risk_policy.yaml` was not touched.

| # | Item (source repo) | Status | ATLAS location | Notes / plan |
|---|---|---|---|---|
| 1 | Options pricing, greeks, IV (OpenBB, Fincept) | built | `ext/options.py`, `/api/ext/options/greeks`, `/options/iv` | Black-Scholes with put-call parity; IV by bisection. |
| 2 | Live option chains (OpenBB) | blocked | `/api/ext/options/chain` returns unavailable | Needs a licensed chain provider. No keyless source is available. |
| 3 | VaR / ES, parametric + historical + component (Fincept, multi-market) | built | `ext/var.py`, `intel/portfolio.py`, `/api/ext/var` | Uses ATLAS feed bars only. Returns no_data when the feed is empty. |
| 4 | DCF FCFF/FCFE (Fincept, ai-hedge-fund) | built | `ext/dcf.py`, POST `/api/ext/dcf` | User-supplied inputs. Terminal-value share is reported. |
| 5 | SEC EDGAR fundamentals, point-in-time (OpenBB, ai-hedge-fund) | built | `ext/edgar.py`, `/api/ext/fundamentals` | companyfacts with a filed-date cutoff and a cache. Needs `ATLAS_SEC_USER_AGENT` in `.env`. Not configured on the box. |
| 6 | VWAP, volume profile, S/R, pivots/Fibonacci scan (TradingView MCP, multi-market) | built | `ext/pricevol.py`, `/vwap`, `/sr`, `/scan` | |
| 7 | Pine v5 export (TradingView MCP) | built | `ext/pine.py`, `/pine`, `/pine/{sid}` | Exports levels with ATLAS replay stats. It does not claim TradingView backtest results. |
| 8 | Conviction dossier 1–100 (multi-market) | built | `ext/dossier.py`, `/dossier` | Uses named deterministic rules, with entry/stop/target taken from levels. |
| 9 | Investor personas + PM (ai-hedge-fund) | built | `ext/personas.py`, `/personas` | Rule-based, not an LLM. Weight matrix is capped. |
| 10 | Analyst → debate → trader → risk → PM pipeline (TradingAgents) | built | `ext/agents.py`, `/pipeline` | Risk step = `ControlPlane.preview_order`. Never submits (`submitted: false`, `llm_used: false`). |
| 11 | News / sentiment analysts (TradingAgents) | blocked | the analyst reports `unavailable` | No keyless licensed news feed. Will not fabricate one. |
| 12 | Alpaca paper broker (Alpaca MCP) | built | `ext/alpaca_paper.py`, `/api/ext/alpaca/*` | Paper URL only; live endpoint/account refused; keys from `.env` only; every order goes through `submit_order` first. Not configured on the box. |
| 13 | Alerts Telegram/Discord/webhook (multi-market, Fincept) | built | `ext/alerts.py`, `/alerts/status`, `/alerts/preview` | Off by default (`ATLAS_ALERTS_ENABLED`). Never sends under tests. No channel is configured. |
| 14 | MCP tool server (TradingView MCP, Alpaca MCP) | built | `ext/mcp.py`, `scripts/atlas_mcp_stdio.py`, `/api/ext/mcp/*` | 11 read-only tools and no order tool. |
| 15 | Order preview without booking (Alpaca MCP) | built | `control/engine.py::preview_order` | Uses the same `_evaluate_request` as submit. A test asserts that the two agree. |
| 16 | Yield curve / FRED / macro (OpenBB, Fincept) | deferred | — | Owned by atlas-evo-5. Not built here. |
| 17 | Maritime / shipping data (Fincept) | blocked | — | No keyless source. |
| 18 | ML model training (ai-hedge-fund, Fincept) | out of scope | — | Excluded by the brief. |
| 19 | Backtest/replay, risk control plane, paper broker, feeds | have | `backtest/`, `control/`, `feeds/` | Already in ATLAS. |

UI: new tabs on existing hubs only. Research Lab gets Valuation, Dossier & agents and Options; Research gets Scan & Pine; Settings gets Broker & alerts.
