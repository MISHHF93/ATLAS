"""Stable read-only payload for a native client. Schema version ``atlas-ml-api-v1``.

Every object carries ``execution_permission: none``. Missing files become empty lists
or ``unavailable``. Numbers are copied from manifests and the shadow log, never filled in.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas.ai.ml.registry import get as get_manifest, list_models, root as registry_root
from atlas.ai.ml.serve_config import aci_enabled
from atlas.ai.ml.shadow_track import DEFAULT_PATH, shadow_report
from atlas.ai.ml.train import GATES

SCHEMA_VERSION = "atlas-ml-api-v1"


def _envelope(**body: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "execution_permission": "none", **body}


def contract_index() -> dict[str, Any]:
    return _envelope(
        aci_default_off=not aci_enabled(),
        gates=dict(GATES),
        endpoints={
            "models": "GET /api/ml/v1/models",
            "model": "GET /api/ml/v1/models/{version}",
            "live": "GET /api/ml/v1/live?symbol=&interval=",
            "drift": "GET /api/ml/v1/drift",
            "roll": "GET /api/ml/v1/roll",
            "shadow": "GET /api/ml/v1/shadow",
            "monitor": "GET /api/ml/v1/monitor",
            "signals": "GET /api/ml/v1/signals",
            "nowcast": "GET /api/ml/v1/nowcast",
            "gapfill": "GET /api/ml/v1/gapfill",
        },
        docs="docs/ml/api-v1.md",
    )


def _gate_rows(man: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate": g.get("gate"), "passed": bool(g.get("passed")), "value": g.get("value"), "threshold": g.get("threshold")}
            for g in man.get("gates") or []]


def _card(man: dict[str, Any], path=None) -> dict[str, Any]:
    primary = (man.get("metrics") or {}).get("primary") or {}
    card_path = registry_root(path) / str(man.get("version")) / "model_card.md"
    text = card_path.read_text(encoding="utf-8") if card_path.is_file() else None
    return {
        "version": man.get("version"),
        "group": man.get("group"),
        "status": man.get("status"),
        "eligible": man.get("status") == "eligible",
        "created_at": man.get("created_at"),
        "code_sha": man.get("code_sha"),
        "data_hash": man.get("data_hash"),
        "calibrator": man.get("calibrator"),
        "features": man.get("features"),
        "gates": _gate_rows(man),
        "failed_gates": [g["gate"] for g in _gate_rows(man) if not g["passed"]],
        "metrics": {
            "n_oos": primary.get("n_oos"),
            "brier": primary.get("brier"),
            "brier_baseline": primary.get("brier_baseline"),
            "brier_skill": primary.get("brier_skill"),
            "logloss": primary.get("logloss"),
            "logloss_baseline": primary.get("logloss_baseline"),
            "dsr": (primary.get("dsr") or {}).get("dsr") if isinstance(primary.get("dsr"), dict) else primary.get("dsr"),
            "pbo": ((man.get("metrics") or {}).get("pbo") or {}).get("pbo"),
        },
        "model_card_markdown": text,
        "execution_permission": "none",
    }


def models_payload(path=None, group: str | None = None) -> dict[str, Any]:
    rows = [_card(m, path) for m in list_models(path) if group is None or m.get("group") == group]
    for row in rows:
        row.pop("model_card_markdown", None)
    return _envelope(models=rows, n_eligible=sum(1 for r in rows if r["eligible"]))


def model_payload(version: str, path=None) -> dict[str, Any] | None:
    man = get_manifest(version, path)
    if man is None:
        return None
    return _envelope(model=_card(man, path))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def live_payload(symbol: str, interval: str, **kwargs: Any) -> dict[str, Any]:
    from atlas.ai.ml.live_intelligence import generate_live_prediction, input_max_age_seconds
    raw = generate_live_prediction(symbol, interval, **kwargs)
    data_at = _parse_ts(raw.get("data_timestamp"))
    pred_at = _parse_ts(raw.get("prediction_timestamp"))
    age = None if data_at is None or pred_at is None else max(0.0, (pred_at - data_at).total_seconds())
    max_age = input_max_age_seconds(interval)
    version = raw.get("model_version")
    man = get_manifest(version) if version and version != "MODEL_UNAVAILABLE" else None
    drift = _drift_for(version) if man else {"status": "unavailable"}
    return _envelope(
        symbol=raw.get("symbol"),
        interval=raw.get("interval"),
        prediction_status=raw.get("prediction_status"),
        data_quality_status=raw.get("data_quality_status"),
        status_reason=raw.get("status_reason"),
        freshness={"data_timestamp": raw.get("data_timestamp"), "prediction_timestamp": raw.get("prediction_timestamp"),
                   "age_seconds": age, "max_age_seconds": max_age, "stale": raw.get("prediction_status") == "STALE_MARKET_DATA"},
        model_version=version,
        eligibility={"status": None if man is None else man.get("status"), "eligible": bool(man and man.get("status") == "eligible"),
                     "failed_gates": [] if man is None else [g.get("gate") for g in man.get("gates") or [] if not g.get("passed")]},
        drift=drift,
        setup_source=raw.get("setup_source"),
        detector=raw.get("detector"),
        probability_target_before_stop=raw.get("probability_target_before_stop"),
        probability_up=raw.get("probability_up"),
        probability_down=raw.get("probability_down"),
        probability_neutral=raw.get("probability_neutral"),
        expected_return_after_costs=raw.get("expected_return_after_costs"),
        conformal_take=raw.get("conformal_take"),
        aci=raw.get("aci") or {"enabled": False, "execution_permission": "none"},
        feature_schema_version=raw.get("feature_schema_version"),
    )


def _drift_for(version: str | None, path=None) -> dict[str, Any]:
    if not version:
        return {"status": "unavailable"}
    f = registry_root(path) / str(version) / "drift.json"
    if not f.is_file():
        return {"version": version, "status": "unavailable"}
    try:
        body = json.loads(f.read_text())
    except (OSError, ValueError):
        return {"version": version, "status": "unreadable"}
    psi = body.get("psi") or {}
    return {"version": version, "status": psi.get("status") or "unavailable",
            "adwin_brier_drift": (body.get("adwin_brier") or {}).get("drift"),
            "reference_rows": body.get("reference_rows"), "current_rows": body.get("current_rows")}


def drift_payload(path=None) -> dict[str, Any]:
    rows = []
    for man in list_models(path):
        item = _drift_for(man.get("version"), path)
        item["group"] = man.get("group")
        item["model_status"] = man.get("status")
        rows.append(item)
    return _envelope(models=rows)


def roll_payload(root=None) -> dict[str, Any]:
    from atlas.ai.prediction.roll import roll_status
    body = roll_status(root)
    sup = body.get("supervisor") or {}
    worker = body.get("worker") or {}
    state = sup.get("state") or worker.get("state") or "absent"
    return _envelope(state=state, supervisor=sup or None, worker=worker or None, cells=body.get("cells"),
                     recent=body.get("recent"), rule=body.get("rule"))


def shadow_payload(path=None) -> dict[str, Any]:
    return _envelope(**shadow_report(path))


def monitor_payload(path=None, shadow_path: str | None = None) -> dict[str, Any]:
    """Brier against its base rate, by registry version and by shadow week. Drift status beside each version."""
    oos = []
    drift = []
    for man in sorted(list_models(path), key=lambda m: str(m.get("created_at") or "")):
        primary = (man.get("metrics") or {}).get("primary") or {}
        oos.append({
            "at": man.get("created_at"), "version": man.get("version"), "group": man.get("group"),
            "brier": primary.get("brier"), "brier_baseline": primary.get("brier_baseline"),
            "brier_skill": primary.get("brier_skill"), "n_oos": primary.get("n_oos"),
        })
        item = _drift_for(man.get("version"), path)
        item["at"] = man.get("created_at")
        item["group"] = man.get("group")
        drift.append(item)
    weekly = []
    report = shadow_report(shadow_path or DEFAULT_PATH)
    for row in report.get("weekly") or []:
        weekly.append({"week": row.get("week"), "brier": row.get("brier"), "base_rate": row.get("base_rate"),
                       "labelled": row.get("labelled"), "resolved": row.get("resolved")})
    return _envelope(oos_brier=oos, shadow_brier=weekly, drift=drift)


def signals_payload(rt=None, limit: int = 50) -> dict[str, Any]:
    from atlas.ai.ml.signal15_live import signals_payload as _p
    return _p(rt, limit)


def nowcast_payload(ledger_path: str | None = None, limit: int = 50) -> dict[str, Any]:
    from atlas.ai.ml.signal15_live import nowcast_payload as _p
    return _p(ledger_path, limit)


def gapfill_payload(path: str | None = None) -> dict[str, Any]:
    from atlas.ai.ml.signal15_live import gapfill_payload as _p
    return _p(path)
