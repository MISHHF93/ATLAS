from fastapi.testclient import TestClient

from atlas.api.app import app


def test_feed_freshness_never_live_without_recent_closed_bar():
    j = TestClient(app).get("/api/feeds/freshness").json()
    assert set(j) >= {"counts", "newest", "symbols", "computed_at"}
    for r in j["symbols"]:
        assert r["label"] in ("live", "delayed", "historical", "simulated", "unavailable")
        if r["label"] == "live":
            assert r["age_s"] is not None and r["age_s"] <= 120
