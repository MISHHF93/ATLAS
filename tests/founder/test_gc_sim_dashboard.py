"""Gap closing 3: end-to-end paper simulation + dashboard explanation trail."""
import json

import pytest

from atlas.ops.sim import run_sim

CFG = "config/founder"


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    var = tmp_path_factory.mktemp("sim")
    s = run_sim(CFG, str(var), start="2023-01-02", warmup_end="2024-01-31", end="2024-06-28", seed=11,
                retrain_every_weeks=12, verbose=False)
    return var, s


def test_sim_exercises_full_pipeline(sim):
    var, s = sim
    assert s["decisions"] > 0 and s["fills"] > 0
    stages = {st["stage"] for t in s["trail"] for st in t["stages"]}
    assert {"rules", "scorer", "factor_sleeve", "meta_label", "news", "sizing", "portfolio", "cost", "risk", "execution"} <= stages
    assert len(s["retrains"]) >= 2                       # warm-up + at least one in-sim challenger retrain
    assert s["shadow_weeks_recorded"] > 0 and s["total_trials_logged"] >= 30
    assert all(m["champion"] is None for m in s["models"]), "no model may self-promote during the sim"
    assert s["acting_models"] == []                      # champions only by default -> none act
    for f in ("sim_trail.json", "sim_summary.json", "shadow_weeks.json"):
        assert (var / "reports" / f).exists()


def test_shadow_weeks_land_in_registry(sim):
    from atlas.models.quant.multi import registry_for
    var, _ = sim
    weeks = json.loads((var / "reports" / "shadow_weeks.json").read_text())
    k = weeks[0]
    reg = registry_for(var / "models", k["kind"])
    assert reg.idx["models"][k["model_id"]]["shadow"]


def test_dashboard_decisions_endpoint(sim):
    from test_dashboard import free_port, req
    from atlas.ops.dashboard.server import serve_in_thread
    from atlas.mcp.trading.service import build_service
    var, s = sim
    svc = build_service(CFG, state_path=str(var / "state.sqlite")); svc.heartbeat(); svc.models_root = str(var / "models")
    port = free_port(); srv = serve_in_thread(svc, port)
    try:
        code, body, _ = req(port, "/api/decisions?limit=5")
        d = json.loads(body)
        assert code == 200 and len(d["decisions"]) == 5 and d["outcomes"] and d["sim"]["mode"].startswith("paper simulation")
        assert d["decisions"][0]["ts"] >= d["decisions"][-1]["ts"]
        code, body, _ = req(port, "/api/decisions?final=submitted&limit=500")
        assert all(t["final"] == "submitted" for t in json.loads(body)["decisions"])
        code, html, _ = req(port, "/")
        assert b'id="decisions"' in html
        code, js, _ = req(port, "/static/app.js")
        assert b"renderDecisions" in js and b".innerHTML" not in js
    finally:
        srv.shutdown()
