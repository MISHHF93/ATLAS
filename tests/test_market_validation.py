"""Reject malformed market records before they can be displayed as candles."""

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.market.fixtures import candle_page
from atlas.market.schemas import Candle


@pytest.mark.parametrize("field,value", [
    ("open", "NaN"), ("high", "Infinity"), ("low", "-1"),
    ("close", "not-a-price"), ("volume", "-0.01"),
    ("open_time", "2026-10-19T00:00:00"), ("open_time", "yesterday"),
    ("high", "66000"), ("low", "68000"), ("close", "68000"),
])
def test_invalid_candles_are_rejected(field: str, value: str) -> None:
    payload = candle_page("BTC-USD", "1h").candles[0].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        Candle.model_validate(payload)


def test_decimal_strings_survive_serialization() -> None:
    payload = candle_page("BTC-USD", "1h").candles[0].model_dump()
    payload["close"] = "67110.500000000000000001"
    assert Candle.model_validate(payload).model_dump()["close"] == payload["close"]


@pytest.mark.parametrize("params", [{"symbol": "UNKNOWN"}, {"interval": "5m"}])
def test_unsupported_fixture_request_returns_labeled_empty_page(params: dict) -> None:
    response = TestClient(app).get("/api/market/candles", params=params)
    assert response.status_code == 200
    assert response.json()["source"] == "fixture"
    assert response.json()["candles"] == []


def test_research_capabilities_report_only_installed_provider_and_disabled_execution() -> None:
    response = TestClient(app).get("/api/research/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == [{
        "provider_id": "naive",
        "location": "local",
        "capabilities": ["forecast"],
        "models": ["last_value", "zero_return"],
    }]
    assert body["components"]["market_data"] == "fixture_only"
    assert body["execution"] == {"enabled": False, "permission": "none", "order_routes": False}


def test_research_demo_is_synthetic_and_never_grants_execution_permission() -> None:
    response = TestClient(app).get("/api/research/demo")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "invented_fixture"
    assert "Simulated research approval only" in body["notice"]
    assert body["without_approval"]["forecasts"] == []
    assert body["with_simulated_fixture_approval"]["execution_permission"] == "none"


def test_asset_catalog_is_paged_searchable_and_explicitly_synthetic() -> None:
    client = TestClient(app)
    first_page = client.get("/api/catalog/snapshot", params={"page": 1, "page_size": 50})
    assert first_page.status_code == 200
    first = first_page.json()
    assert first["source"] == "synthetic_fixture"
    assert first["is_live"] is False
    assert first["total_matching"] > first["page_size"]
    assert len(first["listings"]) == 50
    assert first["execution_permission"] == "none"
    assert all(row["data_status"] == "synthetic_fixture" for row in first["listings"])
    assert all(row["provider"] == "synthetic_fixture" for row in first["listings"])

    second_page = client.get("/api/catalog/snapshot", params={"page": 2, "page_size": 50}).json()
    assert first["listings"][-1]["symbol"] != second_page["listings"][0]["symbol"]

    search = client.get("/api/catalog/search", params={"q": "BTC", "track": "competition", "limit": 10}).json()
    assert search["total_matching"] >= 1
    assert any(row["symbol"] == "BTC-USD" for row in search["results"])
    assert search["execution_permission"] == "none"
