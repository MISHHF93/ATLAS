# Design research: modern fintech dashboards and infographics (2025–2026)

Done 2026-10-17 for the owner console (`trading-bot-app/console`). It covers web research, the patterns we adopted, and
the chart chosen for each data set. Everything is rendered offline in vanilla SVG (`static/js/charts.js`). There's no
CDN and no third-party chart library: the eight chart types we need are small, and a vendored library would add more
weight and licence tracking than it saves.

## 1. What current products do

| Product / source | Pattern we take |
|---|---|
| Wealthsimple redesign: separate Home (total wealth), Spend and Invest tabs, with account tiles that drill down ([product news](https://product-news.wealthsimple.com/meet-our-re-designed-wealthsimple-app-appui)) | Home shows one total picture; Trading and Money are separate sections; tiles open details |
| Analysis of 9 fintech dashboards (Mercury, Stripe, Ramp, Brex, Wise, Revolut) ([adminlte.io, 2026](https://adminlte.io/blog/fintech-dashboard-design-examples/)) | "Visual calm (trust reads as restraint)", tabular figures, **colour reserved for financial state**, explicit pending/in-flight states, **work queues over chart walls** (Ramp), exception-first (Brex), dark mode a requirement for trading |
| Stripe / Mercury breakdowns ([925studios](https://www.925studios.co/blog/stripe-dashboard-design-breakdown), [LlamaPress](https://llamapress.ai/patterns/exemplar-stripe), [Mercury DESIGN.md](https://github.com/rohitg00/awesome-claude-design/blob/main/design-md/warm/mercury.md)) | Right-aligned amounts in tabular numerals, hairline row separators, sticky headers, one accent colour for actions, quiet surfaces, shallow navigation |
| Linear "calmer interface" refresh ([Linear](https://linear.app/now/behind-the-latest-design-refresh), [part II](https://www.linear.app/now/how-we-redesigned-the-linear-ui), [theme system](https://www.thedjpetersen.com/llm-thoughts/linear-theme/)) | Less visual noise, softer borders, dimmer navigation, fewer icons, warmer neutrals; themes derived from a few variables (base, accent, contrast) → our token set |
| Trading UX patterns ([reasonthread](https://reasonthread.com/en/articles/user-experience-patterns-for-desktop-and-mobile-trading-interfaces), [edgeful redesign](https://www.edgeful.com/blog/posts/edgeful-dashboard-upgrade)) | Show risk, cost and status at the moment of decision; remove clicks; most relevant data first; execution/connectivity status always visible |
| Fintech data-viz overview ([Merge Rocks](https://merge.rocks/blog/fintech-dashboard-design-or-how-to-make-data-look-pretty)) | Line charts for value over time, calendar heatmaps for daily activity, chart-per-card grid that stacks on mobile, tooltips instead of crowded labels |
| Koyfin model portfolios: performance chart **plus a drawdown chart** ([Koyfin help](https://www.koyfin.com/help/model-portfolios/)) | Equity curve with an underwater (drawdown) panel below it, on a shared time axis |
| Carta LP portal: self-service capital account, NAV, statements, documents, tax, mobile ([Carta reporting](https://carta.com/learn/private-funds/management/portfolio-management/investor-reporting/), [LP mobile](https://releasenotes.carta.com/limited-partner-mobile-experience-24xOGk), [new investor design](https://carta.com/blog/updated-investor-design/)) | Portal leads with the capital account (units × NAV), NAV history, then requests and documents |

## 2. Data-visualisation guidance

- **FT Visual Vocabulary** ([interactive](https://ft-interactive.github.io/visual-vocabulary/), [poster PDF](https://raw.githubusercontent.com/Financial-Times/chart-doctor/main/visual-vocabulary/Visual-vocabulary-en.pdf)): choose by relationship.
  - Change over time: line/area (equity, NAV).
  - Deviation: underwater drawdown.
  - Part to whole: donut or stacked bar (sleeves).
  - Magnitude: bars (exposure).
  - Flow: Sankey (money flows).
  - Ranking: ordered bars (decision funnel).
- **Tufte** ([sparklines](https://www.edwardtufte.com/notebook/sparklines-history-by-tufte-1324-to-now/), [executive dashboards](https://www.edwardtufte.com/notebook/executive-dashboards/); Few on [scaling sparklines](https://www.perceptualedge.com/articles/visual_business_intelligence/best_practices_for_scaling_sparklines.pdf)): high data-ink, no chart junk, sparklines next to the number with a consistent scale, and avoid gauges when history matters.
- **IBCS** ([SAP IBCS rules](https://www.sap.com/design-system/sac-dashboard-design-best-practices/resources/ibcs), [IBCS on bullet graphs](https://www.ibcs.com/resource/ibcs-evaluation-bullet-graphs/), [variance notation](https://github.com/OptIn-Admin/ibcs-standards/blob/main/docs/09-unify.md)): bullet graphs instead of dial gauges; a marker for the limit; variances signed (+/−) and coloured good/bad, not by sign alone. → Loss limits use **bullet charts** (used vs limit, with a 75% warning band, as in TRD §10).
- **Datawrapper on colour** ([colourblind part 2](https://www.datawrapper.de/blog/colorblindness-part2), [part 1](https://www.datawrapper.de/blog/colorblindness-part1), [choosing colours](https://www.datawrapper.de/blog/colors)): "blue is the safest hue"; pair blue with orange/vermillion; vary lightness ("get it right in black and white"); avoid red/green pairs of equal lightness; grey for context; direct labels and patterns instead of colour alone.
- **Okabe–Ito palette** ([reference](https://siegal.bio.nyu.edu/color-palette/), [see package](https://easystats.github.io/see/reference/okabeito_colors.html)): series colours `#0072B2` blue, `#E69F00` orange, `#009E73` bluish green, `#56B4E9` sky, `#D55E00` vermillion, `#CC79A7` reddish purple, with amber `#F5C710` in place of yellow on light backgrounds. Gains and losses are never shown by colour alone: there's always a +/− sign and an arrow.
- **Accessibility of charts** ([W3C WAI complex images](https://www.w3.org/WAI/tutorials/images/complex/), [WAI tables](https://www.w3.org/WAI/tutorials/tables/), [Observable Plot accessibility](https://observablehq.com/plot/features/accessibility)): each chart is an `<svg role="img">` with an `aria-label` summary and a "Show data" disclosure holding a real `<table>` (caption, `th scope`). We never use `display:none` for the only text alternative.

## 3. Chart chosen for each data set

| Data | Chart | Why |
|---|---|---|
| Bot equity history | Area line + **underwater drawdown** strip | Koyfin pattern; drawdown is the risk view the BRD cares about (MDD gate) |
| Daily / weekly / drawdown loss limits | **Bullet charts** (used, 75% warning band, limit marker) | IBCS/Few replacement for gauges |
| Sleeves 60/30/10 actual vs target | **Donut** with target ticks, plus a drift table | Part to whole with only 3 parts |
| Exposure by asset class / currency | Horizontal **bars** sorted by size | Magnitude; easy to read labels |
| Daily P&L | **Calendar heatmap** (diverging blue/orange, signed tooltips) | Daily pattern at a glance; colourblind-safe diverging pair |
| Money flows | **Sankey** (bank → broker → sleeves; investor → admin trust → fund → custodian) | FT "flow"; shows that money never passes through the app |
| NAV per unit | **Sparkline** with the last value labelled | Tufte |
| Reconciliation | **Status strip** (matched / breaks) with counts | Exception-first |
| Onboarding states | **Funnel** (horizontal bars: applied → KYC → approved → funded) | Ranking/flow of a pipeline |
| FINTRAC deadlines | **Timeline** (today marker, due dates, overdue in vermillion) | Time-to-deadline |
| Tax year | **Waterfall-style bars**: proceeds, ACB, gains, denied losses, allowable | Shows how the taxable figure is built up |
| Decision pipeline | **Funnel** signals → dropped at cost / news / risk → submitted | Explains where ideas die |
| Market sessions | **World clock strip**: 24-hour bars per venue with a "now" line | Follow-the-sun at a glance |

## 4. Design system decisions

- **Tokens**: 4-px spacing scale, radii 6/10/14, elevation in 3 steps, type scale 12/13/14/16/20/24/30 px, and a system font stack (no web-font download; Inter is used only if installed locally). `font-variant-numeric: tabular-nums` on every number.
- **Colour**: neutral slate surfaces; one indigo-blue accent for actions; state colours (ok/warn/bad/info) only for state; chart colours from Okabe–Ito. Light and dark themes are both tuned to WCAG AA (checked by `console/tools/contrast_check.py`).
- **Motion**: 120–200 ms transitions and skeleton shimmer, all switched off under `prefers-reduced-motion`.
- **Layout**: on every page a summary infographic band comes first, then one primary action, then the detail table. Secondary details go in drawers or "More".
