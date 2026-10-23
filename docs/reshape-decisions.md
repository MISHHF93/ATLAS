# Information-architecture reshape decisions (atlas-fix-1, 2026-10-23)

1. **Six sections.** Navigation groups are Home, Trade, Money, Research, Compliance, Settings
   (`frontend/src/components/shell/pagesMap.ts`). Primary pages: Home, Inbox, Money, Compliance, Docs.
2. **Founder pages are real routes.** `/inbox`, `/money`, `/payments`, `/portal`, `/tax`, `/compliance`
   are Next app pages wired to `/api/founder/*` and `/api/founder/data/{area}/{name}` (read-only whitelist).
3. **Old URLs keep working.** Every previous path remains an alias/redirect; `npm run test:routes` guards it.
4. **One Safe stop.** A single unified Safe stop (founder 2% track) replaces the duplicate kill-switch UIs;
   the founder HTTP reset is refused (403) — reset is CLI with step-up only. Prop-desk operator reset stays audited.
5. **Charts are colourblind-safe.** Okabe-Ito palette; every infographic (equity+drawdown, loss-limit bullets,
   Sankey, tax waterfall, FINTRAC timeline) ships a data table.
6. **Retired endpoints answer 410 Gone**, not 503, so they are not mistaken for outages.
7. **`/api/visuals` mounted** with 404 when no runner is active.
8. **Stale-build guard.** `server.mjs --production` rebuilds when `app/**/page.tsx` has pages missing from
   `.next/server/app-paths-manifest.json` — root cause of "That page is not in ATLAS" on an old prod build.
9. Safety unchanged: paper/simulation only, `execution_permission: none` for AI, AI can only shrink/veto.

## 2026-10-23: founder max holding period = 1 day

Owner (Masharai) decision: `position_limits.max_holding_seconds: 86400` in `config/founder/risk_policy.yaml`; sha256 pin re-generated. Paper positions opened by the setup autopilot are force-closed after 1 day. Paper only; live trading stays disabled.
