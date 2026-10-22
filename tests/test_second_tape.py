"""The one-second tape follows new public trades and cannot send an order."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.marketdata import second_tape


def _trade(symbol: str, price: float, observed: str, size: float = 0.1) -> dict:
    return {
        "symbol": symbol,
        "price": price,
        "size": size,
        "observed_at": observed,
    }


def test_a_new_trade_updates_the_open_second_immediately() -> None:
    second_tape.fold_trade(_trade("BTC-USD", 100.0, "2026-10-22T15:00:00.100000Z", 1.0))
    second_tape.fold_trade(_trade("BTC-USD", 102.0, "2026-10-22T15:00:00.400000Z", 2.0))
    second_tape.fold_trade(_trade("BTC-USD", 101.0, "2026-10-22T15:00:01.100000Z", 4.0))
    second_tape.fold_trade(_trade("BTC-USD", 102.0, "2026-10-22T15:00:00.400000Z", 2.0))
    body = second_tape.snapshot("BTC-USD", sampling=True)
    assert body["chart_source"] == "public_last_trade"
    assert body["execution_permission"] == "none"
    assert body["orders_submitted"] == 0
    candles = body["candles"]
    assert len(candles) >= 2
    first = next(row for row in candles if str(row["timestamp"]).startswith("2026-10-22T15:00:00"))
    second = next(row for row in candles if str(row["timestamp"]).startswith("2026-10-22T15:00:01"))
    assert first["open"] == 100.0
    assert first["high"] == 102.0
    assert first["close"] == 102.0
    assert first["volume"] == 3.0
    assert first["prints"] == 2
    assert second["close"] == 101.0
    assert second["prints"] == 1


def test_an_equity_second_stays_withheld() -> None:
    body = second_tape.snapshot("NVDA", sampling=True)
    assert body["chart_source"] == "withheld"
    assert body["candles"] == []
    assert body["execution_permission"] == "none"
    assert body["orders_submitted"] == 0


def test_second_tape_route_stays_off_without_public_sampling() -> None:
    source = Path("src/atlas/marketdata/second_tape.py").read_text(encoding="utf-8")
    assert "submit_order" not in source
    assert "process_strategy_signal" not in source
    assert "ActionableControlPlane" not in source
    client = TestClient(app)
    response = client.get("/api/market/second-tape", params={"symbol": "BTC-USD"})
    assert response.status_code == 200
    body = response.json()
    assert body["chart_source"] == "withheld"
    assert body["execution_permission"] == "none"
    assert body["orders_submitted"] == 0
    assert "submit_order" not in response.text
