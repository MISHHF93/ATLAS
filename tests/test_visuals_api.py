from fastapi.testclient import TestClient

from atlas.api import visuals
from atlas.api.app import app


def test_overlays_404_without_runner_and_markers_with_one():
    c = TestClient(app)
    visuals.register_coordinator(None)
    assert c.get("/api/visuals/overlays/SPY").status_code == 404

    class Zones:
        active_zones: dict = {}

    class Det:
        active_setup = None

    class Coord:
        zone_engines = {"SPY": Zones()}
        detectors = {"SPY": Det()}

    visuals.register_coordinator(Coord())  # type: ignore[arg-type]
    try:
        r = c.get("/api/visuals/overlays/spy")
        assert r.status_code == 200 and r.json()["execution_permission"] == "none" and r.json()["markers"] == []
    finally:
        visuals.register_coordinator(None)
