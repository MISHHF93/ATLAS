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
        return {"status": "never_run", "command": "PYTHONPATH=src python scripts/ml_refresh.py"}
    return json.loads(f.read_text())


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
