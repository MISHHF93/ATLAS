# Repo audit 2026-10-24 (base `main` 69e2baf)

## Test baseline before this branch
- `pytest -x` stopped at 1 failure, with 1181 passed and 9 skipped. Output: `/workspace/shots/baseline_pytest.txt` (box only).
- The failure is pre-existing and unrelated: `tests/test_library_quotes.py::test_quote_route_stays_off_under_pytest_and_does_not_rewrite_the_directory` (assert 3 == 0).

## What existed
| Area | Location | Status |
|---|---|---|
| Price-action engine (live update / batch replay) | `features/price_action/engine.py` | present |
| ORB retest, dual band, wick reversal, prior-day range reversal | `detectors.py`, `prior_day.py` | present (legacy, enabled) |
| Conservative OHLC replay | `replay.py` | present |
| Meta-label ML (purged WF, isotonic, conformal) | `src/atlas/ml/` | present |
| NYSE/FX/crypto calendars | `marketdata/pit/calendars.py` | present; no CME holidays |
| Control plane | `control/engine.py` | present (sole order authority) |

## What was missing, and what this branch did
| Gap | Action |
|---|---|
| CME/COMEX holiday calendar | added (`calendar.py`) |
| Level registry with availability timestamps | added |
| Shared interaction engine | added |
| SFP | added |
| Gold box/ORB/snapback | added |
| HTF bias | added |
| Unified candidate + resolve | added |
| Strategy registry + selector | added |
| Four-box levels, key pivots | not built (no definition in repo) |
| Order-flow data, economic calendar | missing; fields marked `missing` |

## Bug found during this work
`ReentryGovernor.record` wrote the per-level key without the family, so the per-level limit never applied. Fixed, with a regression test.
