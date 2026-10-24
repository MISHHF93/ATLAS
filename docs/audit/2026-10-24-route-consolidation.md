# Route consolidation audit (2026-10-24, branch `atlas-routes-1` from main 8cabd13)

Scope: every frontend route (`frontend/app/**/page.tsx`), the page registry (`frontend/src/components/shell/pagesMap.ts`), header and curtain nav (`src/ui/nav.ts`), internal links, redirects, and the API each view calls. Duplicates were judged by component and data source, not by name.

## Starting state
- 53 `page.tsx` files: 13 canonical hubs and 40 stub pages that called `redirect()`, which answers 307 (temporary).
- Every internal link literal (52 unique, in `src/` and `app/`) resolves to an existing route. No 404 links were found. `/risk` was never a route or a link: the header label "Risk" points to `/control`.
- `scripts/gen-redirects.mjs` regenerated the stubs. It is now removed.

## Canonical routes and decisions

| Route | Purpose | Data source (API) | Duplicate of | Decision | Rationale |
|---|---|---|---|---|---|
| `/` Overview | Glance: P&L, room, open positions, inbox top 5 | `/api/founder/pnl`, `/api/control/state`, `/api/founder/inbox` | P&L tiles duplicated Money › Summary | **Keep canonical**; P&L strip extracted to the shared `PnlTiles` | Home summary is a different job. The tile code was copied twice, so now there is one component. |
| `/inbox` | All pending actions | `/api/founder/inbox`, `/api/founder/approvals` | Overview "Needs attention" is a top-5 preview linking here | Keep | Preview plus full list. |
| `/trade` (chart, markets, depth) | Desk chart and paper ticket, catalog, estimated book | desk/market APIs | — | Keep | Unique. |
| `/control` › Account (`/control/risk-hud`) | Equity, HWM, room, positions table, flatten | `/api/control/state` | **Positions tab** (`/trade/blotter`): same positions, same flatten button | **Merge**: Positions folded into "Account & positions" | Same data and action. Unique blotter figures (open exposure, recorded decisions, stop protection) and the richer table (side badge, ATR stop kind, track) kept. Duplicate P&L KPI and second Flatten button dropped. |
| `/control?tab=positions` | (retired tab) | — | Account | **Redirect 308** → `/control?tab=account` | Bookmarks keep working. |
| `/control` › Portfolio risk | VaR/CVaR/stress | `/api/intel/portfolio` | — | Keep | Unique. |
| `/control` › Track rules | Rulebook probes | `/api/intel/tracks` | Partial overlap with Limits (`/api/control/rulebooks`) | Keep | Probes prove enforcement; Limits shows values plus ticket check. Different job. |
| `/control` › Limits & rules | Limits plus pre-trade ticket check | `/api/control/rulebooks` | — | Keep | |
| `/autopilot` | Request on/off, shadow weeks | `/api/console/autopilot`, `/api/console/shadow` | — | Keep | |
| `/research` › Chart read | Candle read plus QM measurements | `/api/ml/chart-read`, `/api/measurements/institutional` | **Lab › Microstructure** (`/api/intel/microstructure`): liquidity/flow metrics for a symbol | **Merge**: Microstructure section added under Chart read | Same question ("what does flow/liquidity look like for this symbol"). Both tables kept: one is QM-01..08, the other tier-gated metrics. |
| `/research` › Price zones | ORB, breakout-retest, wick zones | price-action API | **Lab › Four-Box** (`/api/intel/fourbox`): same three detectors summarised as boxes | **Merge**: Four-Box section added under Price zones | Same detectors (ORB retest, breakout, wick reversal). Four-Box table kept intact. |
| `/research` › Levels & sweeps | Levels, sweeps, gold box, strategy toggles | `/api/quant/levels` | Gold opening box is related to zones but uses a different engine | Keep | Distinct engine and toggles. |
| `/research` › Forecast ledger | Vertical-slice forecasts | `/api/research/vertical-slice/*` | — | Keep | |
| `/research/evidence` (approved, ML, back-tests, training) | Model evidence and tests | `/api/console/models|evidence`, `/api/ml/*`, `/api/research/walk-forward`, `/api/ml/live-train` | Lab Experiments / Evolution are also walk-forward-based | Keep | Different datasets: the standard WF test vs lab variant runs (`/api/intel/lab/runs`) vs evolution generations (`/api/intel/evolution`). Lab "Memory & governance" shows read-only registry state, not the evidence files. Documented, not merged. |
| `/research/lab` (experiments, regimes, memory, assistant, evolution) | Research-only intel | `/api/intel/*` | microstructure, fourbox (see above) | Keep with 5 tabs | |
| `/research/lab?tab=microstructure` | (retired tab) | — | Research Chart read | **Redirect 308** → `/research?tab=chart` | |
| `/research/lab?tab=fourbox` | (retired tab) | — | Research Price zones | **Redirect 308** → `/research?tab=zones` | |
| `/money` (summary, payments, partners, tax) | Read-only money | `/api/founder/pnl`, founder data | Summary tiles = Overview tiles | Keep; shared `PnlTiles` | Summary adds equity/drawdown chart, loss bullets, ledger. |
| `/compliance` (summary, audit, identity) | Records, audit log, identity check | `/api/founder/compliance|venues`, `/api/control/state`, `/api/proctoring/*` | — | Keep | |
| `/settings` (keys, connectors) | API keys, connectors plus feed health | `/api/console/keys`, `/api/connectors`, feed health | — | Keep | |
| `/docs` | Spec reader | docs API | — | Keep | |
| `/data` (bars, reserve, capability) — advanced | Bar query, reserve plan, capability map | `/api/data/*`, `/api/strategies/reserve-yield`, features-100 | — | Keep | |

## Redirects (all 308, generated by `legacyRedirects()` in `pagesMap.ts`, wired in `next.config.ts`)
`/workbench` `/trade/cockpit` `/market` → `/trade`; `/listings` → `/trade?tab=markets`; `/trade/depth-dom` → `/trade?tab=depth`;
`/control/risk-hud` `/profile` `/trade/blotter` `/control/dealing-desk` → `/control`; `/control/rulebook` `/rules` `/configurations` → `/control?tab=limits`;
`/research/central-node` `/research/microstructure` `/research/drift-dashboard` `/matrix` → `/research`; `/research/price-action` → `/research?tab=zones`; `/research/levels` → `/research?tab=levels`; `/research/prediction-ledger` → `/research?tab=forecasts`;
`/research/walk-forward` `/experiments` → `/research/evidence?tab=walk-forward`; `/models` `/research/registry` → `/research/evidence?tab=training`;
`/payments` `/portal` `/tax` → `/money?tab=payments|partners|tax`; `/control/surveillance` `/trade/journal` → `/compliance?tab=audit`; `/control/proctoring` → `/compliance?tab=identity`;
`/keys` → `/settings`; `/data/pipelines` `/connectors` `/integrations` `/sync` → `/settings?tab=connectors`; `/data/lakehouse` `/warehouse` → `/data`; `/governance` `/data/governance` → `/data?tab=reserve`; `/data/features-100` `/roadmap` → `/data?tab=capability`;
`/control?tab=positions` → `/control?tab=account`; `/research/lab?tab=microstructure` → `/research?tab=chart`; `/research/lab?tab=fourbox` → `/research?tab=zones`.

Retired-tab redirects name the destination tab explicitly, because Next carries the source query into a bare destination and that would loop.

## Verification (box, 2026-10-24)
- `tsc --noEmit` clean; `next build` clean (13 app routes, 0 warnings); `node --test scripts/pages.test.mjs` 5/5.
- pytest (PYTHONPATH=src, 2 threads, ATLAS_FEED_DB unset): 1580 passed, 9 skipped.
- Prod server on :3417: 36 canonical URLs (each hub and tab) returned 200; 43/43 legacy addresses returned 308 to their canonical URL.
- Vertical-text check: 144/144 page/width combos (36 pages × 4 widths), 0 instances.
- Screenshots: `/workspace/shots/routes1/`.

## Left as is (documented, not merged)
- Lab Experiments / Evolution vs Models › Back-tests: all walk-forward based, but they read different datasets with different purposes.
- Track rules vs Limits & rules: overlapping topic, different evidence (probes vs values/ticket check).
- `InstitutionalWorkspacesView` still has an internal legacy-route map (AtlasTerminal lines ~597-632) for desk-internal view switching. It is not user-visible routing.
