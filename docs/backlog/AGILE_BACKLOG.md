# ATLAS backlog

The 2026-10-19 universal AI directive authorizes isolated research infrastructure
before a live-engine audit. Live integration keeps its audit gate. Research is
intended to run continuously and support separate prop-competition and open-market
evaluation tracks; it does not authorize orders. The supplied repository path is
`C:\Users\borah\ATLAS`; it contains no live execution engine.

## Complete: initial scaffold and robustness

Gemini research interface and mocked tests; paid-tier/context checks; read-only
fixture API; decimal/timestamp validation and response/error handling; responsive
research terminal with baseline discovery, synthetic approval demonstration and
integration readiness; read-only capability and demo routes. Trading disabled.

## Complete: universal research foundation

Official-source ecosystem review; separate provider protocols and discovery;
typed market/horizon/data/model contracts; bounded runtime controls; immutable
research metadata and alias rollback; baseline forecasting; scoped orchestration;
held-out probability calibration; evaluation helpers; reproducible manifests and
local experiment history. See the [implementation map](../architecture/UNIVERSAL_AI_ECOSYSTEM.md).

## Complete: regime awareness, deterministic control rules, MCP contracts & walk-forward baseline-vs-tree study

1. Separate competition (`comp:btc-perp:v1`) and open-market (`open:spy-etf:v1`)
   frozen point-in-time dataset bundles with SHA-256 content verification
   (`src/atlas/marketdata/frozen.py`).
2. Read-only data provider contract (`Capability.DATA_SOURCE`, `ReadOnlyDataProvider`),
   allowlisted MCP adapter (`MCPDataSourceAdapter` for `alpha_vantage_mcp`,
   `financial_datasets_mcp`, and `fin_data_mcp`), mutating server rejection
   (`irohan0/quant-mcp`), FRED training prohibition, and deterministic
   `DataQualityReport` (`src/atlas/marketdata/quality.py`).
3. Authoritative `MarketCalendar` (`src/atlas/models/calendars.py`) for traditional
   exchange sessions (auctions, holidays, early closes, maintenance) and 24/7 crypto
   calendars (funding windows, maintenance), plus causal regime classification
   (`src/atlas/models/regimes.py`).
4. Deterministic control-plane rulebook and remaining-room engine
   (`src/atlas/control/rules.py`) with default-deny on unconfigured fields and
   strict isolation from LLMs.
5. Deterministic local tree challenger (`LocalTreeChallengerProvider`) and purged
   walk-forward evaluation (`run_baseline_vs_tree_study`) with per-regime slicing
   and non-promoting `OutcomeFeedbackRecord`.
6. ISO/IEC 42001, 23894, 27001, 22301, 31000, 9001, NIST AI RMF, and IOSCO
   governance alignment (`docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md`) and
   expanded Next.js research terminal with role-based views.

## Next: external licensing and live-track prerequisites, in dependency order

1. Obtain written vendor commercial/training data licenses (e.g., Alpha Vantage
   premium or Financial Datasets Professional with written retention/training
   confirmation, plus official exchange calendar files) and ingest first real
   frozen historical corpus.
2. Persist model/approval/calibration records with authenticated human review;
   export durable operational research telemetry. Add second real market/horizon
   holdout and preregistered feature ablations.
3. Implement native async Gemini usage metering; optionally add xAI research with
   model-specific discovery, privacy settings and contract tests.
4. Select one cloud training adapter only after region/quota/privacy/cost checks.
   Implement job reconciliation, budget/time enforcement, cancellation and checkpointing.
5. Add licensed foundation-model experiments (`Chronos-2` after Apache-2.0 license
   archive verification), embedding/retrieval adapters and optional batch/stream
   interfaces only when those capabilities are verified.
6. Test horizon-specific, multi-output, recursive and hierarchical models.
   Enable ensemble weights only after independent costed evidence beats both
   baseline and best member. Challenger promotion remains human-reviewed.
7. Production deployment/rollback and any order authorization are separate
   authenticated control-plane milestones; no research gate grants execution.

## Live integration track: pending evidence

Read-only audit of any existing execution source: venue/order interfaces,
idempotency, partial fills, unknown order reconciliation, stale data, risk limits,
kill switch, secret mechanism name and test isolation. Then characterization tests
and small security fixes; then one authorized read-only venue collector.

Public identity, account linking, terminal on real data and reporting require their
respective source and authorization work. Prop automation requires current verified
firm rules. Billing requires entity/product underwriting. Custody, withdrawals,
deposits and live order changes retain the master-spec gates. No model evaluation
or research approval overrides them.
