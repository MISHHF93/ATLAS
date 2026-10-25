from datetime import datetime, timedelta, timezone
from decimal import Decimal
import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.ws import register_market_stream_ws
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.marketdata.microstructure import BookLevelSnapshot, compute_multilevel_ofi
from atlas.strategies.base import StrategySignal


def signal(**changes):
    data = dict(symbol="SPY", direction="BUY", reference_price=100,
                suggested_stop_loss=98, suggested_take_profit=104,
                execution_permission="none")
    data.update(changes)
    return StrategySignal(**data)


@pytest.mark.parametrize("changes", [
    {"direction": "HOLD"}, {"suggested_stop_loss": 101},
    {"suggested_take_profit": 99}, {"suggested_stop_loss": 0},
])
def test_invalid_intent_never_calls_connector_or_creates_position(changes):
    class Connector:
        def route_approved_order(self, *args, **kwargs):
            pytest.fail("Rejected intent reached execution connector")
    engine = ActionableControlPlaneEngine()
    before = len(engine.open_positions)
    result = engine.ingest_whale_policy_signal(signal(**changes), execution_connector=Connector())
    assert result.decision.control_plane_decision == "rejected_by_control_plane"
    assert len(engine.open_positions) == before


def test_open_market_sizing_obeys_half_percent_and_lot_rounding():
    engine = ActionableControlPlaneEngine()
    report = engine.process_strategy_signal(signal(), 100_000)
    assert report.decision.control_plane_decision == "rejected_by_control_plane"
    assert "execution_connector_unconfigured" in report.decision.violations
    assert report.risk_fraction_of_equity <= .005
    assert report.decision.quantity == report.decision.quantity.to_integral_value()
    assert report.decision.stop_loss_price == 98
    assert report.decision.take_profit_price == 104


def test_floating_loss_and_updated_high_water_mark_deny():
    engine = ActionableControlPlaneEngine()
    engine.start_of_day_equity_usd = Decimal("100000")
    engine.high_water_mark_usd = Decimal("110000")
    result = engine.process_strategy_signal(signal(), 95_000)
    assert result.decision.control_plane_decision == "rejected_by_control_plane"


def test_ofi_includes_bid_depletion_when_price_drops():
    old = BookLevelSnapshot(level=1, bid_price=100, ask_price=102, bid_size=40, ask_size=30)
    new = BookLevelSnapshot(level=1, bid_price=99, ask_price=102, bid_size=10, ask_size=30)
    assert compute_multilevel_ofi([old], [new]).ofi_raw == -40


def test_stream_volume_buckets_and_invalid_tick_are_causal():
    gateway = LiveMarketDataGateway(bucket_volume=100)
    gateway.ingest_tick(symbol="SPY", price=100, size=60, side="buy")
    tick = gateway.ingest_tick(symbol="SPY", price=100, size=40, side="sell")
    assert tick.vpin == pytest.approx(.2)
    assert sum(gateway._buy_buckets["SPY"]) == 60
    assert sum(gateway._sell_buckets["SPY"]) == 40
    before = len(gateway.ring_buffer)
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        gateway.ingest_tick(symbol="SPY", price=100, size=100, exchange_timestamp=now,
                            system_receipt_timestamp=now-timedelta(seconds=1))
    assert len(gateway.ring_buffer) == before
    assert gateway._partial["SPY"] == [0, 0]


def test_websocket_pushes_without_client_ping_and_cleans_up():
    gateway = LiveMarketDataGateway()
    app = FastAPI()
    broadcaster = register_market_stream_ws(app, gateway)
    @app.post("/tick")
    async def tick():
        gateway.ingest_tick(symbol="SPY", price=101, size=20)
        return {"ok": True}
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market-stream?symbol=SPY") as ws:
            assert ws.receive_json()["event"] == "awaiting_data"
            assert client.post("/tick").status_code == 200
            assert ws.receive_json()["price"] == 101
            ws.send_text("close")
    assert not broadcaster._client_queues
    assert not gateway._subscriptions


def test_models_cannot_import_brokers_or_dispatch_orders():
    root = Path(__file__).resolve().parents[1] / "src/atlas/ai/models"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("atlas.connectors", "atlas.strategies.connectors")), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"submit_order", "route_approved_order", "place_order_via_control_plane"}, path
