"""Read-only ML endpoints: meta-label registry, model cards, drift, shadow and cited explanations.

Nothing here trains, promotes, sizes or submits anything (execution_permission: none). Training runs only via
scripts/ml_refresh.py; a version reaches predict() only if every pre-declared gate passed.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from atlas.ml import registry as R
from atlas.ml.retrieval import build_index, explain_query

ml_router = APIRouter(prefix="/api/ml", tags=["ml"])
REPO = Path(os.environ.get("ATLAS_REPO_ROOT", Path(__file__).resolve().parents[3]))


def _summary(m: dict[str, Any]) -> dict[str, Any]:
    p = (m.get("metrics") or {}).get("primary") or {}
    return {"version": m["version"], "group": m["group"], "status": m["status"], "created_at": m["created_at"],
            "code_sha": m["code_sha"], "data_hash": m["data_hash"], "n_oos": p.get("n_oos"), "brier_skill": p.get("brier_skill"),
            "auc": p.get("auc"), "ece": p.get("ece"), "n_taken": p.get("n_taken"), "mean_r_taken": p.get("mean_r_taken"),
            "dsr": (p.get("dsr") or {}).get("dsr"), "pbo": ((m.get("metrics") or {}).get("pbo") or {}).get("pbo"),
            "failed_gates": [g["gate"] for g in m.get("gates", []) if not g["passed"]]}


@ml_router.get("/registry")
def ml_registry(group: str | None = None) -> dict[str, Any]:
    ms = [m for m in R.list_models() if group is None or m["group"] == group]
    latest: dict[str, dict] = {}
    for m in ms:
        latest.setdefault(m["group"], m)
    return {"execution_permission": "none", "policy": "eligible only if every pre-declared gate passes; otherwise not_eligible",
            "latest": [_summary(m) for m in latest.values()], "versions": [_summary(m) for m in ms],
            "n_eligible": sum(m["status"] == "eligible" for m in ms)}


def _manifest(version: str) -> dict[str, Any]:
    m = R.get(version)
    if m is None:
        raise HTTPException(status_code=404, detail="unknown model version")
    return m


@ml_router.get("/models/{version}")
def ml_model(version: str) -> dict[str, Any]:
    m = _manifest(version)
    card = R.root() / version / "model_card.md"
    m["model_card"] = card.read_text() if card.exists() else None
    return m


@ml_router.get("/models/{version}/drift")
def ml_drift(version: str) -> dict[str, Any]:
    _manifest(version)
    f = R.root() / version / "drift.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="no drift report for this version yet")
    return json.loads(f.read_text())


@ml_router.get("/refresh/last")
def ml_last_refresh() -> dict[str, Any]:
    f = Path("var/ml/last_refresh.json")
    if not f.exists():
        return {"status": "never_run", "command": "PYTHONPATH=src python scripts/ml_refresh.py", "execution_permission": "none"}
    try:
        report = json.loads(f.read_text())
    except ValueError:
        return {"status": "unreadable", "execution_permission": "none"}
    return R.reconcile_refresh(report)


@ml_router.get("/shadow")
def ml_shadow() -> dict[str, Any]:
    from atlas.models.shadow import ShadowCollector
    sc = ShadowCollector("var/shadow/ml_meta_shadow.jsonl")
    rec = sc.records()
    return {"n_observed": len(rec), "n_resolved": sum(r.get("resolution") is not None for r in rec),
            "weekly": sc.weekly(), "recent": sorted(rec, key=lambda r: -r["detected_at"])[:50]}


@lru_cache(maxsize=4)
def _index(stamp: str):
    return build_index(REPO, R.root())


def index():
    st = "|".join(sorted(m["version"] for m in R.list_models()))
    return _index(st)


@ml_router.get("/search")
def ml_search(q: str = Query(min_length=2, max_length=300), k: int = Query(5, ge=1, le=20)) -> dict[str, Any]:
    return {"query": q, "method": "bm25(k1=1.5,b=0.75)", "results": index().search(q, k)}


@ml_router.get("/explain")
def ml_explain(version: str, detector: str | None = None, reasons: str = "", k: int = Query(5, ge=1, le=10)) -> dict[str, Any]:
    """Explain a version's status/decision with passages cited from docs, evidence and the model card."""
    m = _manifest(version)
    failed = [g["gate"] for g in m["gates"] if not g["passed"]]
    rs = [r for r in reasons.split(",") if r]
    q = explain_query(detector, rs + failed, extra=m["group"].replace("-", " "))
    s = _summary(m)
    text = (f"{version} is {m['status']}. " + (f"Failed gates: {', '.join(failed)}. " if failed else "All gates passed. ")
            + f"OOS brier skill {s['brier_skill']}, AUC {s['auc']}, mean after-cost R on taken setups {s['mean_r_taken']} "
              f"over {s['n_taken']} trades (n_oos {s['n_oos']}).")
    hits = [h for h in index().search(q, k + 10)
            if not h["path"].startswith(str(R.root())) or f"/{version}/" in h["path"]][:k]
    return {"version": version, "summary": text, "query": q, "citations": hits}


@ml_router.get("/serving")
def ml_serving() -> dict[str, Any]:
    """Unified catalog over var/ml/registry, var/models/<kind> (quant) and the in-memory serving registry."""
    from atlas.models.serving import catalog
    qroot = Path(os.environ.get("ATLAS_MODELS_ROOT", REPO / "var" / "models"))
    return catalog(quant_root=qroot)


@ml_router.get("/live-prediction")
def ml_live_prediction_get(
    symbol: str = Query("BTC-USD"),
    interval: str = Query("15m"),
    venue_reported_status: str | None = Query(None),
    data_feed_health: str | None = Query(None),
) -> dict[str, Any]:
    """Sections 4–8 & 12: Validated live ML prediction service with calibration, EV after costs, and market status."""
    from atlas.ai.ml.live_intelligence import generate_live_prediction
    return generate_live_prediction(
        symbol=symbol,
        interval=interval,
        venue_reported_status=venue_reported_status,
        data_feed_health=data_feed_health,
    )


@ml_router.post("/live-prediction")
def ml_live_prediction_post(payload: dict[str, Any]) -> dict[str, Any]:
    """POST variant for live ML prediction service."""
    from atlas.ai.ml.live_intelligence import generate_live_prediction
    return generate_live_prediction(
        symbol=str(payload.get("symbol", "BTC-USD")),
        interval=str(payload.get("interval", "15m")),
        venue_reported_status=payload.get("venue_reported_status"),
        data_feed_health=payload.get("data_feed_health"),
    )


@ml_router.get("/prediction-health")
def ml_prediction_health(symbol: str | None = Query(None)) -> dict[str, Any]:
    """Section 8: Live Prediction Health Monitoring Service."""
    from atlas.ai.ml.live_intelligence import get_prediction_health
    return get_prediction_health(symbol=symbol)


@ml_router.get("/ev-evolution")
def ml_ev_evolution(symbol: str = Query("BTC-USD"), interval: str = Query("15m")) -> dict[str, Any]:
    """Section 16: EV Evolution Monitor comparing estimated EV at signal vs realized expectancy after outcome."""
    from atlas.ai.ml.live_intelligence import get_ev_evolution_monitor
    return get_ev_evolution_monitor(symbol=symbol, interval=interval)


@ml_router.get("/champion-challenger")
def ml_champion_challenger() -> dict[str, Any]:
    """Sections 17 & 18: Champion–Challenger Model Lifecycle registry."""
    from atlas.ai.ml.live_intelligence import get_champion_challenger_registry
    return get_champion_challenger_registry()


@ml_router.post("/champion-challenger/transition")
def ml_champion_challenger_transition(payload: dict[str, Any]) -> dict[str, Any]:
    """Section 17 & 24: Governed model rollback and version transition."""
    from atlas.ai.ml.live_intelligence import rollback_or_transition_model
    target_version = str(payload.get("target_version") or "")
    if not target_version:
        raise HTTPException(status_code=400, detail="target_version is required")
    action = str(payload.get("action") or "rollback")
    reason = str(payload.get("reason") or "operator_governed_rollback")
    return rollback_or_transition_model(target_version=target_version, action=action, reason=reason)


@ml_router.get("/strategy-evolution")
def ml_strategy_evolution() -> dict[str, Any]:
    """Section 19: Strategy Evolution across all 7 ATLAS strategy families."""
    from atlas.ai.ml.live_intelligence import get_strategy_evolution_matrix
    return get_strategy_evolution_matrix()


@ml_router.get("/evolution-intelligence")
def ml_evolution_intelligence(symbol: str = Query("BTC-USD"), interval: str = Query("15m")) -> dict[str, Any]:
    """Sections 13–20: Complete ATLAS Evolution Intelligence Dashboard across 4 distinct dimensions."""
    from atlas.ai.ml.live_intelligence import get_evolution_intelligence_dashboard
    return get_evolution_intelligence_dashboard(symbol=symbol, interval=interval)
