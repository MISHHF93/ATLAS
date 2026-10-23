# Platform page consolidation — October 22, 2026

Visual comparison confirmed four overlapping page pairs. The platform now exposes
16 canonical navigation destinations. Its 23 legacy addresses redirect directly
to the relevant canonical page and are not separate application views.

| Retired view | Canonical destination | Preserved functionality |
| --- | --- | --- |
| Trade / Cockpit | Desk `/` | Symbol directory, chart, research card, risk controls, paper order ticket |
| Journal | Audit log `/control/surveillance` | Recorded orders, decisions, violation detail, audit lines |
| Open positions / Dealing desk | Positions `/trade/blotter` | Exposure, account P&L, stop protection, positions, flatten action |
| Flow read | Research `/research` | Chart research and candle measurements |

The duplicate rendering branches were removed from the workspace component.
Shell buttons resolve old workspace destinations through the same page registry
as navigation and use the canonical destination, including when leaving the
workspace shell for Desk. Existing user edits outside those retired views were
preserved.

Markets remains a symbol-information and discovery page. Risk remains an account
summary; Positions is the detailed position view. Walk-forward, Training status,
Bar query, Connectors, Reserve sleeve, and Specifications retain distinct tasks.

Validation on the rebuilt local production application:

- All 16 canonical pages returned HTTP 200 and had exactly one active nav link.
- All 23 legacy routes returned a redirect to their registered canonical page.
- No browser page errors or desktop horizontal overflow were detected.
- The mobile Desk had no horizontal document overflow.
- Research retained its Candle measurements panel.
- An internal capability-map chart button loaded Desk rather than the retired cockpit.
- Three route regression tests passed, checking address ownership, all on-disk
  page routes, direct redirects, and legacy workspace destination resolution.
- TypeScript checking and the production build passed.

Screenshots and browser results are saved locally under
`.test-runs/visual-audit/consolidated/`. The production process was restarted at
http://localhost:3000 with the consolidated build. This interface consolidation
does not change the model limitations recorded in the live-model audit.
