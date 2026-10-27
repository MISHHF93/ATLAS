# ATLAS Cross-Session AI Handoff Protocol

Live machine-readable handoffs are persisted in `var/research/session_handoffs.json` and served via `GET /api/research-integration/handoffs`.

## Resumption Checklist
1. Read `docs/atlas/PROJECT_CONTEXT.md` and `docs/atlas/DECISIONS.md`.
2. Query `GET /api/research-integration/handoffs` and verify `VERIFIED_REPOSITORY_STATE.consistency_status == "VERIFIED_CONSISTENT"`.
3. Inspect `git status` and `git log -n 5`.
4. Run `.\\.venv\\Scripts\\python.exe -m pytest tests/test_complete_system_verification.py tests/test_research_integration.py -v`.
5. Run `cd frontend && node --test scripts/one-chart.test.mjs scripts/pages.test.mjs`.

