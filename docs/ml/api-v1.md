# ML API v1 (`atlas-ml-api-v1`)

Read-only contract for a native client. Every response includes `schema_version` and `execution_permission: "none"`. Missing files are `unavailable` or empty lists. The server does not invent Brier, drift, or shadow weeks.

Base path: `/api/ml/v1`.

## `GET /contract`

| field | type | meaning |
|---|---|---|
| schema_version | string | `atlas-ml-api-v1` |
| execution_permission | string | always `none` |
| aci_default_off | bool | true unless `ATLAS_ML_ACI` is on |
| gates | object | `min_oos` 200, `min_dsr` 0.95, `max_pbo` 0.5, `min_shadow_weeks` 4 |
| endpoints | object | path of each route below |

## `GET /models` and `GET /models/{version}`

List omits the markdown body. The version route includes `model_card_markdown` when `model_card.md` is on disk. Unknown version is HTTP 404.

| field | type | meaning |
|---|---|---|
| version, group, status | string | registry manifest |
| eligible | bool | `status == eligible` (every gate passed) |
| gates | list | `{gate, passed, value, threshold}` |
| failed_gates | list of string | gates with `passed` false |
| metrics | object | `n_oos`, `brier`, `brier_baseline`, `brier_skill`, `logloss`, `logloss_baseline`, `dsr`, `pbo` |
| execution_permission | string | `none` |

## `GET /live?symbol=&interval=`

| field | type | meaning |
|---|---|---|
| prediction_status | string | `VALID`, `NO_SETUP`, `STALE_MARKET_DATA`, `MODEL_UNAVAILABLE`, `UNCALIBRATED`, `MARKET_CLOSED`, `INSUFFICIENT_HISTORY`, `PREDICTION_EXPIRED` |
| data_quality_status | string | `VALID` only when the input is acceptable; stale inputs are not `VALID` |
| freshness | object | `data_timestamp`, `prediction_timestamp`, `age_seconds`, `max_age_seconds`, `stale` |
| eligibility | object | manifest `status`, `eligible`, `failed_gates` |
| drift | object | `status` from `drift.json`, or `unavailable` |
| setup_source | string | `setup_library` when a real open setup was scored |
| probability_target_before_stop | number or null | meta-label; null unless `VALID` |
| probability_up, probability_down, probability_neutral | number or null | binary split of that probability; neutral is 0 on `VALID` |
| aci | object | `{enabled: false}` unless `ATLAS_ML_ACI=1` |
| conformal_take | bool or null | split-conformal take, and ACI take when the flag is on |

## `GET /drift`

`models[]`: `version`, `group`, `model_status`, `status` (`stable`, `moderate`, `significant`, or `unavailable`), `adwin_brier_drift`.

## `GET /roll`

`state` is the supervisor or worker heartbeat (`running`, `idle`, `timeout`, `error`, or `absent`). `cells` are the 1m/5m crypto bundles. `recent` is the tail of `roll.jsonl`.

## `GET /shadow`

| field | type | meaning |
|---|---|---|
| shadow_weeks | int | distinct ISO weeks with a resolved target, stop, or timeout |
| min_shadow_weeks | int | 4 |
| n_observed, n_resolved | int | shadow log counts |
| weekly | list | brier, base rate, labelled count per week |

## `GET /monitor`

| field | type | meaning |
|---|---|---|
| oos_brier | list | one point per registry version: `brier`, `brier_baseline`, `brier_skill`, `n_oos` |
| shadow_brier | list | one point per shadow week: `brier`, `base_rate`, `labelled` |
| drift | list | one drift status per registry version |

An empty registry returns empty lists.
