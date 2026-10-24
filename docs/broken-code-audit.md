# Broken-code audit — atlas-fix-1 (2026-10-23)

Method: (a) import every module under `src/atlas` (`import_all.py`), `compileall` + `ruff` (F821/F811/F841/F401),
call every FastAPI route with TestClient (`route_sweep.py`); (b) `next build`, `tsc`, headless Chrome crawl of every
route and nav link (console errors, failed `/api` calls, "That page is not in ATLAS", empty panels);
(c) README / docs / roadmap CSV/xlsx "Implemented" claims checked against code and routes.

| item | location | symptom | fix | status |
|---|---|---|---|---|
| Founder pages missing | `frontend/app/{inbox,money,payments,portal,tax,compliance}` | "That page is not in ATLAS" | Real pages wired to `/api/founder/*` + `/api/founder/data/*`; nav Money group | fixed |
| Stale prod build | `frontend/server.mjs` | new pages 404 on old `.next` | Stale-build guard rebuilds when manifest lacks pages | fixed |
| Founder data API absent | `src/atlas/api/founder_data.py` | pages had no data | Read-only whitelisted router, `execution_permission: none`; 39 tests | fixed |
| Undefined names (F821) | gateway.py, zones.py, whale_policy.py, backtester.py, memory.py, coordinator.py, runner.py | NameError at runtime paths | Added imports / TYPE_CHECKING imports | fixed |
| Py3.11-unsafe f-string | `recipes.py:535` | SyntaxError on 3.11 | Rewritten with `format()` | fixed |
| `api/visuals.py` broken | imported nonexistent `get_coordinator` | dead module, unmounted | Rebuilt, mounted at `/api/visuals`, 404 without runner; test added | fixed |
| Runner never registered coordinator | `runner.py` | visuals always empty | `register_coordinator()` call | fixed |
| Duplicate import | `app.py` ~2493 (`verify_role_action`) | F811 | removed | fixed |
| Retired endpoints 503 | `app.py` perfect-trader, visual-scan, advanced-ml | looked like outages (5xx) | answer 410 Gone; tests updated | fixed |
| Duplicate Safe stops | control UI / founder HUD | two kill switches, inconsistent | One unified Safe stop, founder 2% track | fixed |
| Money trial balance | `views.tsx` | list rendered as object (0.00 rows) | Ledger accounts table | fixed |
| Sankey layout | `Charts.tsx` | pass-through nodes misdrawn, huge fonts | 3-column layout, capped height | fixed |
| Roadmap CSV malformed | `docs/ATLAS_MASTER_ROADMAP.csv` PKG-LAKE/PKG-LWC | unquoted comma shifted columns | quoted | fixed |
| Overclaim: AUTO-01..10 | roadmap CSV | "Implemented" but endpoint retired | status → Retired | fixed |
| Overclaim: README platform map | `README.md` | old routes/scanner/live claims | Status-correction note (6 sections, retired, paper-only) | fixed |
| `_live_submit` NotImplementedError | `ledgers/providers.py` | stub | Intentional: live money disabled | by design |
| TSFM base `predict` | tsfm base | abstract | Intentional abstract base | by design |
| Unused vars/imports | F841×4, F401≈100 | lint only | not behavioural | open (cleanup) |
| TradingView widget fetch errors | `/listings`, `/trade/depth-dom` | third-party `widget-sheriff`/`/support` fetches fail offline | external iframe, not ATLAS code | n/a |

## Final re-run
- Python imports: 366 modules, **0 import errors**.
- Route sweep: 49 GET + 39 write routes, **0 5xx**.
- Frontend: `next build` exit 0, `tsc` clean, `test:routes` 3/3.
- Crawl: 23 pages, **0 ATLAS errors**, 0 failed `/api` calls, 0 "not in ATLAS" (only third-party TradingView fetches).
- pytest: **1310 passed, 9 skipped, 0 failed** at the time of this audit. Current main (2026-10-23 integration): 1447 passed, 9 skipped.
