"""AI node: one registry, one /api/ai namespace, one advisory guard."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.ai.http import AINodeMiddleware, router
from atlas.ai.node import NODE, REGISTRY, enforce_advisory


def test_registry_modules_import():
    st = NODE.status()
    assert st["execution_permission"] == "none"
    names = {c["name"] for c in st["components"]}
    assert {"ml_pipeline", "evolution", "serving", "research_assistant", "conviction_debate"} <= names
    assert len(names) == len(REGISTRY)
    assert all(c["status"] == "ok" for c in st["components"]), [c for c in st["components"] if c["missing"]]


def test_enforce_advisory_strips_any_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_AUDIT", str(tmp_path / "a.jsonl"))
    clean, n = enforce_advisory({"a": {"execution_permission": "live"}, "b": [{"execution_permission": "paper"}],
                                 "c": {"execution_permission": "none"}})
    assert n == 2 and clean["a"]["execution_permission"] == "none" and clean["b"][0]["execution_permission"] == "none"
    assert (tmp_path / "a.jsonl").read_text().count("enforce_advisory") == 1


def _app():
    app = FastAPI()

    @app.get("/api/ml/x")
    def x():
        return {"execution_permission": "live", "v": 1}

    @app.get("/api/control/x")
    def ctl():
        return {"execution_permission": "live"}

    app.include_router(router)
    app.add_middleware(AINodeMiddleware)
    return TestClient(app)


def test_old_and_new_paths_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_AUDIT", str(tmp_path / "a.jsonl"))
    c = _app()
    assert c.get("/api/ml/x").json() == {"execution_permission": "none", "v": 1}
    assert c.get("/api/ai/ml/x").json() == {"execution_permission": "none", "v": 1}
    # control plane is not an AI namespace and is untouched
    assert c.get("/api/control/x").json() == {"execution_permission": "live"}
    assert c.get("/api/ai/status").json()["node"] == "atlas.ai"
    assert c.get("/api/ai/components/drift").json()["kind"] == "drift"
    assert c.get("/api/ai/components/nope").status_code == 404
    assert c.get("/api/ai/audit").json()["events"]


def test_main_app_exposes_ai_namespace():
    from atlas.api.app import _route_mounted
    assert all(_route_mounted(p) for p in ("/api/ai/status", "/api/ai/components", "/api/ai/audit"))


def test_local_ml_modules_are_registered_and_advisory():
    """Island/niche evolution, the research hand and the outcome ledger sit behind the AI node (execution_permission none)."""
    import importlib

    from atlas.ai.node import EXECUTION_PERMISSION

    registered = {m for c in REGISTRY for m in c.modules}
    for mod in ("atlas.ai.ml.market_islands", "atlas.ai.ml.niche_archive", "atlas.ai.ml.live_intelligence", "atlas.ai.models.outcome_ledger"):
        assert mod in registered
        importlib.import_module(mod)
    assert EXECUTION_PERMISSION == "none"
