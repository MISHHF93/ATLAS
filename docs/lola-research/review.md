# Trading Bot Planning Review (v0.4 docs)

## 1. My understanding
- Personal-money trading bot for a Toronto/Ontario owner, exposed to Grok Bot as an **MCP server**, plus a minimal dashboard (`ui/index.html`, static mockup). Base currency CAD.
- Bot uses at most **20%** of total account equity (hard ceiling 30%; profits don't raise it). Sleeves: **core 60% / active 30% / high-risk 10%**. Derivatives are locked at 0% (Phase 5).
- Pipeline: rules generate candidates → **LightGBM** scores P(hit)/E[r] (min 0.55, must beat costs) → **LLM news screener** can only veto or downsize → **vol-target sizing** with a ¼-Kelly cap → **risk engine** is the only path to a broker → weekly **champion/challenger** retrain (4 shadow weeks minimum).
- Hard limits: 2% daily / 4% weekly loss, 10% max drawdown, 10% max position, no leverage, FX/sector/currency caps, price collars, order-rate limits.
- Safety: a kill switch on 5 channels; a fail-closed watchdog (5 s heartbeat, halt after 3 missed beats); anomaly halts; reconciliation every 60 s. AI can't approve orders or change policy.
- Earned-autonomy ladder from L1 paper to L4 scale, with metric gates and auto-demotion. Live needs `LIVE_ENABLED`, L≥2, dashboard confirmation and step-up auth.
- Brokers: Alpaca (paper, US), IBKR (paper now, live later, global plus FX), Coinbase (crypto; Kraken disabled until CSA status is confirmed). Data: Massive/Polygon, Finnhub, plus broker feeds.
- Global "follow the sun" schedule; weekends are crypto-only and the learning loop runs Saturday.

## 2. Open questions, inconsistencies, risks
**Inconsistencies**
1. **Alpaca live in Phase 2**: BRD §9 says "Alpaca live with approval mode on", but PLATFORMS.md, COMPLIANCE.md and `brokers.yaml` say Alpaca live isn't available to Canadians and route small-live US equities to IBKR. BRD needs an update.
2. **Kraken in the UI**: `ui/index.html` shows an ETH-USD position on Kraken, but `brokers.yaml` has `kraken.enabled: false`.
3. **Undefined sleeve**: `schedule.yaml` `hold_overnight_allowed_sleeves` lists `active_swing`, which isn't a sleeve in `risk_policy.yaml`. Also, which active strategies count as "intraday" is never defined.
4. **DB name mismatch**: `.env.example` has `POSTGRES_DB=tradingbot` but `DATABASE_URL` points at `/trading`.
5. **Small-live limits**: BRD gives small-live MDD ≤8% and 1% daily loss. `risk_policy.yaml` has 10% and 2% (1% appears only as a comment). Nothing defines a per-level limit profile.
6. **Scaling and derivatives gates**: BRD §12.6 says ≤1.5–2× per step, policy says 2.0. The UI lock tooltip says derivatives need "2+ quarters" outperforming; check that against BRD §13.2.
7. **LLM timeout**: `LLM_SCREENER_TIMEOUT_MS=2000` equals the TRD's ≤2 s p95 target, so about 5% of calls will time out. Define what `on_timeout: safe_default` means (veto, or rules-only at half size?).
8. **Demotion at L1**: `auto_demote_on` can't demote below L1. Define what a weekly breach does in paper.
9. **Live toggle in the UI**: the dashboard has a one-click Live toggle. It must enforce the step-up and confirmation flow, not just switch modes.

**Open questions**
- Is the 20% cap measured across all brokers in CAD in real time? Which FX rate source, and what happens if a broker is disconnected?
- Account types: cash vs. TFSA/RRSP? Frequent trading in a TFSA risks being taxed as business income, and superficial-loss tracking across brokers is needed (COMPLIANCE.md).
- Alpaca and IBKR are cash accounts: PDT rules don't apply, but settlement and good-faith-violation rules do. Does the risk engine track settled cash?
- Coinbase Ontario API availability and CSA registration aren't confirmed. The crypto sleeve may rely on the internal simulator only.
- Market data licensing: Alpaca paid data isn't available to Canadians, and IEX-only quotes may trip `stale_quote_seconds: 10` on thin names.
- Watchdog `deadman_timeout_s: 60` vs. halting after 15 s of missed beats: which actually fires the cancel-all?
- Who signs `risk_policy.yaml` (`signed_by` is a placeholder), and how are keys managed?
- Scope: does the MVP really need all 10 venues? I suggest US, TSX and crypto only.

**Key risks**
- Overfitting and leakage in the weekly retrain.
- Paper fills overstate performance, and the internal simulator is weakest for crypto.
- Complexity: multi-broker, multi-currency and global sessions before any edge has been shown.

## 3. Phased paper-trading MVP plan
**M0: Foundations (wk 1–2)**
- Repo, CI, config loader with schema plus cross-file validation, vault, Postgres/Timescale, audit log.
- *Accept:* invalid configs fail closed (tests for each issue in §2); no secrets in the repo or logs; every config change is audited.

**M1: Data and backtester (wk 2–4)**
- Massive and Finnhub ingestion, calendars (`exchange_calendars`), and an event-driven backtester with costs, slippage and FX.
- *Accept:* reproducible backtest of the core rebalancer plus 1 active rule vs. a blended benchmark; data-gap alerts; point-in-time data with a leakage test.

**M2: Risk engine and safety (wk 4–6)**
- Order-intent API → risk gate implementing every `risk_policy.yaml` limit; kill switch (MCP/CLI/dashboard); watchdog; anomaly halts; reconciliation.
- *Accept:* 100% of limits have unit and property tests; the kill switch cancels all paper orders in under 5 s; missing heartbeats halt trading; a reconciliation mismatch halts.

**M3: Paper execution plus MCP (wk 6–8)**
- Alpaca paper adapter, IBKR paper (TSX) adapter, internal crypto simulator; read and propose MCP tools (`place_order` returns a risk decision); approval queue with TTL.
- *Accept:* 5 consecutive sessions with no unhandled errors; fills reconcile with the broker; every order is traceable to a signal and a decision.

**M4: Sleeves and rebalancing (wk 8–9)**
- 60/30/10 sleeves, drift-band and weekly rebalance, 20% cap enforcement.
- *Accept:* simulated drift over 5 pp triggers a cost-aware rebalance within one session; an order that would exceed the cap is rejected.

**M5: ML and LLM layers (wk 9–12)**
- LightGBM filter with walk-forward CV, SHAP "why this trade", LLM veto/downsize with fallback, model registry, shadow champion/challenger.
- *Accept:* the ML filter improves after-cost backtest PF/Sharpe out of sample (deflated Sharpe reported); the LLM can never increase size (test); timeouts fall back correctly.

**M6: Dashboard and ops (wk 12–13)**
- Minimal dashboard (P&L, sleeves, limits, approvals, kill switch), daily summary, weekly kill-switch drill.
- *Accept:* the drill passes 2 weeks running; the daily summary is delivered.

**M7: Paper soak (60+ trading days)**
- *Accept (L2 gate):* Sharpe ≥1.0, MDD ≤10%, PF ≥1.3 net of costs; within 30% of backtest; zero unhandled breaches; uptime ≥99.5%. Then the owner signs off. No live trading before that.
