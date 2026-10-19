# ISO, NIST AI RMF, and IOSCO Governance Alignment

Status: **Designed for future certification readiness. No certification is claimed.**
All research models, forecasts, and control-plane rule evaluations in this repository
retain `execution_permission: none`.

## 1. Purpose

ATLAS aligns its architecture, data lineage, model lifecycle, and deterministic
control-plane boundaries with international standards for AI governance, risk
management, information security, business continuity, and quality management.
This mapping guides implementation and audit evidence collection without claiming
formal third-party certification.

## 2. Standards Mapping

| Standard / Framework | Scope | Concrete ATLAS Implementation & Controls |
| --- | --- | --- |
| **ISO/IEC 42001** | AI Management System (AIMS) | Explicit two-plane separation (`Research` vs `Deterministic Control Plane`); scoped `Eligibility` per model revision, instrument, horizon, target, and unit; mandatory human approval (`approver`, `approved_at`, `expires_at`); immutable `ModelRecord` revisions and audited `SQLiteModelRegistry` alias rollback. |
| **ISO/IEC 23894** | AI Risk Management | Strict point-in-time causality checks (`available_at <= as_of`); isolation of uncalibrated LLM `confidence` from numeric forecasting and position sizing; explicit model disagreement (`disagreement_by_step`); held-out `ProbabilityCalibrator` with leakage prevention; `combined_forecast: null` until independent out-of-sample evidence exists. |
| **ISO/IEC 27001** | Information Security | Pre-call prompt/context secret screening (`atlas/ai/policy.py`); zero logging of prompts, API keys, or response bodies in `ProviderRuntime`; explicit read-only tool allowlists in `MCPDataSourceAdapter` (`ALLOWED_MCP_TOOLS`); rejection of mutating MCP servers (`irohan0/quant-mcp`, `quantgpt-mcp`) and write/order tools. |
| **ISO 22301** | Business Continuity | Structural independence of `src/atlas/control/rules.py` from `src/atlas/ai/` and model providers so risk checks, daily loss circuit breakers, trailing/static drawdown gates, and kill-switch / auto-flatten evaluations operate when all AI/LLM processes are offline; `ProviderRuntime` deadlines, bounded retries, and single-probe circuit recovery. |
| **ISO 31000** | Risk Management | Versioned `TradingRuleBook` in `src/atlas/control/rules.py` enforcing fixed-fractional per-trade risk (0.5–1.0% equity) with ATR/structure stops, daily loss circuit breakers, static/trailing maximum drawdown, notional/leverage/correlation/sector caps, session/funding-window restrictions, time-based exits, and competition consistency/minimum-day rules. Any unconfigured or unknown policy field defaults to **DENY**. |
| **ISO 9001** | Quality Management | SHA-256 content-addressed `DatasetManifest` (`verify_content`), deterministic `DataQualityReport` (`src/atlas/marketdata/quality.py`), versioned `MarketCalendar` (`src/atlas/models/calendars.py`), and seeded purged walk-forward evaluation (`src/atlas/models/challengers.py`). |
| **NIST AI RMF 1.0** | Govern, Map, Measure, Manage | **Govern**: Master-spec hard boundaries and role separation. **Map**: Asset-class, venue, calendar, and license provenance tracking. **Measure**: Paired block-bootstrap MAE improvement, Brier score, expected shortfall, and per-regime slicing (`evaluate_groups`). **Manage**: Challenger immutability (`auto_promoted: False`), alias rollback, and default-deny gates. |
| **IOSCO AI Supervisory Toolkit** | Financial Market AI Governance | Explainable causal regime overlays (`src/atlas/models/regimes.py`), separate Competition vs Open-Market evaluation tracks (preventing cross-track score pooling), explicit transaction cost accounting, and strict prohibition of autonomous LLM order placement or risk override. |

## 3. Hard Boundaries Preserved

- Every `Forecast`, `ModelRecord`, `ResearchSignal`, `MarketDataBatch`, `RegimeState`, `WalkForwardStudyResult`, and `RuleEvaluationReport` carries `execution_permission: "none"`.
- LLMs may classify observations, draft research notes, or flag potential rule violations; they never size positions, authorize orders, override risk limits, or control the kill switch.
- Founder retains full ownership of source code, strategy logic, model artifacts, and signing keys.

