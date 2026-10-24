from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.api.quant import freshness


def test_freshness_labels():
    assert freshness(None, 100, 60, "x")["label"] == "unavailable"
    assert freshness(90, 100, 60, "synthetic_fixture")["label"] == "simulated"
    assert freshness(90, 100, 60, "feed")["label"] == "live"
    assert freshness(0, 5000, 60, "feed")["label"] == "delayed"
    assert freshness(0, 10**6, 60, "feed")["label"] == "historical"


def test_levels_has_overlays_and_correlation_id():
    c = TestClient(app)
    r = c.get("/api/quant/levels", params={"symbol": "GC", "resolution": "15"}, headers={"x-correlation-id": "abc-123"})
    assert r.headers["x-correlation-id"] == "abc-123"
    if r.status_code == 200:
        ov = r.json()["overlays"]
        assert ov["freshness"]["label"] in {"live", "delayed", "historical", "simulated", "unavailable"}
        assert "sma50" in ov["series"] or not r.json()["bars"]
    r2 = c.get("/api/quant/levels", params={"symbol": "ES"})
    if r2.status_code == 200:
        assert r2.json()["overlays"]["gold_sessions"]["status"] in {"NOT_APPLICABLE", "INSUFFICIENT_DATA"}
