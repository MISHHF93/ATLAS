"""Record actions cannot manufacture transport, entitlement, or sync evidence."""
from copy import deepcopy
import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def records(monkeypatch):
    api = importlib.import_module("atlas.api.app")
    monkeypatch.setattr(api, "_CONNECTORS_STATE", deepcopy(api._CONNECTORS_STATE))
    monkeypatch.setattr(api, "_SYNC_PIPELINES_STATE", deepcopy(api._SYNC_PIPELINES_STATE))
    audit = []
    # A connector-record request may append evidence about the request, but has
    # no account/risk/execution authority and must never open an external URL.
    monkeypatch.setattr(api, "control_engine", SimpleNamespace(audit_log=audit))

    def forbidden_network(*args, **kwargs):
        pytest.fail("A record-only action attempted a provider request")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network)
    client = TestClient(api.app)  # No lifespan: no background observation starts.
    yield api, client, audit
    client.close()


def test_connector_inventory_requires_actual_evidence(records):
    _, client, _ = records
    response = client.get("/api/connectors")
    assert response.status_code == 200
    body = response.json()
    assert body["record_only"] is True
    assert len(body["connectors"]) == 11
    for record in body["connectors"]:
        assert record["status"] in {"unconfigured", "standby", "blocked"}
        assert record["record_only"] is True
        assert record["connected"] is False
        assert record["transport_configured"] is False
        assert record["connection_test_status"] == "not_tested"
        assert record["latency_ms"] is None
        assert record["last_tested_at"] is None
        assert record["license_status"] == "unknown"
        assert record["license_ref"] is None
        assert set(record["data_use_eligibility"].values()) == {"unknown"}
        assert record["deployment_eligible"] is False
        assert record["execution_permission"] == "none"


@pytest.mark.parametrize("connector_id", [
    "alpha_vantage_mcp", "financial_datasets_mcp", "fin_data_mcp", "google_gemini",
    "sec_edgar_xbrl", "crypto_perp_feed", "nyse_calendar", "atlas_local_ml",
    "xai_grok_bridge", "chronos_2_slot",
])
@pytest.mark.parametrize("action,operation", [("test_connection", "not_tested"), ("sync_metadata", "not_synced")])
def test_repeated_record_requests_do_not_establish_a_connection_or_license(records, connector_id, action, operation):
    api, client, audit = records
    before = deepcopy(api._CONNECTORS_STATE[connector_id])
    for _ in range(2):
        response = client.post("/api/connectors/action", json={"connector_id": connector_id, "action": action})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"  # Accepted record request; not probe success.
        assert body["operation_status"] == operation
        assert body["record_only"] is True
        assert body["data_synced"] is False
        assert body["connector"] == before
    assert len(audit) == 2
    assert all("connector_record_action" in line for line in audit)


def test_record_toggle_changes_preference_without_activating_transport(records):
    _, client, _ = records
    for expected_enabled in (False, True):
        response = client.post("/api/connectors/action", json={"connector_id": "alpha_vantage_mcp", "action": "toggle_enabled"})
        body = response.json()
        assert body["operation_status"] == "record_updated"
        record = body["connector"]
        assert record["enabled"] is expected_enabled
        assert record["status"] == ("unconfigured" if expected_enabled else "standby")
        assert record["connected"] is False
        assert record["transport_configured"] is False
        assert record["license_status"] == "unknown"
        assert record["deployment_eligible"] is False


@pytest.mark.parametrize("action", ["test_connection", "sync_metadata", "toggle_enabled"])
def test_quarantined_record_remains_blocked(records, action):
    api, client, _ = records
    before = deepcopy(api._CONNECTORS_STATE["irohan0_quant_mcp"])
    body = client.post("/api/connectors/action", json={"connector_id": "irohan0_quant_mcp", "action": action}).json()
    assert body["status"] == "blocked_by_policy"
    assert body["connector"] == before


def test_pipeline_inventory_has_no_invented_sync_evidence(records):
    _, client, _ = records
    body = client.get("/api/sync").json()
    assert body["record_only"] is True
    assert len(body["pipelines"]) == 6
    for pipeline in body["pipelines"]:
        assert pipeline["status"] == "record_only"
        assert pipeline["data_synced"] is False
        assert pipeline["operation_status"] == "not_synced"
        assert pipeline["records_synced"] == 0
        assert pipeline["manifest_sha256"] is None
        assert pipeline["latency_ms"] is None
        assert pipeline["last_synced_at"] is None
        assert pipeline["license_status"] == "unknown"


@pytest.mark.parametrize("pipeline_id", ["all", "sync:whale_microstructure", "sync:sqlite_model_registry"])
def test_repeated_sync_requests_only_update_records(records, pipeline_id):
    api, client, audit = records
    before = deepcopy(api._SYNC_PIPELINES_STATE)
    for _ in range(2):
        response = client.post("/api/sync/run", json={"pipeline_id": pipeline_id, "cadence": "15s"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["operation_status"] == "not_synced"
        assert body["record_only"] is True
        assert body["data_synced"] is False
        for original, pipeline in zip(before, body["pipelines"]):
            assert pipeline["records_synced"] == original["records_synced"] == 0
            assert pipeline["manifest_sha256"] is None
            assert pipeline["last_synced_at"] is None
            if pipeline_id in ("all", pipeline["pipeline_id"]):
                assert pipeline["last_requested_at"] is not None
                assert pipeline["cadence"] == "15s"
            else:
                assert pipeline == original
    assert all("sync_record_action" in line and "data_synced=false" in line for line in audit)


def test_unknown_pipeline_request_does_not_change_inventory(records):
    api, client, _ = records
    before = deepcopy(api._SYNC_PIPELINES_STATE)
    body = client.post("/api/sync/run", json={"pipeline_id": "missing"}).json()
    assert body["status"] == "error"
    assert body["operation_status"] == "not_found"
    assert body["data_synced"] is False
    assert api._SYNC_PIPELINES_STATE == before
