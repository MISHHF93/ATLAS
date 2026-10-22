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


def test_catalog_search_pages_are_disjoint_and_the_pipeline_report_is_local() -> None:
    from atlas.api.app import control_engine

    client = TestClient(app)
    first = client.get("/api/catalog/search", params={"limit": 80, "offset": 0})
    assert first.status_code == 200
    page = first.json()
    assert page["page_size"] == 80
    assert page["offset"] == 0
    assert page["count"] == 80
    assert page["total_matching"] > 80
    assert page["source"] == "synthetic_fixture"
    assert page["is_live"] is False
    assert page["execution_permission"] == "none"

    second = client.get("/api/catalog/search", params={"limit": 80, "offset": 80}).json()
    assert second["offset"] == 80
    assert second["count"] == 80
    left = {row["symbol"] for row in page["results"]}
    right = {row["symbol"] for row in second["results"]}
    assert left.isdisjoint(right)

    report = client.get("/api/data/pipelines")
    assert report.status_code == 200
    body = report.json()
    assert body["execution_permission"] == "none"
    assert body["opens_vendor_socket"] is False
    assert body["trading"] == "disabled"
    expected_seed = any(
        position.position_id == "pos-001" and position.status == "open"
        for position in control_engine.open_positions
    )
    assert body["seed_position_open"] is expected_seed
    assert body["catalog"]["total_assets"] == page["universe_counts"]["total_assets"]
    stages = body["stages"]
    assert [stage["id"] for stage in stages] == list("ABCDEFGHIJKLMNOPQR")
    assert all(stage["opens_vendor_socket"] is False for stage in stages)
    assert all(stage["execution_permission"] == "none" for stage in stages)
    assert all(stage["state"] in {"ready", "watching", "blocked", "withheld"} for stage in stages)
    text = " ".join(f"{stage['name']} {stage['state']} {stage['detail']}" for stage in stages).lower()
    assert "synced" not in text
    assert "manifest" not in text
    assert "sha256" not in text
    by_id = {stage["id"]: stage for stage in stages}
    assert by_id["A"]["state"] == "ready"
    assert "fetch" in by_id["B"]["detail"].lower()
    assert by_id["B"]["state"] == ("watching" if body["public_candle_pages"] else "withheld")
    assert by_id["F"]["state"] == "ready"
    assert by_id["L"]["state"] == "ready"
    assert by_id["M"]["state"] == "watching"
    assert by_id["J"]["state"] == "blocked"
    assert "irohan0" in by_id["J"]["detail"]
    assert "causal stump" in by_id["K"]["detail"]
    assert by_id["O"]["state"] == "blocked"
    assert by_id["P"]["state"] == "ready"
    assert by_id["R"]["state"] == "blocked"
    assert body["range_garden"]["execution_permission"] == "none"
    assert body["reserve"]["execution_permission"] == "none"
    assert all(row["opens_vendor_socket"] is False for row in body["connectors"])


def test_rulebooks_are_the_loaded_paper_limits() -> None:
    from decimal import Decimal

    client = TestClient(app)
    response = client.get("/api/control/rulebooks")
    assert response.status_code == 200
    body = response.json()
    assert body["trading"] == "disabled"
    assert body["execution_permission"] == "none"
    assert "edit" in body["notice"]
    opened = body["open_market"]
    competition = body["competition"]
    assert opened["rulebook_id"] == "open-market-swing-2026-q4:v1"
    assert opened["track"] == "open_market"
    assert Decimal(opened["max_position_notional_usd"]) == Decimal("40000")
    assert Decimal(opened["max_daily_loss_fraction"]) == Decimal("0.03")
    assert Decimal(opened["max_drawdown_fraction"]) == Decimal("0.10")
    assert opened["drawdown_mode"] == "static"
    assert Decimal(opened["max_per_trade_risk_fraction"]) == Decimal("0.005")
    assert Decimal(opened["min_stop_distance_bps"]) == Decimal("30")
    assert opened["execution_permission"] == "none"
    assert competition["rulebook_id"] == "prop-comp-2026-q4:v1"
    assert competition["track"] == "competition"
    assert Decimal(competition["max_position_notional_usd"]) == Decimal("50000")
    assert Decimal(competition["max_daily_loss_fraction"]) == Decimal("0.04")
    assert Decimal(competition["max_drawdown_fraction"]) == Decimal("0.08")
    assert competition["drawdown_mode"] == "trailing"
    assert Decimal(competition["max_per_trade_risk_fraction"]) == Decimal("0.0075")
    assert Decimal(competition["min_stop_distance_bps"]) == Decimal("25")
    assert competition["min_trading_days"] == 5
    assert Decimal(competition["max_single_day_profit_share"]) == Decimal("0.35")
    assert competition["execution_permission"] == "none"
