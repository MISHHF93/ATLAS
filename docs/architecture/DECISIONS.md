# Decisions

Recorded 2026-10-19. Items 1–9 come from the build initialization. Items 10–19 come from the architecture pass that followed. Items 20–32 come from the universal research foundation pass. Items 33–38 record the regime, deterministic rulebook, MCP contract, frozen baseline-vs-tree study, and ISO alignment increment. They bind this repository. They do not describe unaudited live-system behavior.

1. Gemini is the default research provider. Frequent notes use `gemini-3.8-flash`. Deep notes use `gemini-4-argon`. The permanent model choice waits on measured accuracy, latency, cost, and reliability.
2. `LLMProvider` is the only research interface. A second provider can be added later without an OpenAI SDK.
3. OpenAI is not a dependency of this repository.
4. Quantitative prediction stays on local models. Risk decisions use deterministic code. Gemini cannot place, cancel, or size an order.
5. Proprietary context goes to Gemini only with `ATLAS_GEMINI_TIER=paid`. The pricing page marks the free tier as used to improve Google products and the paid tier as not used that way. Source: https://ai.google.dev/gemini-api/docs/pricing
6. `confidence` on a research note is an uncalibrated model estimate.
7. The first market route serves labeled fixtures. A live public feed waits until the existing connector is identified.
8. The live engine is preserved until an audit shows a defect that a patch cannot fix.
9. Prop automation stays disabled until each program's current rule is verified.
10. `C:\Users\borah\atlas` is a new scaffold. It is not the live trading system, and it is not a rewrite of that system.
11. The first sellable product is software: research and, later, a read-only view of accounts the customer already holds. Custody, withdrawals, deposits, and live order changes stay disabled until counsel, a licensed partner, and written provider approval.
12. Eight money records stay separate: software subscription, broker, exchange, user external wallet, custodian, prop-firm rules, founder treasury, and any future customer-funds ledger. A broker profit is not an ATLAS wallet balance. Customer funds, if ever allowed, use double-entry reconciled to the provider.
13. A research note is not an order. Forecast `execution_permission` defaults to `none`. A missing evaluation gate leaves that permission at `none`. Language-model confidence is not combined with a numeric forecast.
14. TimesFM 3.0 downloaded weights are non-commercial and are not a dependency. Moirai 2.0 is CC-BY-NC-4.0 and is not a dependency. Chronos-2 may be evaluated later only after the downloaded license file is confirmed Apache-2.0. No foundation weights are installed in 0.1.0.
15. xAI Grok may be added later as a second narrator over HTTP to the xAI API. The `openai` package is not added for that call.
16. The only wallet design allowed on paper is the user signing in a wallet they control. It is not implemented. ATLAS-operated custody is rejected. Offline agent signing is rejected.
17. Stripe Billing for a software subscription is not adopted. It waits on underwriting of the legal entity and the product. A subscription charge is not a trading deposit.
18. The operating entity’s country is unknown. Canada, the United States, the European Union, and the United Kingdom are research jurisdictions in the notes. They are not a confirmed domicile.
19. Allora Topic 38 is out of scope.
20. Universal ecosystem directive, 2026-10-19: offline research architecture and foundational implementation may proceed independently of the live-engine audit. This supersedes audit-first sequencing only for isolated research modules.
21. The user supplied `C:\Users\borah\ATLAS` as the repository path. Inspection finds the scaffold and research modules, not a live execution system.
22. Use capability-specific protocols and explicit discovery. No provider is forced to implement training, inference, retrieval and deployment together.
23. Research forecasts, calibrated probabilities and strategy candidates have no execution authority. Approval is scoped to model revision, instrument, horizon, target and unit; no global model approval exists.
24. Experiment history uses local SQLite from the standard library for the research foundation. It is not a customer-funds ledger or production store.
25. No cloud jobs or new paid inference are launched in this increment. Vendor evidence and verified price snapshots live in `../research/AI_ECOSYSTEM.md`.
26. Research has two distinct future evaluation tracks: a named competition and an open-market instrument/horizon. Research may run 24/7; that does not grant order authority, and scores do not transfer between tracks.
27. Regime labels and features must be deterministic, versioned and point-in-time. Unknown regime/source/calendar data stays unknown; labels organize research and do not enable live regime switching.
28. External MCP servers are not integrated as live network processes yet. The dated source review is `../research/MCP_DATA_INTEGRATION.md`; tool `readOnlyHint` metadata is not a security control or a data license.
29. Do not use FRED through an MCP server or direct endpoint for ATLAS training or frozen retention under the current terms without written permission. Its published terms prohibit AI training and storage/caching/archiving.
30. Financial Datasets is a possible source only under a plan that permits the intended business use and with written confirmation for retention/training; raw/bulk redistribution is not permitted by its current self-serve terms. Alpha Vantage commercial and exchange-data terms must also be approved before collection or training.
31. `irohan0/quant-mcp` is not a read-only ATLAS data adapter: its documented tools can mutate watchlists/portfolios and its inputs include scraped or differently licensed sources. Do not connect it as-is.
32. The research operating contract is documented in `RESEARCH_OPERATING_CONTRACT.md`; it does not implement a live execution path. Unknown execution rules deny execution.
33. `src/atlas/models/calendars.py` and `src/atlas/models/regimes.py` implement versioned traditional-session and 24/7 crypto calendars (holidays, early closes, opening/closing auctions, funding windows, maintenance windows) and strictly causal regime classification (`volatility`, `trend`, `liquidity`, `session`, `macro_event`) with explicit `unknown` fallback.
34. `src/atlas/control/rules.py` settles versioned, testable trading rules exclusively in the deterministic control plane (per-trade fractional risk with ATR/structure stops, daily loss circuit breaker, static/trailing max drawdown, notional/leverage/correlation/sector caps, quality/freshness/license gates, session/horizon/time-exit rules, kill switch / auto-flatten, and competition consistency & minimum trading days). Unconfigured fields default-deny, `atlas.ai` is never imported, and `execution_permission` remains `"none"`.
35. `src/atlas/marketdata/` implements `ReadOnlyDataProvider` (`Capability.DATA_SOURCE`), `MCPDataSourceAdapter` with explicit read-only tool allowlists (`alpha_vantage_mcp`, `financial_datasets_mcp`, `fin_data_mcp`), explicit rejection of `irohan0/quant-mcp` and FRED training/archival use, and `validate_market_data_batch` (`DataQualityReport`).
36. `src/atlas/models/challengers.py` implements a deterministic local boosted regression stump tree challenger (`LocalTreeChallengerProvider`) and purged walk-forward evaluation (`run_baseline_vs_tree_study`) against naive and no-trade baselines on SHA-256 frozen datasets for separate competition and open-market tracks. Outcomes emit `OutcomeFeedbackRecord` with `auto_promoted: False` and `weights_mutated_in_place: False`.
37. `docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md` maps ATLAS controls to ISO/IEC 42001, ISO/IEC 23894, ISO/IEC 27001, ISO 22301, ISO 31000, ISO 9001, NIST AI RMF, and the IOSCO AI supervisory toolkit for future certification readiness without claiming certification.
38. The Next.js research terminal includes role-based views (`Founder / Admin`, `Quant Researcher`, `Risk & Ops Monitor`), regime overlays, remaining-room bars, walk-forward track tabs, and ISO readiness status without adding any live order-entry surface.
