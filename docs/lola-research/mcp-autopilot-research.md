# MCP + "Autopilot" research (current to 2026-10-17)

Scope: which MCP servers and MCP spec features help us run an always-on, one-button **paper** autopilot, and how
production systems run "always on". Our hard rules still apply: paper only (`BUILD_ALLOWS_LIVE=False`); the AI can
never approve orders or change policy; models can only shrink or drop trades; trading code cannot move money.

**Honest framing of "maximize".** No system can promise the "maximized number". What a responsible autopilot
maximizes is *risk-adjusted expected return under constraints*: it compounds inside a fixed risk budget (volatility
target, fractional-Kelly cap, loss limits, allocation cap). It accepts lower raw return in exchange for a much lower
chance of ruin. Full Kelly, leverage and "always fully invested" maximize the expected *log* growth only when the
edge is known exactly, and it never is (Harvey et al.; see section 3).

## 1. Public MCP servers relevant to trading and markets

Legend:
- **Mode:** RO = read-only data; TR = can place orders.
- **Decision:** *client* = connect our MCP client adapter (allowlisted read tools, output treated as untrusted).
  *replicate* = build the same capability as our own offline tool or adapter (no third-party MCP in the loop).
  *skip* = not useful or not allowed.

| Server | Maintainer / source | Licence | Auth | Canada | Mode | Maturity / risk | Decision |
|---|---|---|---|---|---|---|---|
| **Alpaca MCP v2** | Alpaca (official), github.com/alpacahq/alpaca-mcp-server; docs.alpaca.markets/us/docs/trading-api-mcp; blog alpaca.markets/blog/alpaca-launches-mcp-server-v2 | MIT | API key + secret (env); `ALPACA_PAPER_TRADE=true` by default; `ALPACA_TOOLSETS` filters tools | **No live accounts for Canadian residents**. Alpaca CA is pursuing CIRO approval, target about Nov 2026 (alpaca.markets/support/countries-alpaca-is-available, alpaca.markets/ca/disclosures). Paper and data are usable. | TR + RO (61 to 65 tools; trading, market data, options, crypto) | Mature; OpenAPI-generated. Ships "TrustBoundaryMiddleware". Order tools exist, so it must be filtered. | **client, market-data toolset only** (US bars/quotes/news). Orders keep going through our own paper adapter. |
| **Interactive Brokers MCP** | IBKR (official, remote): `https://api.ibkr.com/v1/api/mcp-public`; press release 2026-07-28 interactivebrokers.com/en/general/about/mediaRelations/7-28-26.php; brokerage.ibkr.com/en/trading/ai-hub.php | Proprietary service | IBKR OAuth login; one account per authorization | Yes (IBKR Canada) | Portfolio, research, order status, *trade instructions* (the user reviews and submits each order in IBKR) | Official, new. Designed so a human submits every order. | **client (read-only tools: portfolio, positions, research)** for reconciliation research only. Execution stays on our IBKR paper adapter (ports 4002/7497, DU accounts). |
| IBKR community MCP | code-rabi/interactive-brokers-mcp (github.com/code-rabi/interactive-brokers-mcp) | MIT | Local gateway | n/a | TR | **Unofficial, alpha**; can place trades | **skip** |
| **Kraken CLI MCP** | Kraken (official), docs.kraken.com/home/mcp; github.com/krakenfx/kraken-cli | Open source (see repo) | None for `market`/`paper`; API key for `account`/`trade`/`funding` | Yes: Restricted Dealer in Canada; Ontario CAD 30k/12-month limit for non-major coins (support.kraken.com/articles/canada-regulatory-requirements-overview) | Service groups: `market` (RO), `paper` (simulated), `account` (RO); `trade`/`funding`/`earn` are *dangerous* | Official; labelled alpha; local stdio only; never expose it. Least-privilege keys. | **client with `-s market` only** (crypto ticker/OHLC/order book). `paper` is redundant with our paper broker. Never `trade`/`funding`. |
| **Coinbase CLI MCP** (Advanced Trade) | Coinbase (official), docs.cdp.coinbase.com/coinbase-for-agents/overview and /skill; hosted `https://agents.coinbase.com/mcp` (OAuth 2.1) | Proprietary / npm `@coinbase/coinbase-cli` | CDP API key (Trade + Transfer) or OAuth | Yes, Coinbase Canada; Ontario limits (help.coinbase.com Canada regulatory FAQ) | TR + **transfers** + RO | Official. **Exposes transfer tools.** | **replicate** (public market-data REST via our disabled-by-default adapter). Do not connect: transfer tools are out of policy. |
| Coinbase AgentKit MCP extension | Coinbase, docs.cdp.coinbase.com/agent-kit/core-concepts/model-context-protocol | Apache-2.0 | CDP keys + wallet | n/a | On-chain wallet actions | Wallets and money movement | **skip** (trading must never move money) |
| **Massive (ex-Polygon) MCP** | Massive (official), github.com/massive-com/mcp_massive; hosted `https://mcp.massive.com` (OAuth); massive.com/docs/ai-tools/quickstart | MIT (repo) | OAuth (hosted) or `MASSIVE_API_KEY` | US data, usable from Canada | RO (3 tools: `search`, `call`, `query` over the whole REST API; local SQL workspace) | Official. `call` is generic, so the arguments need validating. | **client** (US equities/options bars, news, aggregates). Replaces our M1 Polygon adapter when keys exist. |
| **Finnhub MCP** | Finnhub (official), hosted `https://mcp.finnhub.io/mcp`, streamable HTTP + OAuth (finnhub.io/static/finnhub-how-to-connect-mcp-server.html) | Proprietary | OAuth | Yes; global incl. TSX tickers | RO (quotes, financials, estimates, earnings, filings, news, economic data) | Official, 2026-08 | **client** (earnings calendar, news sentiment, fundamentals). |
| **Alpha Vantage MCP** | Alpha Vantage (official), github.com/alphavantage/alpha_vantage_mcp; hosted `https://mcp.alphavantage.co/mcp` | Apache-2.0 (repo) | API key | Yes (global, incl. TSX `.TRT`) | RO (market, fundamentals, technicals, FX, crypto, economic) | Official | **client (fallback data and fundamentals)** |
| **Financial Modeling Prep MCP** | FMP (official), site.financialmodelingprep.com/developer/docs/mcp-server | Proprietary | API key in URL query (rotate; never log URLs) | Yes | RO (fundamentals, statements, ratios, screeners) | Official. The key in the query string is a leakage risk. | **client** if fundamentals depth is needed; otherwise Finnhub. |
| **EODHD MCP** | EODHD (official), eodhd.com/financial-apis/mcp-server-for-financial-data-by-eodhd; `https://mcp.eodhd.com/v2/mcp` (OAuth) | Proprietary | OAuth or API key | Yes; **good TSX/TSXV coverage**, EOD + fundamentals | RO (72 read-only tools) | Official | **client (preferred for Canadian EOD and fundamentals)** |
| Tiingo MCP | Community (Rust `tiingo-mcp`, stdio) | See repo | `TIINGO_API_KEY` | Yes | RO | Community; pin the version | **replicate** (simple REST; our adapter) |
| Yahoo Finance MCP | Community (e.g. github.com/benethos-hub/yahoo-finance-mcp, yfinance-based) | See repo | None | n/a | RO | Scrapes unofficial endpoints; Yahoo ToS; brittle | **skip** for production (research only) |
| FRED / SEC EDGAR (FinanceAPIs) | FinanceAPIs hosted `https://mcp.financeapis.dev/mcp` (financeapis.dev/guides/using-mcp-tools/) | Proprietary | OAuth | n/a | RO (`search_fred_series`, `get_fred_observations`, EDGAR) | Third-party aggregator | **replicate**: FRED and EDGAR are free public APIs; our own adapter keeps provenance. |
| SEC-API MCP | sec-api.io/docs/mcp-server, `https://api.sec-api.io/mcp?apiKey=…` | Proprietary | API key in URL | n/a | RO (49 tools: filings, XBRL, insider) | Paid. Key in URL. | client only if paid; otherwise replicate from EDGAR. |
| Bank of Canada Valet / SEDAR+ / SEDI | No official MCP found | n/a | none | Canada | RO | n/a | **replicate** (we already have `BankOfCanadaValet`, `SEDARPlusFilings`, `SEDIInsiderTrades` adapters, disabled by default) |
| Benzinga MCP | Benzinga (official), benzinga.com/apis/blog/our-mcp-server-is-live/ | Proprietary | API key | n/a | RO (news, ratings, calendars) | Official, paid | **client** (news) if licensed |
| GDELT | No official MCP; GDELT Cloud API (docs.gdeltcloud.com) | Open data | none | global | RO | n/a | **replicate** (our `GDELTDoc` adapter exists) |
| **TradingView MCP** | TradingView (official), `https://mcp.tradingview.com/mcp`; tradingview.com/support/solutions/43000795699 and /43000795700 | Proprietary | TradingView account (Essential plan or higher) | Yes | RO (`run_screener`, `get_symbol_data(_batch)`, `get_screener_columns`, `get_technicals_rating`) | Official. Saved screens can't be opened by ID. | **client (screener)** as an idea source. Our `run_scanner` is the offline equivalent. |
| **QuantConnect MCP** | QuantConnect (official), github.com/QuantConnect/mcp-server; hub.docker.com/r/quantconnect/mcp-server | Apache-2.0 | QC user id + API token | Yes | Projects, compile, **backtests**, optimisation, **live deployment** | Official, 60+ tools. Has live-trading tools. | **client (backtest/optimise tools only; live tools denied)** for cross-checking our backtests. |

**Top picks to adopt first** (all read-only, via our allowlisting client adapter, disabled until keys/OAuth exist):
1. **EODHD**: Canadian EOD and fundamentals.
2. **Finnhub**: news, earnings and estimates.
3. **Massive**: US intraday and options.
4. **Kraken CLI `-s market`**: crypto, no key needed.
5. **TradingView screener**: idea generation.
6. **QuantConnect** (backtest tools only).

Everything else is replicated as our own offline tool.

**Never connect for execution:** every order still goes through *our* risk engine and paper adapters. Third-party
broker MCPs (Alpaca, IBKR, Coinbase, Kraken `trade`) would bypass the risk engine, approvals and the kill switch.

## 2. MCP spec features useful for an autopilot

Current spec: **2026-07-28** (modelcontextprotocol.io/specification/2026-07-28/changelog). The previous revision
was 2025-11-25 (…/2025-11-25/changelog), and before that 2025-06-18. Our SDK is `mcp` 2.3.0, which implements 2026-07-28.

| Feature | What it gives us | How we use it |
|---|---|---|
| **Tools + structured output** (`outputSchema`/`structuredContent`; any JSON Schema 2020-12 since 2026-07-28) | Typed results | All new tools return JSON dicts; the SDK derives schemas from type hints. |
| **Resources** + **`subscriptions/listen`** (2026-07-28 replaces `resources/subscribe`). Clients opt in to `resourceSubscriptions`, and the server pushes `notifications/resources/updated`. | Live positions, P&L and alert feeds without polling | We expose `tradingbot://autopilot/status`, `tradingbot://portfolio/positions` and `tradingbot://alerts` as resources. Clients that support `subscriptions/listen` get updates. The others poll (`ttlMs` cache hint). |
| **Elicitation** (2025-06-18 form mode; 2025-11-25 URL mode; 2026-07-28 MRTR `InputRequiredResult`) | Ask the human for input mid-call | **Not trusted as approval.** The AI host can answer an elicitation itself, so `autopilot_start` over MCP creates a *start request* that the owner approves in the console with step-up (passphrase + TOTP). URL-mode elicitation points the human at the console URL. |
| **Sampling** | Server asks the client's LLM | **Deprecated** in 2026-07-28 (SEP-2577); not used. |
| **Tasks** (experimental 2025-11-25; official extension `io.modelcontextprotocol/tasks` in 2026-07-28, polled with `tasks/get`) | Long-running jobs (backtests, retrains) | `run_backtest` is bounded and synchronous today. Tasks are the upgrade path for long backtests. |
| **Progress notifications** | Feedback on long tools | Used for `run_backtest` when the client provides a progress token. |
| **Authorization**: OAuth 2.1 + Protected Resource Metadata (RFC 9728), resource indicators (RFC 8707); 2026-07-28 adds `iss` validation (RFC 9207) and Client ID Metadata Documents | Transport auth for remote servers | Our server is stdio + per-client scoped tokens (`read`/`propose`/`kill`). OAuth is needed only if we ever expose streamable HTTP. For external servers, OAuth tokens are stored by issuer, never passed through. |
| **Stateless protocol** (2026-07-28: no `initialize`, no session id) | Restart-safe clients | Fits an always-on bot: a core restart doesn't break MCP clients. |

### MCP security best practices (applied)
Sources:
- modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices
- OWASP MCP Security Cheat Sheet (cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html)
- OWASP *Practical Guide for Securely Using Third-Party MCP Servers* (genai.owasp.org/download/51928/)
- OWASP MCP Tool Poisoning (community.owasp.org/attacks/MCP_Tool_Poisoning)

- **Tool poisoning and rug pulls:** pin a SHA-256 of each external tool's name, description and schema. Refuse the server if the hash changes.
- **Prompt injection through outputs:** every external result is wrapped as `{"untrusted": true, …}`, control characters are stripped, it is truncated, and it is only used as *data* (research and screener veto/downsize). It never reaches order creation.
- **Least privilege:**
  - external servers are disabled by default;
  - each server has an explicit tool allowlist;
  - a deny pattern (order, trade, buy, sell, transfer, withdraw, …) applies even when a tool is allowlisted;
  - for our own server, scoped tokens (`read`/`propose`/`kill`) are stored as SHA-256 hashes only.
- **No token passthrough / confused deputy:** our client never forwards our MCP token downstream. External credentials are referenced by env-var *name* only.
- **Human approval for consequential actions:** autopilot start needs owner step-up in the console. Stop is always allowed: it reduces risk.
- **Local only:** stdio transport. Never expose kraken/coinbase CLIs or our server on a network.

## 3. How production autonomous trading systems run "always on"

- **Event loop plus scheduler, not cron alone.** NautilusTrader uses one deterministic event-driven kernel for both backtest and live; only the data and execution clients differ (nautilustrader.io/docs/latest/concepts/architecture/). Timers handle the periodic jobs. We do the same:
  - a *safety loop* (heartbeat, reconcile, guards, honour stop) every few seconds on the main thread;
  - a *work loop* (autopilot cycles, retrain, reports) on a worker thread, so slow work never starves the heartbeat.
- **Streaming data:** live venues push quotes over websockets (Alpaca, Kraken, Coinbase, IBKR). Bars are built incrementally and *staleness is measured* per feed. Here every feed has a `max_age_s`. A stale feed for an open venue **pauses** the autopilot (fail closed) and it resumes automatically when the data is fresh again.
- **State recovery:** persist state, and on restart restore the cache and run *startup reconciliation* against the venue before strategies start (nautilustrader.io/docs/latest/concepts/execution/reconciliation/). An external supervisor restarts crashed processes. We already persist the paper book and recon ledger. Autopilot state is now persisted too, and it resumes after a restart only if it was running and no guard fires.
- **Health checks:** heartbeats plus an independent watchdog process (we have one). Auto-pause or halt on: missed beats, data staleness, broker disconnect, model drift, anomalies, and daily/weekly loss or drawdown limits.
- **Session awareness:** crypto trades 24/7; equities follow exchange calendars (holidays, half days). Follow-the-sun ordering. We reuse `SessionModel` (exchange_calendars + schedule.yaml).
- **Rebalancing cadence:** calendar plus drift bands (rebalance when a sleeve leaves its band, at most every N minutes) with cost-aware no-trade zones. Our sleeves already have drift bands and a max-cost rule.
- **Continuous learning:** retrain on a schedule as *challengers*, shadow-test them, and promote only through gates with human sign-off. Drift monitors demote models (we have this; promotion still needs owner sign-off).
- **Capital-aware compounding:**
  - **Reinvest within a risk budget.** Profits stay in the bot's capital up to the configured allocation cap; our policy has `profits_raise_cap: false`, so the cap grows only via the autonomy ladder.
  - **Volatility targeting:** scale exposure by target vol divided by forecast vol. Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert, *The Impact of Volatility Targeting* (people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf), show it reduces tail events and improves Sharpe for risk assets. Conditional variants are in *Conditional Volatility Targeting*, FAJ 2020 (tandfonline.com/doi/full/10.1080/0015198X.2020.1790853).
  - **Fractional Kelly:** use a quarter to half of Kelly at most, because estimation error makes full Kelly ruinous (MacLean, Thorp & Ziemba; see the arXiv 2508.16598 discussion).
  - **No leverage** (our policy).
- **Realistic expectations:** an always-on bot mostly *does nothing*. Most candidate trades are dropped by cost or news filters (our demo shows 2 of 454 submitted). That is the system working as intended.

## 4. What this means for our build
- `autopilot` package: state machine (off / running / paused / waiting) persisted in the state DB. Start needs owner step-up; stop is instant. Feed registry with staleness. Shrink-only risk-budget overlay (vol target + fractional Kelly + allocation cap). Cycles run per session cadence and reuse the existing pipeline, risk engine and paper broker.
- **Autonomy is unchanged.** At policy level L1 (current), every order the autopilot sizes is **queued for owner approval** (TTL 120 s). Fully hands-off execution needs autonomy L3 through a *new owner-signed policy* after the ladder gates, and the current validation refuses levels above 1. The autopilot is therefore "one button" for the *loop*. It is not one button for bypassing approvals.
- New read-mostly MCP tools and resources, plus an external MCP client adapter (disabled, allowlisted, untrusted output, no order tools).
