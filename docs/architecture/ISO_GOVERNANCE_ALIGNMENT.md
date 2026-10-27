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
| **ISO 9001** | Quality Management | SHA-256 content-addressed `DatasetManifest` (`verify_content`), deterministic `DataQualityReport` (`src/atlas/marketdata/quality.py`), versioned `MarketCalendar` (`src/atlas/ai/models/calendars.py`), and seeded purged walk-forward evaluation (`src/atlas/ai/models/challengers.py`). |
| **NIST AI RMF 1.0** | Govern, Map, Measure, Manage | **Govern**: Master-spec hard boundaries and role separation. **Map**: Asset-class, venue, calendar, and license provenance tracking. **Measure**: Paired block-bootstrap MAE improvement, Brier score, expected shortfall, and per-regime slicing (`evaluate_groups`). **Manage**: Challenger immutability (`auto_promoted: False`), alias rollback, and default-deny gates. |
| **IOSCO AI Supervisory Toolkit** | Financial Market AI Governance | Explainable causal regime overlays (`src/atlas/ai/models/regimes.py`), separate Competition vs Open-Market evaluation tracks (preventing cross-track score pooling), explicit transaction cost accounting, and strict prohibition of autonomous LLM order placement or risk override. |

## 3. Hard Boundaries Preserved

- Every `Forecast`, `ModelRecord`, `ResearchSignal`, `MarketDataBatch`, `RegimeState`, `WalkForwardStudyResult`, and `RuleEvaluationReport` carries `execution_permission: "none"`.
- LLMs may classify observations, draft research notes, or flag potential rule violations; they never size positions, authorize orders, override risk limits, or control the kill switch.
- Founder retains full ownership of source code, strategy logic, model artifacts, and signing keys.


## 4. ISO Financial, Market & Privacy Standards Registry

| ISO Standard | Official Specification | ATLAS Implementation |
| --- | --- | --- |
| **ISO 10383** (MIC) | https://www.iso20022.org/market-identifier-codes | Canonical Market Identifier Codes across `XNYS`, `XNAS`, `ARCX`, `XTSE`, `XCME`, `XCEC`, `XNYM` (`atlas.market.sessions`, `atlas.assets.service`). |
| **ISO 6166** (ISIN) | https://www.anna-web.org/standards/isin-iso-6166/ | 12-character alphanumeric ISIN & Luhn check-digit verification for equities, ETFs, sovereign bonds, and ETRs (`atlas.assets.service`). |
| **ISO 10962** (CFI) | https://www.iso.org/standard/81140.html | Classification of Financial Instruments distinguishing equities, ETFs, physical/allocated bullion, futures, and sovereign debt (`atlas.assets.service`). |
| **ISO 4217** (Currency & Bullion) | https://www.iso.org/iso-4217-currency-codes.html | Currency and precious metal codes (`CAD`, `USD`, `EUR`, `GBP`, `XAU`, `XAG`, `XPT`, `XPD`) with Bank of Canada daily FX conversion (`atlas.tax.boc_fetch`). |
| **ISO 20022** | https://www.iso20022.org/ | Structured financial transaction, settlement, and FINTRAC `LVCTR`/`EFTR`/`LCTR` audit record schemas (`atlas.compliance.fintrac`). |
| **ISO/IEC 27701:2019** (PIMS) | https://www.iso.org/standard/71670.html | Privacy Information Management System controls: append-only `p_consents`, 30-day DSAR SLA, 730-day RROSH breach register, and legal-hold interlocks (`atlas.compliance.privacy`). |

## 5. Privacy & Regulatory Authorities Directory

- **PIPEDA (Office of the Privacy Commissioner of Canada)**: https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/
- **Quebec Law 25 (Commission d'accès à l'information du Québec)**: https://www.cai.gouv.qc.ca/
- **CIRO (Canadian Investment Regulatory Organization)**: https://www.ciro.ca/
- **CSA / OSC (Ontario Securities Commission — NI 31-103 & NI 81-102)**: https://www.osc.ca/
- **FINTRAC (PCMLTFA Recordkeeping & s.8 No-Tipping-Off Withholding)**: https://fintrac-canafe.canada.ca/
- **SEMA (Consolidated Canadian Autonomous Sanctions List)**: https://www.international.gc.ca/world-monde/international_relations-relations_internationales/sanctions/consolidated-consolide.aspx
- **OFAC SDN (US Treasury Sanctions List)**: https://sanctionssearch.ofac.treas.gov/
- **UN Security Council Consolidated List**: https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
- **U.S. SEC EDGAR (Point-in-Time Corporate & ETF Filings)**: https://www.sec.gov/edgar/searchedgar/companysearch

## 6. Third-Party Exchanges, Benchmarks, Data Providers & Open-Source Attribution

- **Nasdaq Official Holiday & Trading Schedule (`XNAS`)**: https://www.nasdaq.com/market-activity/stock-market-holiday-schedule
- **NYSE & NYSE Arca Market Hours & Calendars (`XNYS` / `ARCX`)**: https://www.nyse.com/markets/hours-calendars
- **Toronto Stock Exchange (`TSX` / `XTSE`) Trading Hours**: https://www.tsx.com/trading/calendars-and-trading-hours
- **CME Group / COMEX / NYMEX Globex Trading Hours (`XCME` / `XCEC` / `XNYM`)**: https://www.cmegroup.com/trading-hours.html
- **LBMA (London Bullion Market Association Good Delivery & Benchmarks)**: https://www.lbma.org.uk/
- **Royal Canadian Mint (Canadian Gold & Silver Reserves ETRs `MNT.TO` / `SVR.TO`)**: https://www.reserves.mint.ca/
- **Bank of Canada Valet API (FX & Sovereign Yields)**: https://www.bankofcanada.ca/valet/docs
- **European Central Bank (ECB) Data Portal**: https://data.ecb.europa.eu/help/api/data
- **Alpaca Markets (Paper Trading & IEX Market Data)**: https://docs.alpaca.markets/docs/paper-trading
- **Databento (`GLBX.MDP3` Futures & Historical Market Data)**: https://databento.com/docs
- **Massive.com (formerly Polygon.io)**: https://massive.com/docs
- **Coinbase Exchange Public Market Data API**: https://docs.cdp.coinbase.com/exchange/docs/welcome
- **TradingView Lightweight Charts (Apache License 2.0 Attribution)**: https://www.tradingview.com/lightweight-charts/
