from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.api.ws import MarketStreamBroadcaster
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.marketdata.live_stream import LiveMarketDataGateway, OrderBookRingBuffer


def test_socket_reconnection_backoff_on_simulated_network_drop() -> None:
    gateway = LiveMarketDataGateway()
    dropped = gateway.simulate_disconnect("databento")
    assert dropped["connected"] is False
    assert dropped["status"] == "DISCONNECTED"

    rec1 = gateway.attempt_reconnect("databento")
    assert rec1["connected"] is False
    assert rec1["status"] == "AWAITING_TRANSPORT"
    assert rec1["reconnect_attempts"] == 1
    assert rec1["last_backoff_seconds"] == 0.5

    gateway.simulate_disconnect("databento")
    rec2 = gateway.attempt_reconnect("databento")
    assert rec2["reconnect_attempts"] == 2
    assert rec2["last_backoff_seconds"] == 1.0


def test_ring_buffer_memory_bounding_and_pit_causal_discipline() -> None:
    gateway = LiveMarketDataGateway(ring_buffer_maxlen=5000)
    base_ts = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)

    # Burst 6,200 ticks into the 5,000-slot ring buffer
    for i in range(6200):
        ex_ts = base_ts + timedelta(milliseconds=i * 10)
        rx_ts = ex_ts + timedelta(milliseconds=7)
        frame = gateway.ingest_tick(
            symbol="BTC-USD",
            price=67800.0 + (i % 50),
            size=1.25,
            side="buy" if i % 2 == 0 else "sell",
            exchange_timestamp=ex_ts,
            system_receipt_timestamp=rx_ts,
        )
        assert frame.execution_permission == "none"

    assert len(gateway.ring_buffer) == 5000

    # Verify PIT causal discipline: system_receipt_timestamp < exchange_timestamp is rejected
    buf = OrderBookRingBuffer(maxlen=10)
    bad_ex = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    bad_rx = bad_ex - timedelta(milliseconds=5)
    with pytest.raises(ValueError, match="Causal violation"):
        gateway.ingest_tick(
            symbol="SPY",
            price=584.20,
            size=100.0,
            exchange_timestamp=bad_ex,
            system_receipt_timestamp=bad_rx,
        )

    # Verify PIT as_of filtering excludes future ticks
    cutoff = base_ts + timedelta(milliseconds=1500 * 10)
    pit_rows = gateway.ring_buffer.query_pit_records(as_of=cutoff, symbol="BTC-USD")
    assert all(r.system_receipt_timestamp <= cutoff and r.exchange_timestamp <= cutoff for r in pit_rows)


def test_control_plane_500ms_data_freshness_gate_and_ws_backpressure() -> None:
    engine = ActionableControlPlaneEngine()
    gateway = LiveMarketDataGateway(control_engine=engine)
    now = datetime.now(timezone.utc)

    # Nominal latency (< 500ms) on competition track
    gateway.ingest_tick(
        symbol="BTC-USD",
        price=67850.0,
        size=2.0,
        exchange_timestamp=now - timedelta(milliseconds=12),
        system_receipt_timestamp=now,
    )
    assert engine.data_freshness_breach is False

    # Stale latency (> 500ms) on competition track triggers circuit breach
    gateway.ingest_tick(
        symbol="BTC-USD",
        price=67855.0,
        size=2.0,
        exchange_timestamp=now - timedelta(milliseconds=640),
        system_receipt_timestamp=now,
    )
    assert engine.data_freshness_breach is True
    assert any("data_freshness_circuit_breach" in entry for entry in engine.audit_log)

    # Verify non-blocking broadcaster backpressure frame dropping
    broadcaster = MarketStreamBroadcaster(max_client_queue_size=3)
    client_q = broadcaster.register_client_queue()
    for step in range(6):
        tick = gateway.ingest_tick(symbol="SPY", price=584.0 + step, size=50.0)
        broadcaster.broadcast_non_blocking(tick)
    assert client_q.qsize() == 3
    assert broadcaster.dropped_frames_count == 3

    # Verify FastAPI WebSocket `/ws/market-stream` & REST `/api/market/live-stream`
    client = TestClient(app)
    res = client.get("/api/market/live-stream?symbol=BTC-USD")
    assert res.status_code == 200
    payload = res.json()
    assert payload["execution_permission"] == "none"
    assert payload["tick"]["symbol"] == "BTC-USD"

    with client.websocket_connect("/ws/market-stream?symbol=BTC-USD") as ws:
        first_frame = ws.receive_json()
        assert first_frame["symbol"] == "BTC-USD"
        assert first_frame["execution_permission"] == "none"
        ws.send_text("ping")
        second_frame = ws.receive_json()
        assert second_frame["symbol"] == "BTC-USD"
        assert "vpin" in second_frame and "ofi" in second_frame
        ws.send_text("close")

