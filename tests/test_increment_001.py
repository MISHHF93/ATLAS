import json

import pytest
from fastapi.testclient import TestClient

from atlas.ai.gemini_provider import DEEP_MODEL, FREQUENT_MODEL, GeminiResearchProvider
from atlas.ai.policy import PolicyError
from atlas.ai.schemas import MarketResearchResult
from atlas.api.app import app

VALID = {
    "regime": "unknown",
    "summary": "The fixture shows two rising hours. That is not a trade signal.",
    "confidence": 0.2,
    "risk_flags": ["fixture data", "uncalibrated confidence"],
}


def test_schema_rejects_confidence_above_one() -> None:
    payload = dict(VALID)
    payload["confidence"] = 1.1
    with pytest.raises(ValueError):
        MarketResearchResult.model_validate(payload)


def test_gemini_refuses_free_tier_without_calling_the_model() -> None:
    def generate(model: str, context: str) -> str:
        raise AssertionError("provider was called")

    client = GeminiResearchProvider(tier="free", generate=generate)
    with pytest.raises(PolicyError, match="paid"):
        client.analyze("Public funding note.")


def test_gemini_frequent_model_and_mock_response() -> None:
    seen: dict[str, str] = {}

    def generate(model: str, context: str) -> str:
        seen["model"] = model
        seen["context"] = context
        return json.dumps(VALID)

    result = GeminiResearchProvider(tier="paid", generate=generate).analyze(
        "Two hourly candles closed higher."
    )
    assert result.regime == "unknown"
    assert seen["model"] == FREQUENT_MODEL
    assert "candles" in seen["context"]


def test_deep_workload_selects_argon() -> None:
    def generate(model: str, context: str) -> str:
        assert model == DEEP_MODEL
        return json.dumps(VALID)

    GeminiResearchProvider(workload="deep", tier="paid", generate=generate).analyze(
        "Review this research note."
    )


def test_secret_and_oversize_context_are_not_sent() -> None:
    def generate(model: str, context: str) -> str:
        raise AssertionError("provider was called")

    client = GeminiResearchProvider(tier="paid", generate=generate)
    with pytest.raises(PolicyError, match="secret"):
        client.analyze("api_key=abcdef1234567890")
    with pytest.raises(PolicyError, match="characters"):
        client.analyze("x" * 12_001)


def test_empty_provider_response_raises() -> None:
    client = GeminiResearchProvider(tier="paid", generate=lambda model, context: "")
    with pytest.raises(RuntimeError, match="empty"):
        client.analyze("No body returned.")


def test_market_endpoint_is_read_only_fixture() -> None:
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["trading"] == "disabled"

    page = client.get("/api/market/candles", params={"symbol": "BTC-USD", "interval": "1h"})
    assert page.status_code == 200
    body = page.json()
    assert body["source"] == "fixture"
    assert body["candles"][0]["close"] == "67110.50"
    assert client.post("/api/market/candles").status_code == 405

    paths = set(app.openapi()["paths"])
    assert {
        "/api/health",
        "/api/market/candles",
        "/api/research/capabilities",
        "/api/research/demo",
        "/api/research/vertical-slice/status",
        "/api/research/vertical-slice/chart",
        "/api/research/vertical-slice/forecasts",
        "/api/research/vertical-slice/paper-trades",
        "/api/research/vertical-slice/lucky-moments",
        "/api/research/vertical-slice/run",
        "/api/research/vertical-slice/resolve",
    }.issubset(paths)
