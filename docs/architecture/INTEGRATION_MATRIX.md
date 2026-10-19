# Integration matrix

Status values: `scaffold`, `selected`, `blocked`, `rejected`. Nothing here is connected to a live account. Prices and vendor terms in older research notes are not restated here, because they go stale. Re-read the vendor page before buying or applying.

| Layer | Choice | Status | Note |
| --- | --- | --- | --- |
| Language | Python | selected | Matches the stated live system. That repo is not in this tree |
| API | FastAPI + Pydantic | scaffold | Read-only health, fixture candles, research capability and synthetic demo GET routes |
| Terminal | Next.js + TypeScript | scaffold | Research terminal; invented fixture data, no order controls |
| Research LLM | Gemini via `google-genai` | scaffold | `LLMProvider` plus `GeminiResearchProvider`. Paid tier required. No tools |
| Second narrator | xAI over HTTP, later | selected | Not implemented. The OpenAI SDK is not the client |
| OpenAI | None | rejected | Not a dependency of this repository |
| Quant models | Naive forecast, then LightGBM or XGBoost. PyTorch if measured | selected | Not installed |
| Chronos-2 | Local weights after the license file is confirmed Apache-2.0 | selected | Not downloaded |
| TimesFM 3.0 weights | Hugging Face weight files | rejected | Non-commercial license. Not a dependency |
| Moirai 2.0 | Salesforce weight files | rejected | CC-BY-NC-4.0. Not a dependency |
| Operational store | PostgreSQL | selected | Not provisioned |
| Research store | Parquet + DuckDB | selected | Not provisioned |
| Crypto connectors | CCXT and native APIs, research only | blocked | Wait for the live adapter audit. CCXT is not the execution bus |
| Forex connector | Existing broker API | blocked | Preserve it. Do not replace it from this tree |
| Charts | Lightweight Charts, ECharts. Widgets as a hosted reference | selected | Advanced Charts waits on a written license |
| Identity | Clerk for human login, authorization in ATLAS | selected | Not implemented. Clerk is not KYC |
| Software billing | Stripe Billing, after underwriting | blocked | Not adopted. A subscription charge is not a trading deposit |
| Wallet | User signs in their own wallet | selected | Design only. Not built |
| ATLAS-operated custody | Holding customer keys | rejected | |
| KYC / sanctions | Hosted vendor, when a money feature creates the duty | blocked | No documents in this tree |
| MCP market/research data | Alpha Vantage official, Financial Datasets, fin-data-mcp, quant-mcp reviewed | blocked | No client is installed. Must use explicit read-only allowlists, separate credentials, source/license provenance and local validation; see `../research/MCP_DATA_INTEGRATION.md` |
| Monitoring | Prometheus + Grafana | selected | Not deployed |
| Packaging | Docker | selected | No image in this increment |
| Market data in this tree | Local fixture | scaffold | `source` is `fixture`. It is not a venue feed |


## Universal research foundation update � 2026-10-19

The earlier rows describe vendor adoption, not the complete current module set.
`src/atlas/models/` now implements provider contracts/discovery, runtime controls,
instrument and horizon registries, baseline forecasting, research orchestration,
calibration/evaluation helpers, immutable model metadata with research rollback,
and SQLite experiment history. No additional vendor is connected. Training,
embedding, retrieval, deployment and remote registry providers are contracts only.

The official-source cross-provider capability and commercial review is
[AI_ECOSYSTEM.md](../research/AI_ECOSYSTEM.md). The implementation boundary is
[UNIVERSAL_AI_ECOSYSTEM.md](UNIVERSAL_AI_ECOSYSTEM.md).

The research plane targets separate competition and open-market evaluation
tracks with causal regime features. Continuous research scheduling, source
connectors and regime detection are not implemented. Read the
[research operating contract](RESEARCH_OPERATING_CONTRACT.md) before designing
any future deterministic policy; research approval remains distinct from
execution authority.
