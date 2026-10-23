# Plan conformance: trading-bot-app vs the plan (2026-10-17)

Sources reread: `/workspace/trading-bot/` (README, BRD, TRD, COMPLIANCE, PLATFORMS, config, ui/index.html) and
`/workspace/trading-bot-review/` (review, hedge-fund-addendum, implementation-research, strategy-research-2, audit,
wallet-research, banking-standards), plus the owner's decisions listed below. Paths are relative to
`/workspace/trading-bot-app`. Tests: `tests/` = bot suite, `payments/tests/`, `console/tests/`, `common/tests/`.

Status key: **built** · **partial** (works, but a named piece is missing) · **missing** · **deviated** (intentionally
different, with the reason).

## Summary

| Status | Count |
|---|---|
| Built | 87 |
| Partial | 17 |
| Missing | 5 |
| Intentionally deviated | 13 |
| **Total requirements tracked** | **122** |

**Fixed in this pass:** single launcher `tradingbot-console up --demo` (core, then watchdog, then console; clean
shutdown even on a second Ctrl-C); five-section navigation with old URLs redirecting; Home "Action needed" inbox built from
one source that also drives the sidebar badges and is test-checked against every page; legacy "Fund & Investors" page
(a second, conflicting investor register) folded into Money › Investors; read-only MCP research tools `get_bars`,
`get_quote`, `compute_indicators` (US-06); trade-history CSV per broker and tax year (US-12); `/overview` and `/home` no
longer 404; end-to-end crawler (`console/tools/crawl.mjs`); core runner moved slow jobs (Saturday retrain, drill,
pipeline) to a worker thread after the integrated run showed a retrain starving the heartbeat and the external watchdog
halting trading (`src/tradingbot/ops/runner.py`, `tests/test_m6_ops.py::test_slow_job_never_starves_the_core_heartbeat`).

**Key deviations:** live trading impossible in this build; autonomy locked at L1 (paper); money movement is manual
(the app prepares, the owner sends it in the provider's UI); SQLite instead of Postgres/Redis; stdlib + vanilla JS
instead of FastAPI/React; local passphrase + TOTP instead of OIDC/OAuth; no email/push; derivatives locked; no network
code in wallet/payments.

## Owner decisions

| # | Decision | Status | Where / test |
|---|---|---|---|
| D1 | One repo | built | bot `src/`, `payments/`, `console/`, `common/` in one git repo; one `pip install -e` chain (README "Run") |
| D2 | Open-ended profit, fixed loss limits (2% daily kill switch) | built | `config/risk_policy.yaml` `loss_limits.daily_pct: 2.0`; `src/tradingbot/risk/engine.py` daily latch + halt · `tests/test_risk_engine.py`, `tests/test_killswitch_watchdog.py`. No profit target or take-profit cap anywhere in the policy |
| D3 | Fully autonomous goal, earned autonomy locked at L1 in this build | deviated (by decision) | schema forces `autonomy.level == 1` (`src/tradingbot/config/schemas.py`); ladder evaluator reports readiness but cannot promote (`src/tradingbot/risk/ladder.py`, `risk/autonomy.py`) · `tests/test_mm_ladder_dashboard.py::test_evaluator_cannot_change_autonomy`, `tests/test_safety.py` |
| D4 | Manual money movement: pipeline prepares, owner confirms | built | payments: request → step-up approval → instruction sheet → owner marks executed after sending in the provider UI; no execute route (`payments/src/tradingbot_payments/manual.py`, `treasury.py`) · `payments/tests/test_manual.py`, `console/tests/test_console_api.py` (no execute route, step-up) |
| D5 | One-page overview combining trading and payments as Home | built | console Home `console/src/tradingbot_console/static/js/pages/overview.js` + `/api/inbox` (`inbox.py`) · `console/tests/test_wallet_api.py::test_home_inbox_matches_every_page` |
| D6 | Full app with a payments page and a profile | built | `/payments`, `/profile` (`pages/payments.js`, `pages/profile.js`) · `console/tests/test_console_api.py` |
| D7 | Wallet = read-only view of partner-held balances, incl. investor money | built | `payments/src/tradingbot_payments/wallet/` (partners hold money; app never holds it) + `/wallet` and `/portal` · `payments/tests/test_wallet.py`, `console/tests/test_wallet_api.py` |

## BRD user stories

| ID | Requirement | Status | Where / test |
|---|---|---|---|
| US-01 | Paper by default; live needs flag + confirm + re-auth | deviated | live is impossible: `src/tradingbot/safety.py` `BUILD_ALLOWS_LIVE=False`, `assert_paper_only()` everywhere · `tests/test_safety.py`. Reason: owner rule "LIVE must be impossible to enable in this build" |
| US-02 | Kill switch: cancel all ≤2 s, optional flatten, block, log, alert | partial | `risk/killswitch.py` persisted, cancel-all, owner flatten; top-bar button on every page; CLI; MCP engage-only · `tests/test_killswitch_watchdog.py`, `console/tests`. Alert = audit + console only (no email/push) |
| US-03 | Daily loss limit auto-halts, cancels, alerts | built | `risk/engine.py` daily latch, `risk/anomaly.py` · `tests/test_risk_engine.py` |
| US-04 | Max position % and $ | built | `risk/engine.py` position %, notional, issuer netting · `tests/test_risk_engine.py` |
| US-05 | Approval mode, TTL, approve/reject on dashboard or MCP | built | `risk/approvals.py` (TTL 120 s, persisted); console Trading › Approvals with step-up; MCP can only propose · `tests/test_paper_and_mcp.py`, `console/tests/test_console_api.py` |
| US-06 | MCP tools for quotes, bars, news, indicators | partial (fixed this pass) | `src/tradingbot/mcp_server/research.py` + `server.py` (`get_bars`, `get_quote`, `compute_indicators`, offline store) · `tests/test_mcp_research.py`. News over MCP not exposed (news screener exists internally, untrusted text) |
| US-07 | Propose order via MCP → risk engine → pending_approval | built | `mcp_server/service.py::propose_order` · `tests/test_paper_and_mcp.py` |
| US-08 | Backtest with costs, Sharpe/MDD/win/PF, benchmark, walk-forward | built | `src/tradingbot/backtest/`, `ml/validation*` · `tests/test_backtest.py`, `tests/test_ri_validation.py` |
| US-09 | One dashboard: equity, P&L, positions, orders, ≤5 s refresh | built | console Home + Trading (auto-refresh), one-page `tradingbot-dashboard` · `tests/test_dashboard.py`, `console/tests` |
| US-10 | Full append-only audit log | built | `src/tradingbot/audit/` hash chain; payments chain; console Compliance & reports › Audit log · `tests/test_audit_logging.py` |
| US-11 | Alerts by email/push within 30 s | deviated | no outbound network in this build; alerts are audit events, Home "Action needed" items and the daily summary file. Reason: offline/no-secrets rule |
| US-12 | Trade history CSV per broker and tax year | built (fixed this pass) | `console/src/tradingbot_console/trading_api.py::trades_csv`, Trading › Orders & fills download buttons · `console/tests/test_console_api.py::test_trade_history_export_per_broker_and_year` |
| US-13 | ML signals as flagged, paper-only experiments vs baseline | built | `src/tradingbot/ml/` registry, shadow mode, gates · `tests/test_m5_ml.py` |
| US-14 | Set limits once, run autonomously (rung 3) | deviated | locked at L1 (D3); signed set-once policy is built (`config/signing.py`) |
| US-15 | Cap the bot at X% of the account | built | `risk/engine.py` 20% cap; `sleeves/rebalancer.py` pro-rata sells · `tests/test_m4_rebalancer.py` |
| US-16 | Sleeves with cost-aware auto-rebalance | built | `sleeves/rebalancer.py` 60/30/10 · `tests/test_m4_rebalancer.py` |
| US-17 | Global markets around the clock; open venues only; low-liquidity size | built | `data/calendars.py`, `execution/scheduling.py` (phases, multipliers, weekend crypto-only) · `tests/test_m6_ops.py` |
| US-18 | Autonomy ladder shown; promotion needs evidence + sign-off; auto-demote | partial | ladder evaluator + Strategies › gates view (`risk/ladder.py`); promotion disabled by D3 |
| US-19 | Halt on failure; missed heartbeat → halt ≤15 s | built | `risk/watchdog.py`, `risk/watchdog_proc.py` (separate process, both directions fail closed); launcher starts it · `tests/test_killswitch_watchdog.py`, `console/tests/test_launcher.py` |
| US-20 | Derivatives locked, UI shows "Phase 5, locked" | built | schema + risk engine reject options/futures (`config/schemas.py`, `risk/engine.py`); Risk page shows locked · `tests/test_config.py`, `tests/test_risk_engine.py` |
| US-21 | Defined-risk options only | deviated | no options code at all while locked (Phase 5) |
| US-22 | Micro futures with a contract cap | deviated | as US-21 |
| US-23 | Expiry auto-close/roll with alerts | deviated | as US-21 |
| US-24 | Greeks and margin at a glance | deviated | as US-21 |

## TRD

| § | Requirement | Status | Where / test |
|---|---|---|---|
| 2.1 | Data ingestion: normalised bars, PIT, quality checks; news untrusted | partial | `data/` Massive/Finnhub adapters off by default, PIT store, stale-quote checks, `screener/` treats news as untrusted · `tests/test_data_layer.py`, `tests/test_m5_screener_autonomy.py`. No WebSocket streaming (offline) |
| 2.2 | Strategy plugins, deterministic | built | `backtest/strategies.py`, `strategies2/`, `pipeline_full.py` · `tests/test_strategies2.py`, leakage tests |
| 2.3 | Pre-trade checks (mode, kill, size, exposure, daily loss, orders/min, collar, allow-list, dup, session, approval) | built | `risk/engine.py`, `risk/ratelimit.py` (shared across processes) · `tests/test_risk_engine.py`, `tests/test_m2_extras.py` |
| 2.3 | PDT guard | deviated | cash accounts only, no margin (spot-only flags enforced), so PDT cannot apply |
| 2.3 | Post-trade recon every 60 s, halt on mismatch | built | `risk/reconcile.py`, runner job · `tests/test_killswitch_watchdog.py` |
| 2.4 | Broker adapters (Alpaca, IBKR, Coinbase, Robinhood), retries, idempotency, paper simulator | partial | Alpaca + IBKR paper adapters (injected transport, never connected), router, paper simulator with slippage/commission/T+1 · `tests/test_m3_adapters.py`, `tests/test_ri_execution.py`. Coinbase/Robinhood/Kraken use the internal simulator |
| 2.5 | MCP server, every order through risk, scopes, audit | partial | `mcp_server/` scoped hashed tokens (read/propose/kill), audit per call · `tests/test_paper_and_mcp.py`. OAuth 2.1 transport auth not built (stdio only) |
| 4 | MCP tool catalog | partial | status, positions, limits, approvals, propose, kill, bars, quote, indicators. Not built: snapshot, clock, news, fundamentals, calendar, scanner, backtest.run, paper.reset |
| 2.6 | Backtester sharing strategy + risk code, walk-forward, Monte Carlo | built | `backtest/engine.py` reuses `RiskEngine`; purged CV, deflated Sharpe, PBO · `tests/test_backtest.py`, `tests/test_ri_validation.py` |
| 2.7 | Dashboard: overview, positions, orders, strategies, approvals, backtests, audit, health; kill switch always visible | built | console (5 sections) + `tradingbot-dashboard` one-pager · `console/tests`, `tests/test_dashboard.py` |
| 2.7 | React + TS behind OIDC/MFA | deviated | vanilla ES modules, stdlib server on 127.0.0.1, passphrase + TOTP step-up. Reason: no CDN/framework, offline, loopback only |
| 2.8 | Postgres/Timescale, Redis, object storage, vault | deviated | SQLite (0600) + Parquet; vault = local encrypted file for wallet PII only. Reason: single-box paper build |
| 2.8 | Retention ≥7 years for audit/trade records | partial | append-only hash-chained logs, retention schedule in `compliance/privacy.py`; no WORM copy |
| 2.9 | Structured logs, metrics, traces | partial | redacted JSON logs (`logging_setup.py`), health check; no Prometheus/OTel |
| 6.2 | Fail-safe on feed/DB loss; watchdog 3 × 5 s | built | stale quote halt, unreadable kill-switch store = engaged, external watchdog · `tests/test_killswitch_watchdog.py` |
| 7 | Secrets never in git; step-up for privileged actions; AI can't approve its own orders | built | `.gitignore` (.env, var/), placeholder-token refusal, `source=ai` forced · `tests/test_paper_and_mcp.py::test_propose_cannot_spoof_source` |
| 7 | Supply chain: SAST, Dependabot, signed images | missing | no CI in this offline repo |
| 8 | Unit/property tests, chaos, safety drills | built | Hypothesis property tests, kill-switch drill (`tradingbot-drill`, Sat 11:00 job) · `tests/test_m6_ops.py` |
| 8 | Coverage ≥90% on risk/OMS | missing | coverage not measured in this pass |
| 9 | Docker Compose dev environment | partial | `Dockerfile`, `docker-compose.yml` (no Docker daemon in this box to build) |
| 10 | Alerts table + end-of-day report | partial | thresholds feed halts and Home inbox; daily summary file `tradingbot-summary`; no delivery channel (US-11) |
| 11.2 | Policy store signed, AI read-only | built | `config/signing.py` (sha256 pin / ed25519) · `tests/test_config.py` |
| 11.2 | Session calendar service, fail closed on disagreement | built | `data/calendars.py`, `execution/scheduling.py` · `tests/test_m6_ops.py` |
| 11.2 | Follow-the-sun scheduler, weekend crypto-only | built | `execution/scheduling.py`, dashboard market strip · `tests/test_m6_ops.py` |
| 11.2 | Portfolio layer 60/30/10, drift band, cost check | built | `sleeves/rebalancer.py` · `tests/test_m4_rebalancer.py` |
| 11.2 | Strategy allocator (5–40% per strategy, Δ≤10 pp/week, auto-pause) | partial | name-level allocator (inverse-vol/HRP/HERC chosen OOS) in `ml/stack2.py`; per-strategy weight bounds with weekly change cap not built |
| 11.2 | Extended risk: cap, weekly loss, sleeves, FX exposure, ISIN netting, low-liquidity mult | built | `risk/engine.py`, `risk/fx.py` · `tests/test_risk_engine.py`, `tests/test_m2_extras.py` |
| 11.2 | Multi-broker router, failover for flattening only | built | `execution/adapters/router.py` · `tests/test_m3_adapters.py` |
| 11.2 | FX service: CAD base, multi-currency cash, PIT FX | built | `risk/fx.py`, `risk/fx_hist.py`, Bank of Canada fetcher (disabled) · `tests/test_tax_wiring.py` |
| 11.2 | Autonomy controller state machine | deviated | evaluator only; level fixed at 1 (D3) |
| 11.2 | Watchdog as independent process | built | `tradingbot-watchdog`; started by the launcher · `console/tests/test_launcher.py` |
| 11.2 | Reporting: daily summary 17:30 ET | built | `ops/summary.py`, scheduler · `tests/test_m6_ops.py`; weekly/monthly PDFs missing |
| 11.4 | Session/allocation/autonomy/watchdog MCP tools | missing | the data is on the console and dashboard; MCP exposes only the core set (see §4 row) |
| 11.5 | UTC storage, Decimal money, ISIN/MIC, settlement T+1/T+2 | built | payments use Decimal; tax uses Decimal; bot uses floats for paper P&L with CAD conversion · `tests/test_tax.py`, `payments/tests/test_treasury.py` |
| 11.6 | Anomaly auto-halts (loss, P&L jump, fill deviation, reject spike, stale, rate, heartbeat) | built | `risk/anomaly.py`, `ml/` isolation-forest guard · `tests/test_mm_cost_anomaly.py` |
| 13 | Six-stage decision pipeline, ML filter/size only, LLM veto/downsize only, fallback rules-only at half size | built | `pipeline_full.py`, `screener/`, `ml/` · `tests/test_gc_pipeline.py`, `tests/test_m5_screener_autonomy.py` |
| 13.7 | "Why this trade" explanation | built | decision trail + console Trading › Why each trade drawer · `tests/test_gc_pipeline.py`, `console/tests` |
| 13.5 | Model registry, champion/challenger, rollback | built | `ml/registry.py`, `ml/shadow.py` · `tests/test_m5_ml.py`, `tests/test_gc_registry_kinds.py` |
| 13.6 | Drift monitoring (PSI) auto-demote | built | `ml/` PSI drift job · `tests/test_mm_ladder_dashboard.py` |
| 13.10 | Prompt-injection test cases for the screener | built | `tests/test_m5_screener_autonomy.py` (embedded-instruction headlines → veto/none only) |
| 14.1 | Pydantic validation, cross-file checks, signature fail closed | built | `config/loader.py`, `validate.py` · `tests/test_config.py` |
| 14.1 | Hot reload of tightening changes | partial | loosening blocked intraday; tightening applies at next load, not live-reloaded |
| 14.2 | Vault secrets, rotation, secret scanning | partial | placeholders only, `.env` gitignored, wallet vault key rotation (`tradingbot-payments vault-rotate`); no CI secret scanning |

## COMPLIANCE / PLATFORMS / hedge-fund addendum

| Requirement | Status | Where / test |
|---|---|---|
| Own money only; fund needs registration before outside money | built | entity features labelled; investor wallet is SIMULATION with partner-held money (`payments/.../wallet/`) |
| Venue eligibility, registration staleness >90 d fails closed | built | `config/venues.yaml`, `src/tradingbot/config/venues.py` · `tests/test_venues.py` |
| Kraken Canada blocklist, Coinbase interim-relief warning, excluded venues | built | `config/blocklists/kraken_ca.yaml` · `tests/test_venues.py` |
| Data licences pro/non-pro per entity | built | `config/venues.yaml` licences · `tests/test_venues.py` |
| Per-taxpayer ACB, superficial loss ±30 d, CAD FX per fill with source | built | `src/tradingbot/tax/` · `tests/test_tax.py`, `tests/test_tax_wiring.py` |
| Entity separation, fund allocation + fairness, NAV per unit | built | `src/tradingbot/entity/` · `tests/test_entity.py` |
| Business-vs-capital evidence, T1135 tracker | built | `tax/` exports on Compliance & reports › Tax · `console/tests/test_console_api.py::test_downloads_have_content_disposition` |
| Crypto events (swaps, staking, wallet transfers) | partial | crypto spot fills tracked in ACB; staking/transfer linking not built |
| Immutable trail order → signal → decision → fill, T5008/Schedule 3 exports | built | audit chain + decision trail; `tax/` exports |
| Withholding tax per dividend | missing | no dividend events in the paper simulator |
| ISO 27001/SOC 2/ISO 42001 alignment notes | partial | controls matrix in docs (banking build), model cards; no certification (out of scope) |

## Wallet research and banking standards

| Requirement | Status | Where / test |
|---|---|---|
| App never holds money; partners hold it; read-only wallet view | built | `wallet/partners.py`, `wallet/service.py` · `payments/tests/test_wallet.py` |
| Onboarding decisions recorded from dealer/administrator (KYC, eligibility, suitability, sanctions/PEP, BO) | built | `wallet/service.py` `DECISION_KINDS` · `payments/tests/test_wallet.py` |
| Subscription instructions to the fund's trust account with reference | built | `/portal` subscribe instructions · `console/tests/test_wallet_api.py::test_investor_subscription_instructions` |
| Redemption request with notice/gates/lockups, investor step-up, forwarded to administrator | built | `wallet/service.py`, portal · `console/tests/test_wallet_api.py::test_investor_redemption_requires_investor_stepup` |
| Payouts only to the verified own-name account; two-person approval | built | `wallet/service.py` · `console/tests/test_wallet_api.py::test_two_person_payout_approval` |
| Change-bank-account workflow with cooling-off | built | `wallet/service.py` bank verification + cooling-off |
| Three-way reconciliation with break alerts | built | `wallet/recon.py`, Money › Investors › Balance checks · `console/tests/test_wallet_api.py::test_recon_breaks_report` |
| Secure document exchange, communications archive | partial | statements (PDF/CSV) and portal documents list; no free-form messaging archive |
| Banking calendars, bank IDs, IBAN/BIC/ABA, PAN refusal | built | `banking/calendars.py`, `banking/bankids.py` · `payments/tests/test_banking_calendar_ids.py` |
| ISO 20022 camt.053/054 parse, pain.001 generate, pain.002 parse | built | `banking/iso20022/` · `payments/tests/test_iso20022.py` |
| CPA-005 SIM file writer/validator, never transmitted | built | `banking/cpa005.py` · `payments/tests/test_cpa005_vault.py` |
| Sanctions screening from local lists, two-person disposition, daily rescreen | built | `compliance/screening.py`, `lists.py`, `matching.py` · `payments/tests/test_sanctions.py` |
| FINTRAC records (receipts, EFTR/LCTR candidates, LPPR draft, travel rule), nothing filed | built | `compliance/fintrac.py` · `payments/tests/test_fintrac.py` |
| Structured addresses, name-match (match/close/no), consent ledger | built | `banking/addresses.py`, `wallet/partners.py`, `compliance/privacy.py` · `payments/tests/test_addresses_privacy.py` |
| Privacy: retention, legal hold, access requests, incidents, key rotation | built | `compliance/privacy.py`, `wallet/vault.py` · `payments/tests/test_addresses_privacy.py`, `test_cpa005_vault.py` |
| Live connectivity to banks/Interac/Plaid/sanctions URLs | deviated | out of scope by the plan itself ("simulation-safe, offline, no network"); `tools/fetch_sanctions_lists.py` is a manual, separate helper |

## Review M0–M7 and research docs

| Item | Status | Where / test |
|---|---|---|
| M0 foundations: config schema, audit, fail closed | built | `config/`, `audit/` · `tests/test_config.py` |
| M1 data + backtester + leakage test | built | `data/`, `backtest/` · `tests/test_backtest.py` |
| M2 risk engine + safety | built | `risk/` · `tests/test_risk_engine.py`, `tests/test_killswitch_watchdog.py` |
| M3 paper execution + MCP + approvals | built | `execution/`, `mcp_server/` · `tests/test_m3_*.py`, `tests/test_paper_and_mcp.py` |
| M4 sleeves + rebalancing | built | `sleeves/` · `tests/test_m4_rebalancer.py` |
| M5 ML + LLM layers | built | `ml/`, `screener/` · `tests/test_m5_*.py` |
| M6 dashboard + ops (drill, daily summary) | built | `ops/`, console, dashboard · `tests/test_m6_ops.py` |
| M7 60-day paper soak | missing | needs calendar time and a running core; the launcher makes this a single command |
| Review open questions §2 (Alpaca live, Kraken UI, sleeves, limits, LLM timeout, L1 demotion, live toggle) | built | resolved in config/schemas ("Config fixes vs the specs" in README); no live toggle exists |
| implementation-research tiers 1–5 (purged CV, DSR/PBO, meta-labels, HRP, conformal sizing, execution params, drift) | built | `ml/`, `portfolio/` · `tests/test_ri_*.py` |
| strategy-research-2 return sources | built | `strategies2/` · `tests/test_strategies2.py` |
| audit.md findings incl. follow-ups | built | see audit.md "Follow-up"; regression tests in `tests/test_audit_fixes.py`, `tests/test_remaining_audit.py`, `payments/tests/test_audit_fixes.py` |

## Integration and UX (this request)

| Requirement | Status | Where / test |
|---|---|---|
| One install, one config, one launcher (console + core + watchdog, demo) | built | `tradingbot-console up --demo` (`console/src/tradingbot_console/cli.py`) · `console/tests/test_launcher.py` |
| Core keeps beating during long jobs; fails closed if the safety step is blocked | built (fixed this pass) | `src/tradingbot/ops/runner.py::run_forever` · `tests/test_m6_ops.py` (2 tests) |
| Crawl every route: no 404/500, no JS errors | built | `console/tools/crawl.mjs` (46 pages, 714 button clicks, 8 old URLs, 0 issues on the final run) + `console/tests/test_wallet_api.py::test_every_nav_route_and_old_url_is_served` |
| Home pulls consistent numbers from trading, payments, wallet, compliance | built | `/api/inbox` single source · `console/tests/test_wallet_api.py::test_home_inbox_matches_every_page` |
| About 5 sections, progressive disclosure, plain labels, one primary action, fewer badges | built | `static/js/app.js` SECTIONS; "More" menus and "More details" drawers |
| Action-needed inbox on Home | built | `inbox.py`, `pages/overview.js` |
| Keyboard, mobile, light/dark, accessible | built | `g`+h/t/m/c/s, `?`, Shift+K; off-canvas nav < 900 px; theme toggle; ARIA landmarks/tabs |
| Safety features visible, behaviour unchanged (step-up, two-person, kill switch) | built | kill switch in top bar on every page; payments kill switch on Payments; step-up/two-person routes unchanged (all console tests) |
| Old URLs redirect | built | `ALIASES` in `app.js`; `web.py` serves them |

## Remaining gaps (not feasible offline or out of scope)
1. Live brokers, OAuth/OIDC, email/push alerts, Postgres/Redis, WORM storage, CI (SAST, secret scanning, coverage), Docker build: need network, accounts or infrastructure.
2. Missing MCP catalog tools (snapshot, clock, news, fundamentals, calendar, scanner, backtest.run, paper.reset, TRD §11.4 and §13.9 tools).
3. Per-strategy allocator with weight bounds and a weekly change cap; weekly/monthly PDF reports; crypto staking/transfer events; dividend withholding.
4. Derivatives (US-21..24) stay locked until Phase 5; autonomy above L1 stays locked by decision.
5. M7: the 60-trading-day paper soak.
