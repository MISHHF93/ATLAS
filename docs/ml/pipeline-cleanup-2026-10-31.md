# ML pipeline cleanup (2026-10-31)

The live machine was not mounted in this workspace. The notes below are from the code paths that produce the reported symptoms, plus the 2026-10-30 changelog entry that deleted Binance-trained `atlas-meta-crypto-*` registry directories. No model was retrained. No gate threshold was changed. Nothing here is a performance number.

Promotion gates stay `n_oos >= 200`, Brier skill `> 0`, log loss below the training base rate, deflated Sharpe `> 0.95`, PBO `< 0.5`, `shadow_weeks >= 4`. `execution_permission` stays `none`. A missing artifact is marked not eligible; it is never promoted.

## What changed

**Roll loop.** `scripts/ml_horizons_roll.py --loop` only appended `var/ml/horizons/roll.jsonl` when `retrain_cell` finished, so a long or stuck fit looked identical to a dead process. The loop now writes `cycle_start` before the child runs, heartbeats `roll_supervisor.json` while it waits, and the child heartbeats `roll_status.json` (phase such as `crypto-1m`). The child is killed after `--timeout` (default 4 hours; `0` waits with no cap). Timeout and traceback go to the same jsonl. A killed iteration does not promote. The pinball rule is unchanged: promote only when the challenger is no worse on at least 200 real bars neither model trained on.

**Duplicate interpreters.** On Windows a venv `Scripts\python.exe` is a redirector (`PC/venvlauncher.c`). It sets `__PYVENV_LAUNCHER__` and starts the base `Python312\python.exe`, then waits. `ml_horizons_roll.py` and `run_live_ingest.py` do not spawn a second interpreter. The pair is that redirector plus the interpreter whose pid is in `live_ingest.pid`. Current CPython puts the child in a job that ends when the redirector ends, so killing the launcher does not leave an orphan on a current install. The frontend did spawn the redirector (`frontend/server.mjs`). It now starts the base interpreter with `__PYVENV_LAUNCHER__` set, which is the same activation `multiprocessing` uses, and one process instead of two. The roll supervisor uses the same unwrap so the `--once` worker is not another redirector pair.

**Stale inputs.** `generate_live_prediction` defaulted the staleness floor to `max(3 * bar, 7 days)`. A 15m bar four days old was still `data_quality_status: VALID` while the market was open, including when the caller passed feed health `HEALTHY`. The default is now the coverage-service slack after the bar close, plus one bar (15m: 3 hours + 15 minutes; 1h: 6 hours + 1 hour; 1d: 4 days + 1 day, the existing weekend/holiday slack). An open market past that bound returns `STALE_MARKET_DATA` and does not score. A closed equity session still returns `MARKET_CLOSED`. Callers can still pass `stale_threshold_seconds`.

**Retired jsonl.** Nothing in the live sweep reads or writes `var/ml/live_predictions.jsonl`. The sweep ledger is `var/ml/predictions/*.sqlite`. The API no longer appends the jsonl. `GET /api/ml/prediction-health` reports `prediction_log.live_predictions_jsonl = retired`. The file on disk, if present, is historical and is not deleted by this change.

**Feature schema.** `atlas-pit-features-v2.4` is defined once, next to `dataset.FEATURES`. If a manifest stores a different feature list, live scoring returns `MODEL_UNAVAILABLE` and `data_quality_status: FEATURE_SCHEMA_MISMATCH` instead of `VALID`. Manifests that do not store a feature list are unchanged.

**Pooled horizon labels.** The 1m/5m trainer's 2-row embargo matches one series. Pooled frames interleave symbols, so a row's next-bar label can sit inside the calibration or test block. Fit and calibration now drop any row whose next same-instrument bar is not strictly before the next block. The hold-out slice and the pinball promote/keep rule are unchanged. This removes leakage; it does not claim a better pinball number.

**Registry versus refresh.** `code_sha()` ran git from `src/atlas/ai/ml` and then asked for the path `src/atlas/ai/ml`, which does not exist relative to that directory, so a dirty tree was recorded as clean. Git now runs at the repo root. A dirty tree gets a version id ending in `-dirty` and does not no-op onto the clean commit's directory. `GET /api/ml/refresh/last` marks a named version `artifact: missing` when the directory is gone, and downgrades `eligible` to `not_eligible` in that response only. It does not rewrite gates and does not promote. Refresh records `providers` / `provider_status` (`none` when no provider name is on the bars) and continues after a per-group error so one failure does not leave the previous report looking current. A null provider no longer crashes the model card (`none` instead of `join` on `None`).

## Evidence, not a re-score

- Changelog 2026-10-30: the 15 `atlas-meta-crypto-*` registry models and the 4 `directional/crypto-*` dirs trained on Binance were deleted. `var/ml/last_refresh.json` is a separate file. A report that still names versions from commit `d63417b` is that stale file, not proof the directories exist. The API now says `missing`.
- Published cards in `docs/ml/model-card.md` were already `not_eligible`. This change does not produce a new OOS table. The owner's read (15m/1h Brier below the base rate, 1m `n_oos` 123, 1d `n_oos` 45 with PBO 0.59, `shadow_weeks` 0) fails the pre-declared gates. Shadow weeks cannot pass at training time.
- Equities and gold with provider `none` means the stored bars had no provider name, or no permitted keyed feed is in the store. Yahoo remains excluded. Massive, Questrade, or Alpaca paper data is an operator configuration, not a code path that invents bars.
- Live meta-label responses that do score still set `setup_source: momentum_heuristic`. The detector is chosen from return and EMA distance, not from the setup library the model was trained on. That is called out below; it was not "fixed" by relabeling it `VALID`.

## Not done, in order

1. **Score live meta-labels on real setup detections.** Until `generate_live_prediction` runs the same detectors as `dataset.build_rows`, a `VALID` probability is not the OOS meta-label. Expected effect of doing that: the live number becomes comparable to the purged walk-forward. It does not, by itself, pass Brier, DSR, PBO, or shadow weeks. Those still fail on the last published book.

2. **Retrain meta models on Coinbase and Kraken bars after a backfill.** Do this only when the store has enough confirmed history. Expect `not_eligible` until four shadow weeks exist and the other gates pass. Do not copy the deleted Binance manifests back. No expected Sharpe or Brier is stated here because this run did not train.

3. **Configure a permitted equity and gold provider** if those groups should leave `provider_status: none`. An empty provider is not a model defect and must not be papered over with a fallback venue.

4. **Leave the horizon timeout at 4 hours unless a heartbeat shows a healthy fit running longer.** Lowering it will kill a real 1m pass. The heartbeat is how to tell a long fit from a hang. The Oct 30 gap (jsonl quiet for about three hours) is explained by the old "log only at the end" behavior; this workspace could not see whether that process was still inside LightGBM.

5. **Do not merge the directional pipeline into the meta-label pipeline.** `atlas.ml` is an alias of `atlas.ai.ml` (same module objects). The directional book adds ACI and quantile gates on top of the same `GATES` dict. Merging the two trainers is a large change and does not move a failing gate.

6. **`atlas-console up` still launches `sys.executable`.** On Windows that is the redirector, so core, watchdog, and console each show a pair. Same unwrap as the roll supervisor would remove those extra parents. Not changed here because it was outside the three processes that were reported, and the console launcher test starts real processes.
