# UX consolidation (atlas-ux-3)

Goal: fewer, clearer destinations for a newcomer while keeping a professional trading-terminal feel. Paper only; Safe stop (release is CLI-only) and approval gates unchanged; every control still calls the same backend endpoint.

## Result
- Before: ~52 routes, 29 separate menu entries, 5 header dropdowns, a theme button and duplicate titles inside the desk.
- After: **11 main destinations + 1 Advanced** (`Data tools`). 39 old URLs answer `307` to the matching hub tab (verified, none 404).
- One registry (`src/components/shell/pagesMap.ts` + `src/ui/nav.ts`) drives header links, curtain, breadcrumbs, ⌘K, the 404 page and the permanent (308) redirects in `next.config.ts` (`legacyRedirects()`; no stub page files).

## Inventory (page, purpose, overlap, decision)
| Old route | Purpose | Overlap | Decision |
|---|---|---|---|
| `/` | Your paper account at a glance: balance, room left before Safe stop, open positions and today's to-dos. | — | **Kept** as hub “Overview” |
| `/inbox` | Everything waiting on you: paper approvals, payouts, policy and venue checks. | — | **Kept** as hub “Action needed” |
| `/trade` | Pick a symbol, read the chart and send a paper order. Nothing here reaches a live market. | — | **Kept** as hub “Trading desk” |
| `/workbench` | The symbol list, the price chart and the paper order ticket. | Same job as Trading desk → Chart & ticket | **Merged** → `/trade` (308) |
| `/trade/cockpit` | The symbol list, the price chart and the paper order ticket. | Same job as Trading desk → Chart & ticket | **Merged** → `/trade` (308) |
| `/market` | The symbol list, the price chart and the paper order ticket. | Same job as Trading desk → Chart & ticket | **Merged** → `/trade` (308) |
| `/listings` | Search the instrument catalog. Entries are catalog data, not a live exchange feed. | Same job as Trading desk → Market list | **Merged** → `/trade?tab=markets` (308) |
| `/trade/depth-dom` | An estimated order book built from the last close and the catalog spread. It is not a real exchange book. | Same job as Trading desk → Order book estimate | **Merged** → `/trade?tab=depth` (308) |
| `/control` | How much room the paper account has, what is open right now, and the limits that protect it. | — | **Kept** as hub “Risk & positions” |
| `/control/risk-hud` | Equity, drawdown room and open positions for the one paper account. | Same job as Risk & positions → Account | **Merged** → `/control` (308) |
| `/profile` | Equity, drawdown room and open positions for the one paper account. | Same job as Risk & positions → Account | **Merged** → `/control` (308) |
| `/trade/blotter` | Every open position, total exposure and its stop protection. | Same job as Risk & positions → Positions | **Merged** → `/control` Account & positions (308, 2026-10-24 route consolidation) |
| `/control/dealing-desk` | Every open position, total exposure and its stop protection. | Same job as Risk & positions → Positions | **Merged** → `/control` Account & positions (308, 2026-10-24 route consolidation) |
| `/control/rulebook` | The trading limits in force, plus a risk check you can run on a paper ticket before sending it. | Same job as Risk & positions → Limits & rules | **Merged** → `/control?tab=limits` (308) |
| `/rules` | The trading limits in force, plus a risk check you can run on a paper ticket before sending it. | Same job as Risk & positions → Limits & rules | **Merged** → `/control?tab=limits` (308) |
| `/configurations` | The trading limits in force, plus a risk check you can run on a paper ticket before sending it. | Same job as Risk & positions → Limits & rules | **Merged** → `/control?tab=limits` (308) |
| `/autopilot` | Ask to switch the paper setup autopilot on (owner approves), switch it off instantly, and review what it saw. | — | **Kept** as hub “Autopilot” |
| `/research` | Study price behaviour for the symbol on the desk. Research can never place an order. | — | **Kept** as hub “Market research” |
| `/research/central-node` | Candle patterns and order-flow measurements for the current symbol. | Same job as Market research → Chart read | **Merged** → `/research` (308) |
| `/research/microstructure` | Candle patterns and order-flow measurements for the current symbol. | Same job as Market research → Chart read | **Merged** → `/research` (308) |
| `/research/drift-dashboard` | Candle patterns and order-flow measurements for the current symbol. | Same job as Market research → Chart read | **Merged** → `/research` (308) |
| `/matrix` | Candle patterns and order-flow measurements for the current symbol. | Same job as Market research → Chart read | **Merged** → `/research` (308) |
| `/research/price-action` | Opening ranges, breakout-and-retest setups and wick zones. Setups are ideas, not trades. | Same job as Market research → Price zones | **Merged** → `/research?tab=zones` (308) |
| `/research/prediction-ledger` | Every recorded forecast, the data it used, and how it turned out. | Same job as Market research → Forecast ledger | **Merged** → `/research?tab=forecasts` (308) |
| `/research/evidence` | Which models the autopilot may use and the tests behind them. Unproven setups stay switched off. | — | **Kept** as hub “Models & testing” |
| `/research/walk-forward` | Run the standard walk-forward test. Passing a test does not promote a model. | Same job as Models & testing → Back-tests | **Merged** → `/research/evidence?tab=walk-forward` (308) |
| `/experiments` | Run the standard walk-forward test. Passing a test does not promote a model. | Same job as Models & testing → Back-tests | **Merged** → `/research/evidence?tab=walk-forward` (308) |
| `/models` | Train the isolated research policy on desk candles. It cannot send an order. | Same job as Models & testing → Training | **Merged** → `/research/evidence?tab=training` (308) |
| `/research/registry` | Train the isolated research policy on desk candles. It cannot send an order. | Same job as Models & testing → Training | **Merged** → `/research/evidence?tab=training` (308) |
| `/money` | Profit and loss, payments, partner holdings and tax records. Read-only: nothing here moves money. | — | **Kept** as hub “Money” |
| `/payments` | Transfers and payees. Any transfer needs two-person approval. | Same job as Money → Payments | **Merged** → `/money?tab=payments` (308) |
| `/portal` | What partners hold with the custodian: value, holdings and statements. | Same job as Money → Partner wallet | **Merged** → `/money?tab=partners` (308) |
| `/tax` | Canadian cost base (ACB), superficial losses, FX rates, T5008 and T1135. | Same job as Money → Tax | **Merged** → `/money?tab=tax` (308) |
| `/compliance` | Regulatory records, the audit trail and identity checks. | — | **Kept** as hub “Compliance” |
| `/control/surveillance` | Every order and control-plane event, as recorded. | Same job as Compliance → Audit log | **Merged** → `/compliance?tab=audit` (308) |
| `/trade/journal` | Every order and control-plane event, as recorded. | Same job as Compliance → Audit log | **Merged** → `/compliance?tab=audit` (308) |
| `/control/proctoring` | Run a typed example through the identity checklist. No camera is opened. | Same job as Compliance → Identity check | **Merged** → `/compliance?tab=identity` (308) |
| `/settings` | Access keys for agents and the data connectors this desk knows about. | — | **Kept** as hub “Settings” |
| `/keys` | Create read or research keys for agents, see each once, revoke any time. No key can trade live or move money. | Same job as Settings → API keys | **Merged** → `/settings` (308) |
| `/data/pipelines` | Data connector records. A test writes an audit line and does not open a vendor connection. | Same job as Settings → Connectors | **Merged** → `/settings?tab=connectors` (308) |
| `/connectors` | Data connector records. A test writes an audit line and does not open a vendor connection. | Same job as Settings → Connectors | **Merged** → `/settings?tab=connectors` (308) |
| `/integrations` | Data connector records. A test writes an audit line and does not open a vendor connection. | Same job as Settings → Connectors | **Merged** → `/settings?tab=connectors` (308) |
| `/sync` | Data connector records. A test writes an audit line and does not open a vendor connection. | Same job as Settings → Connectors | **Merged** → `/settings?tab=connectors` (308) |
| `/docs` | The specifications this desk is built from, in plain reading form. | — | **Kept** as hub “Help & docs” |
| `/data` | Specialist tools: raw bar queries, the reserve plan and the capability map. | — | **Kept** as hub “Data tools” |
| `/data/lakehouse` | Load closed price bars for the symbol on the desk. | Same job as Data tools → Bar query | **Merged** → `/data` (308) |
| `/warehouse` | Load closed price bars for the symbol on the desk. | Same job as Data tools → Bar query | **Merged** → `/data` (308) |
| `/governance` | Load the paper reserve plan. It does not send an order. | Same job as Data tools → Reserve plan | **Merged** → `/data?tab=reserve` (308) |
| `/data/governance` | Load the paper reserve plan. It does not send an order. | Same job as Data tools → Reserve plan | **Merged** → `/data?tab=reserve` (308) |
| `/data/features-100` | A map of 100 desk ideas, each linked to the page that actually runs it. | Same job as Data tools → Capability map | **Merged** → `/data?tab=capability` (308) |
| `/roadmap` | A map of 100 desk ideas, each linked to the page that actually runs it. | Same job as Data tools → Capability map | **Merged** → `/data?tab=capability` (308) |

## New information architecture
| Group | Destination | Tabs | One-line explanation |
|---|---|---|---|
| home | **Overview** `/` | — | Your paper account at a glance: balance, room left before Safe stop, open positions and today's to-dos. |
| home | **Action needed** `/inbox` | — | Everything waiting on you: paper approvals, payouts, policy and venue checks. |
| trade | **Trading desk** `/trade` | Chart & ticket · Market list · Order book estimate | Pick a symbol, read the chart and send a paper order. Nothing here reaches a live market. |
| trade | **Risk & positions** `/control` | Account & positions · Portfolio risk · Track rules · Limits & rules | How much room the paper account has, what is open right now, and the limits that protect it. |
| trade | **Autopilot** `/autopilot` | — | Ask to switch the paper setup autopilot on (owner approves), switch it off instantly, and review what it saw. |
| research | **Market research** `/research` | Chart read · Price zones · Forecast ledger | Study price behaviour for the symbol on the desk. Research can never place an order. |
| research | **Models & testing** `/research/evidence` | Approved models · Back-tests · Training | Which models the autopilot may use and the tests behind them. Unproven setups stay switched off. |
| money | **Money** `/money` | Summary · Payments · Partner wallet · Tax | Profit and loss, payments, partner holdings and tax records. Read-only: nothing here moves money. |
| compliance | **Compliance** `/compliance` | Summary · Audit log · Identity check | Regulatory records, the audit trail and identity checks. |
| settings | **Settings** `/settings` | API keys · Connectors | Access keys for agents and the data connectors this desk knows about. |
| settings | **Help & docs** `/docs` | — | The specifications this desk is built from, in plain reading form. |
| Advanced | **Data tools** `/data` | Bar query · Reserve plan · Capability map | Specialist tools: raw bar queries, the reserve plan and the capability map. |

## Header
Left: Menu (opens the all-pages curtain) · ATLAS · **PAPER** badge. Centre: Trade · Risk · Research · Money · Compliance. Right: Search (⌘K) · Action needed · **Safe stop** pill · Account menu (Limits & rules, Settings & API keys, Help & docs, theme). PAPER, Safe stop and the account menu are visible at every width.

## Page pattern
Every destination uses `Hub`: eyebrow (group) → plain-language title → one-line explanation → tabs (server links, `?tab=`; default tab has the bare URL) → one-line tab description → panel. Only the selected tab renders, so hidden tabs make no requests. Empty/loading/error states use the shared `ux-state` / `ux-loading` components.

## Visual system (v3)
- Calmer palette: deeper neutral surfaces, flat cards with borders (no dark shadows), one accent (sky) for active/primary; colour otherwise reserved for P&L, warnings and Safe stop.
- Type scale 11/12/13/14/16/20/22/26; monospace only for figures and codes; tabular numbers in tables.
- 4 px spacing grid; radii 4/6/8; denser tables (8 px rows, uppercase 11 px headers) and cards.
- Header in three zones with underline active state; one primary button per page header.

## UX-4: readable cards and no vertical text (atlas-ux-4)

- Shared `AssetCard`/`AssetTable` (`src/components/market/AssetCard.tsx`) on Markets; the Trading desk watchlist uses the same hierarchy: symbol and name, large price, change, then a quote-status pill with source and time. Secondary metrics are collapsed in `<details>`. Quote status stays honest (live/delayed/market_closed/stale/no_data); no prices are invented.
- Markets catalog: the card grid comes first (auto-fill minmax 280px, Cards/List toggle). Desk context, the symbol profile and the TradingView widgets are collapsed or lazy, so no iframes load until asked (before: 22 iframes, page over 14,000px tall).
- Global CSS: no `overflow-wrap:anywhere`; table cells are nowrap inside horizontally scrolling containers; docs tables keep a 14ch minimum width; labels truncate with an ellipsis.
- Guard: `npm run check:vertical-text -- <baseUrl>` (Playwright) scans 14 pages at 1440/1024/768/390 and fails on any vertical text. It found 187 instances before this work and finds 0 after.

## 2026-10-24 route consolidation (atlas-routes-1)
See `docs/audit/2026-10-24-route-consolidation.md`. Positions merged into Account & positions; Lab Microstructure → Research Chart read; Lab Four-Box → Research Price zones; every legacy address is a 308 from `next.config.ts`.


## evo-10 consolidation (7 pages)

| Old route | New location | Reason |
|---|---|---|
| `/inbox` | `/?tab=inbox` | same "home to-dos" job as the Overview card |
| `/autopilot` | `/control?tab=autopilot` | the paper control switch sits next to the risk limits |
| `/research/evidence` (+ `?tab=evidence/ml/walk-forward/training`) | `/research/lab?tab=...` | models and evidence are one workflow with the lab |
| `/research?tab=forecasts` | `/research/lab?tab=forecasts` | forecasts are lab output |
| `/research?tab=multi-agent`, `/research/lab?tab=agents` | `/research?tab=agents` | duplicate agent pipelines merged |
| `/research/lab?tab=valuation`, `?tab=options` | `/research?tab=valuation`, `?tab=options` | market research lives with the chart |
| `/compliance` (+ `?tab=overview/audit/identity`) | `/money?tab=regulatory/audit/identity` | compliance is part of the money page |
| `/data` (+ `?tab=bars/reserve/capability`) | `/settings?tab=bars/reserve/capability` | data plumbing is settings |
| `/docs` | `/settings?tab=docs` | reference material belongs in settings |
| `/trade/journal`, `/research/registry`, `/research/prediction-ledger`, `/data/lakehouse` | `/money?tab=audit`, `/research/lab?tab=training`, `/research/lab?tab=forecasts`, `/settings?tab=bars` | older aliases re-pointed |

Removed dead components: `ChartTrainStrip`, `ChartLockRail`. Still present and flagged: `PumpIntelligenceView` (unmounted since the `/trade?tab=pump` merge; the `/api/pump` backend remains).

### /trade layout (evo-10)

At 100% zoom `/trade` has zero nested scroll containers at 1920x1080 and 1366x768 in its default state. The symbol list is paged (Prev/Next), the ticket is a single Order / Risk room card at heights below 1000px, and long content (chart layers, model details, notes, blotter tables) opens as a popover over the chart, so the chart takes the remaining height. An opened popover can scroll.
