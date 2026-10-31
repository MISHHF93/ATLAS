# Handoff for Lola

Branch `cursor/ml-pipeline-cleanup-7120`. Pull request https://github.com/MISHHF93/ATLAS/pull/5. Do not merge it into `main` from this work. `main` was not changed here.

Three commits, in order:

1. `eb8ae11` — roll-loop heartbeats and timeout, stale bars are not `VALID`, registry/refresh reconcile, pooled horizon label purge, Windows venv redirector unwrap.
2. `06fb32d` — live meta-labels score a real open setup from `build_rows`, not a momentum heuristic.
3. The platform commit on top of those — adaptive conformal flag (off), public OHLCV retrain script, `/api/ml/v1` contract, shadow-week count, monitor series.

Gates are still `n_oos >= 200`, Brier skill `> 0`, log loss below the base rate, deflated Sharpe `> 0.95`, PBO `< 0.5`, `shadow_weeks >= 4`. Nothing auto-promotes. `execution_permission` stays `none`. No secrets were added. No full retrain was run in this environment.

## What you need to restart

- Restart the Node host (`frontend/server.mjs`) so the API routes and the Windows Python spawn change load. On Windows it now starts the base interpreter with `__PYVENV_LAUNCHER__` set, one process instead of the venv redirector plus a child.
- Restart `scripts/ml_horizons_roll.py --loop` so the new supervisor is the process that heartbeats. The old process will not pick up the timeout or the status files.
- Restart `scripts/run_live_ingest.py` only if you want the docstring-level note; its behavior did not change. The pid file is still the interpreter child.
- No database migration. New files, if you turn features on, are `var/ml/aci_state.json` and the existing `var/shadow/ml_meta_shadow.jsonl`. Both are gitignored runtime state.

## How to run and test

```bash
PYTHONPATH=src python -m pytest tests/ml/test_ml_platform_v1.py tests/ml/test_pipeline_cleanup.py tests/test_complete_system_verification.py tests/test_procutil.py tests/ml_directional/test_roll_and_anchored.py -q
cd frontend && node --test scripts/python_cmd.test.mjs
```

Do not run `scripts/ml_public_ohlcv_retrain.py --run` in CI. On your PC, with the feed store and network:

```bash
PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py                 # plan only
PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --backfill      # public bars, no training
PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --run           # backfill + refresh (heavy)
PYTHONPATH=src python scripts/ml_aci_eval.py --demo                      # synthetic ACI comparison; flag stays off
```

`ATLAS_ML_ACI` is unset or not `1` unless you choose to turn adaptive conformal on after reading an eval report. An empty ACI buffer abstains (the take becomes false).

## Files

Roll loop, freshness, registry, pooled labels, Windows spawn:

- `scripts/ml_horizons_roll.py`, `src/atlas/ai/prediction/roll.py`, `src/atlas/ai/prediction/horizons.py`
- `src/atlas/ai/ml/live_intelligence.py`, `src/atlas/ai/ml/dataset.py`
- `src/atlas/ai/ml/registry.py`, `src/atlas/ai/ml/refresh.py`, `src/atlas/api/ml.py`
- `src/atlas/ops/procutil.py`, `frontend/server.mjs`, `frontend/scripts/python_cmd.mjs`
- `scripts/run_live_ingest.py` (comment only)

Live setup scoring (same `live_intelligence.py` and `dataset.py`).

Platform slice:

- `src/atlas/ai/ml/serve_config.py` — `ATLAS_ML_ACI` flag
- `src/atlas/ai/ml/aci_serve.py`, `src/atlas/ai/ml/aci_eval.py`, `src/atlas/ai/ml/directional/aci.py` (`empirical_qhat` only)
- `src/atlas/ai/ml/shadow_track.py` — week count and live observe
- `src/atlas/ai/ml/contract_v1.py` — `/api/ml/v1` payloads
- `scripts/ml_aci_eval.py`, `scripts/ml_public_ohlcv_retrain.py`
- `docs/ml/api-v1.md`, `docs/ml/pipeline-cleanup-2026-10-31.md`, this file

Tests: `tests/ml/test_pipeline_cleanup.py`, `tests/ml/test_ml_platform_v1.py`, `tests/test_complete_system_verification.py`, `tests/test_procutil.py`, `tests/ml_directional/test_roll_and_anchored.py`, `frontend/scripts/python_cmd.test.mjs`.

## Behavior you will see

- `GET /api/ml/v1/contract` describes the schema. Live calls are `GET /api/ml/v1/live`. Drift, roll health, shadow weeks, and Brier series are the other `/v1` routes in `docs/ml/api-v1.md`.
- A `VALID` live prediction is an open filled setup. No open setup is `NO_SETUP` with null probabilities. Bars older than the interval freshness bound are `STALE_MARKET_DATA`.
- `var/ml/live_predictions.jsonl` is no longer appended. The sqlite ledgers under `var/ml/predictions/` are unchanged.
- `GET /api/ml/refresh/last` marks a version `artifact: missing` when the registry directory is gone (the Binance crypto models deleted on 2026-10-30). It does not promote.
- The horizon loop writes `cycle_start` immediately and heartbeats `var/ml/horizons/roll_status.json` and `roll_supervisor.json`. Default kill is 4 hours (`--timeout 0` waits without a cap).

## Open risks

- No new out-of-sample score was produced. Crypto meta models on the last published card were `not_eligible`. `--run` on a PC can register another `not_eligible` version. It becomes `eligible` only if every gate passes, including four resolved shadow weeks. That is still not an order.
- ACI was not validated on real purged walk-forward predictions here, only on a synthetic stream in tests and `--demo`. Leave the flag off until you run the eval on a real scored stream (`--csv`).
- The public retrain script assumes the feed’s Coinbase and Kraken adapters can see BTC, ETH, and SOL. Equity and gold stay `provider_status: none` until a permitted keyed feed is configured.
- Live setup scan uses the last 300 closed bars. An open setup that started before that window is invisible.
- `atlas-console up` still launches `sys.executable`, which on Windows is the venv redirector. Core, watchdog, and console can still show a launcher/interpreter pair.
- Shadow observe reads the jsonl to dedup. Fine while the file is small. A long file makes each live `VALID` slower.
- Champion-challenger HTTP still returns the baseline champion slot when no evolution champion exists. That slot is not an eligible meta-model and `promoted_to_execution` is false.
