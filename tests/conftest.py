
import pytest


@pytest.fixture(autouse=True)
def explicit_mock_market_data_permission(request, monkeypatch):
    """Grant only isolated test fixtures; production admission never inspects pytest.

    These modules supply deterministic data or mock provider responses. Their
    local evidence is a test double, not permission to fetch actual market data.
    Admission-denial tests deliberately receive no grant from this fixture.
    """
    if request.module.__name__.split(".")[-1] not in {
        "test_live_capture", "test_live_view", "test_live_observer",
        "test_observer_integrity", "test_observer_service", "test_stream_gaps",
        "test_market_bars", "test_second_tape",
    }:
        return
    import hashlib
    import json

    directory = request.getfixturevalue("tmp_path")
    evidence = directory / "mock_market_data_permission.txt"
    evidence.write_text(
        "TEST DOUBLE ONLY: in-memory synthetic provider responses for this test. "
        "This document conveys no rights to actual Coinbase, Yahoo, or other market data.",
        encoding="utf-8",
    )
    symbols = [
        "BTC-USD", "ETH-USD", "SOL-USD", "CAPTURE-USD", "CAPTURE-OBSERVER-USD",
        "GAP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LTC-USD",
        "NVDA", "AAPL", "MSFT", "SPY", "QQQ", "TSLA", "AMD",
        "T", "M", "BAD", "OLD", "ATOMIC", "GAP",
    ]
    grants = [
        {
            "grant_id": "mock-fixture-only:" + provider,
            "provider_id": provider,
            "symbols": symbols,
            "resolutions_seconds": [1, 60, 300, 900, 3600, 86400],
            "allowed_uses": ["training", "retention"],
            "license_ref": "internal:synthetic-test-fixture-only",
            "reviewed_by": "pytest fixture for synthetic responses only",
            "approved_at": "2020-01-01T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "evidence_path": evidence.name,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "written_permission_confirmed": True,
        }
        for provider in (
            "coinbase_exchange_public", "yahoo_chart_public", "test_public", "real_test_provider"
        )
    ]
    policy = directory / "mock_data_use_policy.json"
    policy.write_text(json.dumps({"schema_version": 1, "grants": grants}), encoding="utf-8")
    monkeypatch.setenv("ATLAS_DATA_USE_POLICY", str(policy))

@pytest.fixture(autouse=True)
def explicit_legacy_demo_gateway(request, monkeypatch):
    if request.module.__name__.split(".")[-1] in {
        "test_strategies", "test_catalog_and_stream", "test_live_stream", "test_live_stream_module02", "test_whale_policy_intake"
    }:
        from atlas.api.app import live_market_gateway
        monkeypatch.setattr(live_market_gateway, "demo_mode", True)
