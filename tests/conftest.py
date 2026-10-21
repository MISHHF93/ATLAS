
import pytest

@pytest.fixture(autouse=True)
def explicit_legacy_demo_gateway(request, monkeypatch):
    if request.module.__name__.split(".")[-1] in {
        "test_strategies", "test_catalog_and_stream", "test_live_stream", "test_live_stream_module02", "test_whale_policy_intake"
    }:
        from atlas.api.app import live_market_gateway
        monkeypatch.setattr(live_market_gateway, "demo_mode", True)
