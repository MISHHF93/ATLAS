# ATLAS documentation index

Last verified: **2026-10-23** against `main@c87ef50`, where pytest gives 1404 passed and 9 skipped. Everything runs on paper or simulation only.

Status vocabulary, used here and in the root workbook:

- **Implemented+tested**: the code and its tests are on main. This says nothing about trading performance.
- **Partial**
- **Experimental**: code exists, but its validation gates failed or were never run.
- **Blocked**
- **Planned**
- **In progress (branch X)**: the work is not on main yet.

The row-by-row status matrix is the root workbook `ATLAS Platform Master Roadmap & Technical Specifications (A-Z).xlsx`. Its "Changelog & Legend" sheet records each change.

## Start here: governing spec and current truth

| Doc | What it is | Current? |
|---|---|---|
| [spec/master-wrapper-summary.md](spec/master-wrapper-summary.md) | Condensed master wrapper spec (owner directive 2026-10-23), the governing spec | yes |
| [spec/audit-and-gap.md](spec/audit-and-gap.md) | Phase-1 audit and gap map, with status per spec area | mostly. Baseline count (1308) predates slices 4–5. It says "no HMM", but `models/quant/regime.py` has one |
| [spec/price-action.md](spec/price-action.md) | Price-action package spec, slices 1–5: engine, predict(), EV gate, replay, evidence, autopilot, shadow, prior-day detector, selector | yes |
| [spec/evidence/price-action-setups-2026-10-23.md](spec/evidence/price-action-setups-2026-10-23.md) (+ `.json`) | Real-data setup evaluation. **All 21 configs failed the gates; no model registered** | yes |
| [spec/evidence/technique-selector-2026-10-23.md](spec/evidence/technique-selector-2026-10-23.md) (+ `.json`) | 15m selector and range-break hypothesis. **The selector failed, and the claim is unproven** | yes |
| [api-and-mcp.md](api-and-mcp.md) | API keys, paper autopilot routes, localhost MCP endpoint | yes |
| [reshape-decisions.md](reshape-decisions.md) | IA decisions (6 sections, one Safe stop, 410 Gone) and the **founder max holding of 1 day (owner, 2026-10-23)** | yes |
| [ux-audit.md](ux-audit.md) | Frontend UX audit and overhaul (tokens, AppShell, route registry) | yes. The curtain nav that replaces the sidebar is in progress on `atlas-ux-2` |
| [broken-code-audit.md](broken-code-audit.md) | Import, route and crawl audit with fixes | yes. Its final test count (1310) predates slices 4–5 |
| [lola-port-plan.md](lola-port-plan.md) | Lola → ATLAS port: founder capital track, 2% Safe stop, tax, ledgers | yes |

## Work in progress (not on main)

| Area | Branch | Notes |
|---|---|---|
| Curtain navigation, functional console UI (autopilot, Safe stop, API keys, approvals, evidence), responsive grids | `atlas-ux-2` | The branch is 9 commits ahead of main. |
| TradingView widgets, UDF and Lightweight Charts | `atlas-tv-1` | The branch had no commits ahead of main when checked. Main already has `api/udf.py` and `marketdata/tradingview.py`. |
| One authoritative ATLAS feed and provider adapter library | `atlas-feeds-1` | The branch had no commits ahead of main when checked. Main uses public Yahoo, Binance and Coinbase bars. |

## Product and architecture (background; older wording)

These documents describe the target or vision. Some of their claims are **not** implemented: live trading, Databento/Polygon/BigQuery feeds, and anything described as "Live" or "Executed Directly". Trust the spec and evidence documents above, and the workbook, over these.

| Doc | Last changed |
|---|---|
| [ATLAS_MASTER_SPEC.md](ATLAS_MASTER_SPEC.md): product, authority, tracks, non-custodial boundaries | 2026-10-20 |
| [ATLAS_PRODUCT_VISION.md](ATLAS_PRODUCT_VISION.md): long-form vision | 2026-10-23 |
| [ADVANCED_ML_INFRASTRUCTURE.md](ADVANCED_ML_INFRASTRUCTURE.md): ML infrastructure notes (its endpoints are retired and answer 410) | 2026-10-23 |
| [architecture/CURRENT_STATE.md](architecture/CURRENT_STATE.md): state as of 2026-10-21, before the 6-section IA | 2026-10-22 |
| [architecture/TARGET_STATE.md](architecture/TARGET_STATE.md) | 2026-10-19 |
| [architecture/EXECUTION_PLAN.md](architecture/EXECUTION_PLAN.md) | 2026-10-22 |
| [architecture/DECISIONS.md](architecture/DECISIONS.md): decisions 1–43 | 2026-10-20 |
| [architecture/RESEARCH_OPERATING_CONTRACT.md](architecture/RESEARCH_OPERATING_CONTRACT.md): research gates and rulebook fields (cited by `control/engine.py`) | 2026-10-19 |
| [architecture/ISO_GOVERNANCE_ALIGNMENT.md](architecture/ISO_GOVERNANCE_ALIGNMENT.md): standards alignment (a mapping, not a certification) | 2026-10-19 |
| [architecture/INTEGRATION_MATRIX.md](architecture/INTEGRATION_MATRIX.md) | 2026-10-19 |
| [architecture/LIVE_AUDIT_INTAKE.md](architecture/LIVE_AUDIT_INTAKE.md) | 2026-10-19 |
| [architecture/UNIVERSAL_AI_ECOSYSTEM.md](architecture/UNIVERSAL_AI_ECOSYSTEM.md) | 2026-10-19 |
| [architecture/UNIFIED_INTELLIGENCE_ASSESSMENT.md](architecture/UNIFIED_INTELLIGENCE_ASSESSMENT.md) | 2026-10-23 |
| [architecture/VISION_GAP_ANALYSIS.md](architecture/VISION_GAP_ANALYSIS.md) | 2026-10-23 |
| [backlog/AGILE_BACKLOG.md](backlog/AGILE_BACKLOG.md) | 2026-10-21 |

## Roadmap exports

`roadmap/tab*.csv` are exported by `src/atlas/whale_saas_az.export_master_roadmap_csvs` from constants in that file. `ATLAS_MASTER_ROADMAP.csv` was partly corrected in atlas-fix-1. Both still carry "Implemented" and "Executed Directly (Live)" labels that the code does not support. The verified statuses are in the root workbook.

- [roadmap/range_garden.md](roadmap/range_garden.md): paper harvest of a proven range
- [roadmap/reserve_yield.md](roadmap/reserve_yield.md): reserve-yield sleeve

## Research notes (dated; point-in-time)

- [research/PRICE_ACTION_FRAMEWORK.md](research/PRICE_ACTION_FRAMEWORK.md)
- [research/TRADER_KIM_FRAMEWORK.md](research/TRADER_KIM_FRAMEWORK.md): hypotheses, not validated
- [research/EVIDENCE_ROADMAP.md](research/EVIDENCE_ROADMAP.md)
- [research/experiments/EXP_001_BASELINE_VS_SCRATCH_TREE.md](research/experiments/EXP_001_BASELINE_VS_SCRATCH_TREE.md)
- 2026-10-22 audits:
  - [CHART_MODEL_FLOW](research/CHART_MODEL_FLOW_2026-10-22.md)
  - [LIVE_CAPTURE_AUDIT](research/LIVE_CAPTURE_AUDIT_2026-10-22.md)
  - [LIVE_CHART_REPAIR](research/LIVE_CHART_REPAIR_2026-10-22.md)
  - [LIVE_MODEL_AUDIT](research/LIVE_MODEL_AUDIT_2026-10-22.md)
  - [MODEL_RUNTIME_INTEGRATION](research/MODEL_RUNTIME_INTEGRATION_2026-10-22.md)
  - [NATIVE_API_VIEW](research/NATIVE_API_VIEW_2026-10-22.md)
  - [NAVIGATION_AUDIT](research/NAVIGATION_AUDIT_2026-10-22.md)
  - [REALTIME_OBSERVER](research/REALTIME_OBSERVER_2026-10-22.md)
  - [RESPONSIVE_VISUAL_AUDIT](research/RESPONSIVE_VISUAL_AUDIT_2026-10-22.md)
- Reviews:
  - [research/AI_ECOSYSTEM.md](research/AI_ECOSYSTEM.md)
  - [research/MCP_DATA_INTEGRATION.md](research/MCP_DATA_INTEGRATION.md)

## Lola research (imported 2026-10-23)

- [audit](lola-research/audit.md)
- [review](lola-research/review.md)
- [plan-conformance](lola-research/plan-conformance.md)
- [page-by-page](lola-research/page-by-page.md)
- [design-research](lola-research/design-research.md)
- [implementation-research](lola-research/implementation-research.md)
- [strategy-research-2](lola-research/strategy-research-2.md)
- [ai-transformers-research](lola-research/ai-transformers-research.md)
- [mcp-autopilot-research](lola-research/mcp-autopilot-research.md)
- [recipe-search](lola-research/recipe-search.md)
- [hedge-fund-addendum](lola-research/hedge-fund-addendum.md)
- [banking-standards](lola-research/banking-standards.md)
- [wallet-research](lola-research/wallet-research.md)

## Other

- [../frontend/ATLAS_AUDIT.md](../frontend/ATLAS_AUDIT.md): repository audit, 2026-10-21 (historical)
