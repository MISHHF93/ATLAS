import pytest
from fastapi.testclient import TestClient

from atlas.api import founder_data
from atlas.api.app import app
from atlas.console.demo import seed


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    var = tmp_path_factory.mktemp("fdemo") / "var"
    seed(str(var), run_sim=False)
    mp = pytest.MonkeyPatch()
    mp.setenv("ATLAS_FOUNDER_VAR", str(var))
    founder_data.reset_cache()
    yield TestClient(app)
    founder_data.reset_cache()
    mp.undo()


@pytest.mark.parametrize("area,name", [(a, n) for a, ns in founder_data.READS.items() for n in ns])
def test_every_founder_view_reads(client, area, name):
    r = client.get(f"/api/founder/data/{area}/{name}" + ("?id=1" if name in ("transfer", "investor") else ""))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["execution_permission"] == "none" and j["trading"] == "paper_only" and j["demo"] is True


def test_writes_and_unknown_views_are_unreachable(client):
    assert client.get("/api/founder/data/payments/approve_transfer").status_code == 404
    assert client.get("/api/founder/data/os/system").status_code == 404
    assert client.post("/api/founder/data/payments/summary").status_code == 405
