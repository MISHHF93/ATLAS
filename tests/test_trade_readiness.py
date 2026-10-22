"""Trade readiness stays closed for live money and follows the measured ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.models.trade_readiness import build_trade_readiness


def _ledger(
    judgment: str,
    brier: float,
    confidence: str = "scored",
    decisions: list[dict] | None = None,
) -> dict:
    def track() -> dict:
        return {
            "judgment": judgment,
            "notice": "sample notice",
            "reliability": {
                "confidence": confidence,
                "brier_score": brier,
                "calibration_rows": 40,
            },
        }

    report: dict = {"tracks": {"competition": track(), "open_market": track()}}
    if decisions is not None:
        report["decisions"] = decisions
    return report


def _month(net: float, count: int = 10) -> list[dict]:
    end = datetime(2026, 10, 20, tzinfo=timezone.utc)
    rows: list[dict] = []
    for track in ("competition", "open_market"):
        for offset in range(count):
            rows.append(
                {
                    "track": track,
                    "counts_toward_proof": True,
                    "net_return": net,
                    "resolve_timestamp": (end - timedelta(days=offset)).isoformat(),
                }
            )
    return rows


def test_a_clear_research_sample_still_cannot_open_live_money() -> None:
    ready = build_trade_readiness(_ledger("supported_on_this_sample", 0.20, decisions=_month(0.01)))
    assert ready["light"] == "research_clear"
    assert ready["live_money"] == "disabled"
    assert ready["trading"] == "disabled"
    assert ready["orders_submitted"] == 0
    assert ready["may_propose_order"] is False
    assert ready["execution_permission"] == "none"
    assert all(row["status"] == "closed" for row in ready["checks"] if row["id"] in {"live_money", "broker_audit", "human_approval"})
    assert all(row["status"] == "met" for row in ready["checks"] if row["id"].endswith("_recent_month"))


def test_current_failure_modes_keep_the_light_withheld() -> None:
    weak = build_trade_readiness(_ledger("not_supported", 0.259))
    assert weak["light"] == "withheld"
    assert weak["live_money"] == "disabled"
    closed = {row["id"] for row in weak["checks"] if row["status"] == "closed"}
    assert "competition_costed_sample" in closed
    assert "competition_confidence" in closed
    assert "open_market_confidence" in closed

    few = build_trade_readiness(_ledger("supported_on_this_sample", 0.10, confidence="too_few_to_calibrate"))
    assert few["light"] == "withheld"
    confidence = next(row for row in few["checks"] if row["id"] == "competition_confidence")
    assert confidence["status"] == "closed"

    reversed_month = build_trade_readiness(
        _ledger("supported_on_this_sample", 0.20, decisions=_month(-0.02))
    )
    assert reversed_month["light"] == "withheld"
    recent = next(row for row in reversed_month["checks"] if row["id"] == "competition_recent_month")
    assert recent["status"] == "closed"
    assert reversed_month["live_money"] == "disabled"

    thin_month = build_trade_readiness(
        _ledger("supported_on_this_sample", 0.20, decisions=_month(0.01, count=3))
    )
    assert thin_month["light"] == "withheld"


def test_trade_readiness_route_submits_nothing() -> None:
    source = Path("src/atlas/models/trade_readiness.py").read_text(encoding="utf-8")
    assert "submit_order" not in source
    assert "process_strategy_signal" not in source
    assert "ActionableControlPlane" not in source

    client = TestClient(app)
    response = client.get("/api/control/trade-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["light"] == "withheld"
    assert body["live_money"] == "disabled"
    assert body["trading"] == "disabled"
    assert body["execution_permission"] == "none"
    assert body["orders_submitted"] == 0
    assert body["trials"]["execution_permission"] == "none"
    assert body["trials"]["orders_submitted"] == 0
    assert body["trials"]["may_propose_order"] is False
    assert body["trials"]["persisted"] is True
    assert "submit_order" not in response.text
    again = client.get("/api/control/trade-readiness")
    assert again.status_code == 200
    assert again.json()["trials"]["count"] == body["trials"]["count"]
    assert again.json()["trials"]["added"] == 0
