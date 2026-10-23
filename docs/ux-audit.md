# ATLAS frontend UX audit (2026-10-23)

Scope: every route in `frontend/app`, each captured at 1440×900 and 390×844 (`/workspace/shots/ux-before/`, with
`report.json` holding console errors and non-2xx responses per route). The same crawl was rerun after the overhaul
(`/workspace/shots/ux-after/`).

## Top findings (before)

| # | Severity | Finding | Where |
|---|----------|---------|-------|
| 1 | High | **No information architecture.** A two-row top bar holds 20+ links with equal weight: Desk, Markets, Inbox, Estimated depth, Positions, Risk, Rulebook, Money, … Docs. There is no grouping, active section, breadcrumb or search, and on mobile the bar wraps or clips. | `AppNav` on every page |
| 2 | High | **Home is the trading desk.** `/` opened a dense three-panel terminal with no summary of the day: P&L, room before Safe stop and items needing attention were all missing. | `/` |
| 3 | High | **Raw data dumps.** Money listed `remaining_room` as about 20 snake_case key/value rows (`daily drawdown fraction 0.010204`). Founder tables printed raw JSON. | `/money`, founder pages |
| 4 | High | **Error text shown to users.** Pages printed `Unavailable: HTTP 404. Seed demo data…` whenever founder data wasn't seeded, and each page fired 3–4 failing `/api/founder/data/*` requests, all 404s in the console. | money, payments, portal, tax, compliance, inbox |
| 5 | High | **Inconsistent safety wording.** The same control appeared as "Halt paper trading", "Kill switch", "Engage Emergency Kill Switch" and "Safe stop". The 4% competition breaker and the 2% founder Safe stop were not distinguished. | terminal, studio, listings, founder |
| 6 | Medium | **No persistent PAPER indicator.** Paper-only status was buried in body copy. The header showed a role selector ("B2B Enterprise Prop Operator") but nothing saying the account is simulated. | global |
| 7 | Medium | **Hardcoded colours.** The desk used about 150 inline hex/rgba values (`#070A0F`, `#00F29D`, `#FF3B69`) outside any token system, with neon red/green that is not colour-blind safe. There was no light theme. | `StreamlinedTradingStudio`, `AtlasTerminal` |
| 8 | Medium | **Duplicate chrome.** Terminal pages rendered the global nav plus their own header and an Equities/Competition toggle, so the content started about 150px down. | terminal routes |
| 9 | Medium | **Layout bugs.** The desk root used `height: 100vh` inside a page that also had a nav, causing double scrollbars and clipping. `body { overflow: hidden }` hid content on short or mobile viewports. | studio, `globals.css` |
| 10 | Medium | **No standard states.** Loading was plain "Loading..." text, with no empty, offline or stale states and no retry. A dead backend left half-rendered pages. | all data views |
| 11 | Low | **Mixed type.** Monospace was used for prose, and font sizes ran from 10.5 to 22px with no scale. | global |
| 12 | Low | **The 404 page had no route back** other than the overloaded nav. | `not-found` |
| 13 | Low | **Home never reached network idle** because it polled every second. Not a bug, but it makes automated checks slower. | `/` |

Accessibility gaps seen: no skip link; several icon-only controls had no accessible name; colour-only status in
tables (green/red text); low-contrast muted text (#64748B on #070A0F ≈ 3.9:1); no `lang` region for en-CA.

## What changed

* **Design tokens** (`frontend/src/ui/tokens.css`) define colour, spacing, radius and type scales in dark and light
  themes. Status colours come from the Okabe-Ito palette. A bridge remaps the legacy `--bg-*`, `--text-*` and
  `--accent-*` variables so older views pick up the theme.
* **AppShell** (`frontend/src/ui/AppShell.tsx`):
  * The header has the logo, a ⌘K / Ctrl+K command palette, a permanent **PAPER** badge, a **Safe stop** pill
    (live, links to Account), a theme toggle and an account menu.
  * The sidebar is collapsible and holds 6 sections (Home, Trade, Money, Research, Compliance, Settings) with
    their subpages. On mobile it becomes a drawer.
  * Breadcrumbs, a skip link, an offline/backend-down banner with Retry, and a **"Safe stop active"** banner.
* **Single route registry** (`pagesMap.ts` → `ui/nav.ts`) drives the nav, breadcrumbs, palette and 404 page.
  Legacy aliases (`/workbench`, `/market`, `/trade/cockpit`) redirect to `/trade`. `scripts/pages.test.mjs`
  enforces this.
* **Shared primitives** (`ui/primitives.tsx`): PageHeader, Card, StatTile (with an accessible meter), DataTable,
  Badge, EmptyState, ErrorState, LoadingSkeleton, StaleNote, `Async` and a `useApi` hook that keeps the last good
  data and flags it stale.
* **Pages:**
  * `/` is a new Overview dashboard: equity, today, since start, room before Safe stop, open paper positions and
    the inbox preview. It uses real API data only.
  * `/trade` is the trading desk.
  * Money, Payments, Partner wallet, Tax, Compliance and Inbox were rebuilt with tiles and tables. Founder views
    check `GET /api/founder/data/status` first and show an empty state with the seed command instead of 404s.
* **Wording:** "Safe stop" is used everywhere. The investor portal is now "Partner wallet", described as a
  read-only view of money the partner custodian holds.
