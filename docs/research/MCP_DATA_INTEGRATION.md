# Read-Only Data and MCP Integration Review

Reviewed 2026-10-19 against provider repositories, vendor terms and official
API documentation. A repository license covers server code, not upstream data.
No MCP server is installed or connected to ATLAS. This is a research integration
plan, not an approval to collect, retain or train on any source.

## Recommendation

Use MCP as a bounded research interface and source-discovery surface, not as the
authority for a frozen training corpus. Before a source enters the benchmark,
confirm the applicable data license permits the exact use (including internal
retention, feature derivation, model training, competition use and any planned
customer display). Record that evidence in the dataset manifest. For bulk,
repeatable snapshots, prefer the licensed provider's documented API or bulk
delivery over LLM-mediated tool calls. MCP annotations are hints, not a security
boundary.

The shortlist below ranks fit to ATLAS, not predictive quality.

| Candidate | Coverage and behavior | License, price and credentials | ATLAS fit and issues |
| --- | --- | --- | --- |
| [Alpha Vantage official MCP](https://github.com/alphavantage/alpha_vantage_mcp) | Official tool wrappers for equities, indices, options, FX, crypto, commodities, economic indicators, technical indicators, fundamentals, news/sentiment, insider and congressional disclosures. Daily equity history is documented at 25+ years; full daily and intraday history and many valuable endpoints are premium. | Server code is MIT. Data rights are separate. Free API usage is generally 25 requests/day; the documented verified open-source/education exception does not establish ATLAS commercial rights. Realtime/delayed US data and commercial use require premium entitlement and/or a sales agreement. Remote MCP uses OAuth to authorize an Alpha Vantage key; local setup needs the API key. Keep credentials in a secret manager or process environment, never a prompt or checked-in MCP config. | Best prospective single-vendor market adapter after written commercial permission. Explicit historical/realtime/delayed endpoint choice is useful, but default quote endpoints may be end-of-day and entitlements vary per endpoint. Intraday is expensive for wide polling; throttle and capture with the API, not an LLM. Equity bars are not automatically venue-specific crypto/perpetual data. |
| [fin-data-mcp](https://github.com/CohenD/fin-data-mcp) | README advertises 83 no-key tools across 15 providers, with optional keys expanding to as many as 110 tools/22 providers: Yahoo Finance, delayed Cboe, OKX, ECB/Frankfurter, SEC, World Bank, OECD, prediction markets, plus optional Alpha Vantage, Finnhub, FRED, Tiingo, EIA and others. README describes all tools as read-only and uses `readOnlyHint`; it also records Yahoo 429/bot sensitivity and a live smoke check dated 2026-06-28. | Server code is MIT; provider/data terms remain separate and vary. No keys for the base tool set; optional provider keys are environment variables. SEC access needs a declared contact User-Agent; FRED requires an API key. | Useful for sandbox discovery and comparison only. Yahoo is explicitly unofficial/bot-sensitive; broad source fallback can silently change semantics/coverage. It has no single data license, contract, SLA, or authoritative point-in-time guarantee. Do not use its FRED tools for training or archival: current FRED terms forbid AI training and caching/archiving without permission. Do not accept tool annotations as enforcement. |
| [Financial Datasets official MCP server](https://github.com/financial-datasets/mcp-server) | Repository exposes ten read tools for US stock prices, historical prices, financial statements, company news, and crypto prices/tickers. Vendor documentation claims 27,000+ tickers and 30+ years of financial history; it identifies SEC filings as the source for fundamentals and Databento as the stock-price partner. A hosted MCP endpoint is also documented. | Server code is MIT; underlying data is governed by Financial Datasets and source-provider terms. Current pricing: $20 credit pack/1,000 requests; Personal $200/month/100,000 requests for non-business use; Professional starts at $2,000/month/2,000,000 requests and allows professional/internal business use. Tool calls are billable requests. API key required. Professional redistribution has conditions; raw/bulk redistribution is prohibited. Terms prohibit training a model that competes with Financial Datasets. Obtain written confirmation that ATLAS's intended internal trading research, retention period, and feature training are permitted; do not assume an MCP response is export-licensed. | Strongest candidate for sourced equity fundamentals and filings, and a possible price-data candidate if the Professional license and vendor agreement explicitly cover the benchmark. It is not a crypto-perpetual feed. Its published MCP repository was last materially updated in 2025; verify its schema/tool behavior against the current hosted API. Vendor says sources are not guaranteed timely, accurate or complete. |
| [quant-mcp by irohan0](https://github.com/irohan0/quant-mcp) | Twenty research tools: yfinance price history, HMM regimes, backtests, risk/portfolio analytics, options, macro overlays and Monte Carlo. Its README lists yfinance, FRED CSV, Ken French factors, Yahoo/Google RSS and a 12-hour price/24-hour fundamentals SQLite cache. It includes local persistent watchlist and portfolio CRUD. | No API key is advertised; README says sources are free and labels the project MIT, but those claims do not grant rights in source data. GitHub repository metadata does not identify a license. Yahoo/yfinance, news, and macro terms need separate review. FRED terms block its use for training/archive as noted above. | Not a strictly read-only MCP server because it writes watchlists and portfolios. No broker-order tool is documented, but do not connect it to ATLAS as-is. Its precomputed HMM/metrics are opaque research outputs, not validated labels or a substitute for ATLAS's point-in-time regime pipeline. At most, inspect a fork with mutating tools disabled in a disposable sandbox; do not use its cache or scores as benchmark truth. |

### Name and authority checks

"quant-mcp" is ambiguous. The entry above is `irohan0/quant-mcp`, not
[QuantGPT's hosted MCP listing](https://github.com/quantgptco/quantgpt-mcp).
QuantGPT says its MCP tools do not place orders, but it does include writes to
its own saved studies, books, alerts and terminal; its separate Cloud product can
run user strategies against a user's brokerage account. Do not treat it as a
read-only source or connect it to ATLAS. No recommendation here enables an order
tool. The same check applies to future server updates: inspect tool schemas and
side effects at a pinned commit before allowlisting any method.

## Additional authoritative sources

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  are a better fundamentals/event source than an aggregator: submissions and XBRL
  company facts are available without an API key, update during the day, and the
  SEC says government-created and EDGAR filing content is free to access and
  reuse. Automated clients must declare a descriptive User-Agent and stay at or
  below 10 requests/second. Filings often appear 1-3 minutes after acceptance;
  represent the filing acceptance/availability time separately from fiscal period.
  Prefer direct SEC data with accession provenance over an intermediary. For
  point-in-time features select facts as they were filed, not later amendments or
  current restated values.
- Use the named competition's venue/exchange for its calendar and instrument
  metadata (for example, the relevant exchange's official trading-hours and
  holiday files). A current `MARKET_STATUS` endpoint is not a historical
  point-in-time calendar. Crypto is not one universal continuous session: venue
  maintenance, funding timestamps and instrument lifecycle still matter.
- FRED is not an ATLAS ML source under the currently published
  [FRED terms](https://fred.stlouisfed.org/legal/): they prohibit use in
  developing/training AI/ML systems and prohibit storing, caching or archiving
  data absent permission. Use a primary agency series with explicit rights or get
  written permission before any research retention/training. FRED/ALFRED
  vintage support would otherwise be useful for release-time/revision-aware
  macro features, but vintage availability is not a license grant.

## Safe integration shape

1. Keep credentials in an OS secret manager or narrowly scoped process
   environment. Never put keys in a prompt, request log, source file, MCP config
   committed to the repo, or frontend bundle. Prefer Alpha Vantage's official
   OAuth flow or a local sidecar whose secret injection and process arguments
   have been reviewed. A provider key is not execution authority.
2. Add a dedicated typed read-only data contract; do not misrepresent a market
   feed as `ForecastProvider`, `TrainingProvider`, or an LLM `ResearchProvider`.
   Allowlist exact server/tool names in code, and reject all writes, unknown
   tools, raw tool-routing from an LLM, and unbounded pagination.
3. Normalize responses into a provenance envelope plus observations/features:
   source/provider/version, upstream record ID, instrument/venue, event time,
   available/published time, retrieval time, timezone, adjustment basis, calendar
   ref, license ref, and response/content hash. Unknown provenance/license means
   `quality=unknown` and is not eligible for forecasting/training.
4. Run the same schema, numeric, chronology, duplicate, calendar, freshness,
   survivorship, and corporate-action checks regardless of provider. MCP
   `readOnlyHint` is advisory only. Keep provider-specific quotas and deadlines
   in `ProviderRuntime`; count throttling, stale responses and unknown costs.
5. Treat results only as research records or fixtures until rights, lineage and
   quality checks pass. Freeze eligible bytes and their manifest; tests must
   prove the resulting Forecast/ModelRecord/ResearchSignal still have
   `execution_permission: none`. Do not route MCP into Gemini prompts by default.

## Milestone gaps and source fit

| Gap | Preferred source/approach | Why MCP alone is insufficient |
| --- | --- | --- |
| Licensed competition dataset | Select the named competition and instrument first. Alpha Vantage is a candidate for global daily equity/FX and daily crypto history only after written commercial/internal-training rights. Financial Datasets Professional is a candidate for US equity prices/fundamentals if its terms and a written answer explicitly cover ATLAS training and frozen retention. For an exchange-specific crypto competition, request licensed OHLCV from that actual venue or a vendor that grants training/retention rights. | A server repo's MIT license is not a data license. Free/open-source/educational API exceptions are not ATLAS's commercial license. MCP calls may truncate, charge per request, or return only a limited window. |
| Point-in-time fundamentals/news/macro | SEC direct submissions/XBRL for as-filed US fundamentals/events; licensed vendor for market bars/news. Macro only from a primary source whose terms expressly permit internal ML use. | Need filing/availability timestamps, revisions, origin/source IDs and full export. FRED is explicitly disqualified for training and caching absent written permission. |
| Authoritative calendar/targets | Versioned calendars from the specific exchange/competition plus explicit 24/7 crypto instrument/funding metadata from the relevant venue. | None of the four MCP candidates is the authoritative historical exchange-calendar service. Current status or a provider's timestamp cannot construct past sessions, holidays, DST, early closes, or target availability. |
| Data-quality reports | ATLAS validator and frozen provenance manifest, with source-specific contracts/fixtures. | Providers can return HTTP 200 with stale, revised, adjusted, delayed, incomplete, or mismatched data. |
| Regime-aware baseline/tree study | ATLAS-generated causal regime features and a preregistered walk-forward evaluation on the frozen dataset. Use last-value, zero-return/no-trade, then one LightGBM or XGBoost challenger. | Quant-MCP's HMM and vendor-provided analytics are comparison surfaces only; their labels/features are not the frozen experiment or proof of skill. |

## Implementation order

1. Choose one named competition/rulebook and one open-market comparison track;
   write separate objectives, target timestamps, scoring/cost assumptions and
   no-lookahead split rules. Obtain data/legal approval for retention and model
   training before collection. If approval is absent, stop at synthetic tests.
2. Define `DataSource`/`ReadOnlyDataProvider` and provenance records in
   `src/atlas/ai/models/providers.py` and `src/atlas/schemas.py`; add a
   provider capability only for implemented, tested behavior. Create
   `src/atlas/marketdata/` adapters for explicitly allowlisted data tools.
3. Add deterministic validators/calendar interfaces and a quality report in
   `src/atlas/marketdata/quality.py` and `calendars.py`. Unknown rights, unknown
   availability time, malformed timestamps, stale bars, mismatched calendar or
   invalid adjustment lineage deny the dataset.
4. Add an offline freeze/import command and canonical content hash/manifest,
   pinned transform and non-overlapping train/validation/test dates. Persist raw
   provenance locally only where the license permits; never silently archive MCP
   responses.
5. Preregister one baseline-versus-tree experiment and regime taxonomy in
   `docs/research/experiments/`, then implement the walk-forward runner in
   `src/atlas/ai/models/experiments.py`/`evaluation.py`. Keep regimes causal and
   include `unknown`; report both overall and per-regime results. No online
   weight mutation, automatic promotion or ensemble.
6. Add mocked MCP contract tests before any network test: exact tool allowlist,
   write-tool denial, secret redaction, retries/rate limits, malformed/stale
   response rejection, calendar/DST/holiday boundaries, license-missing denial,
   hash reproducibility and `execution_permission == "none"`. Add a later
   optional, explicitly enabled vendor smoke test that does not run in the
   default suite.

This plan adds no OpenAI SDK, no live order path, and no changes to customer-funds
or account boundaries. Review vendor terms again before purchase or ingestion.