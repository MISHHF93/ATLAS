"""Integration test suite for ATLAS Institutional Master Architecture & Module 02 Real-Time Data Streaming Engine (`tests/test_live_stream_module02.py`)."""
from __future__ import annotations

import asyncio
import collections
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.api.rbac import ROLE_PROFILES, verify_role_action
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.marketdata.live_stream import (
    LiveMarketDataGateway,
    compute_streaming_kyles_lambda,
    compute_streaming_vpin,
    compute_top5_ofi,
)


def test_async_socket_reconnects_and_graceful_fallback_on_mock_disconnect() -> None:
    gateway = LiveMarketDataGateway(ring_buffer_maxlen=10000)
    assert gateway.ring_buffer.maxlen == 10000

    # Simulate disconnect on Polygon (equities) and Hyperliquid (crypto perps)
    disc_poly = gateway.simulate_disconnect("polygon")
    assert disc_poly["connected"] is False
    assert disc_poly["status"] == "DISCONNECTED"

    disc_hl = gateway.simulate_disconnect("hyperliquid")
    assert disc_hl["connected"] is False

    # Async ingestion automatically reconnects with exponential backoff and ingests tick
    frame_nvda = asyncio.run(
        gateway.async_ingest_with_fallback(
            symbol="NVDA",
            price=142.50,
            size=120.0,
            preferred_provider="polygon",
        )
    )
    assert gateway.provider_status["polygon"]["connected"] is False
    assert gateway.provider_status["polygon"]["reconnect_attempts"] == 1
    assert frame_nvda.symbol == "NVDA"
    assert frame_nvda.track == "open_market"
    assert frame_nvda.execution_permission == "none"

    frame_sol = asyncio.run(
        gateway.async_ingest_with_fallback(
            symbol="SOL-USD",
            price=176.80,
            size=45.0,
            preferred_provider="hyperliquid",
        )
    )
    assert gateway.provider_status["hyperliquid"]["connected"] is False
    assert frame_sol.symbol == "SOL-USD"
    assert frame_sol.track == "competition"
    assert frame_sol.execution_permission == "none"


def test_vpin_volume_bucket_ofi_and_kyles_lambda_determinism() -> None:
    buy_b: collections.deque[float] = collections.deque([120.0, 140.0, 160.0, 180.0], maxlen=20)
    sell_b: collections.deque[float] = collections.deque([80.0, 60.0, 40.0, 20.0], maxlen=20)

    vpin_1 = compute_streaming_vpin(buy_b, sell_b)
    vpin_2 = compute_streaming_vpin(buy_b, sell_b)
    assert vpin_1 == vpin_2
    assert 0.0 < vpin_1 < 1.0
    # Imbalance = 40 + 80 + 120 + 160 = 400; Total = 200 * 4 = 800 -> VPIN = 0.50
    assert vpin_1 == 0.5

    ofi_1 = compute_top5_ofi(
        [100.0, 90.0, 80.0, 70.0, 60.0],
        [100.0, 90.0, 80.0, 70.0, 60.0],
        [150.0, 120.0, 95.0, 80.0, 65.0],
        [85.0, 80.0, 75.0, 65.0, 55.0],
    )
    ofi_2 = compute_top5_ofi(
        [100.0, 90.0, 80.0, 70.0, 60.0],
        [100.0, 90.0, 80.0, 70.0, 60.0],
        [150.0, 120.0, 95.0, 80.0, 65.0],
        [85.0, 80.0, 75.0, 65.0, 55.0],
    )
    assert ofi_1 == ofi_2
    assert ofi_1 > 0.0

    lam_1 = compute_streaming_kyles_lambda(142.00, 142.45, 300.0, prev_lambda=0.0014)
    lam_2 = compute_streaming_kyles_lambda(142.00, 142.45, 300.0, prev_lambda=0.0014)
    assert lam_1 == lam_2
    assert lam_1 > 0.0


def test_streaming_ticks_trigger_deterministic_control_plane_liquidation_on_drawdown_breach() -> None:
    engine = ActionableControlPlaneEngine()
    gateway = LiveMarketDataGateway(ring_buffer_maxlen=10000, control_engine=engine)
    now = datetime.now(timezone.utc)

    # Confirm initial state has 1 open position and kill switch is False
    assert sum(1 for p in engine.open_positions if p.status == "open") == 1
    assert engine.kill_switch_engaged is False

    # 1. Nominal tick keeps positions open and returns Remaining-Room HUD
    frame_ok = gateway.ingest_tick(
        symbol="BTC-USD",
        price=68410.0,
        size=2.5,
        mark_to_market_equity_usd=101850.0,
        exchange_timestamp=now - timedelta(milliseconds=9),
        system_receipt_timestamp=now,
    )
    assert frame_ok.execution_permission == "none"
    assert engine.kill_switch_engaged is False
    assert sum(1 for p in engine.open_positions if p.status == "open") == 1
    hud = engine.get_remaining_room_hud(track="competition")
    assert float(hud["daily_loss_room_usd"]) > 0.0
    assert float(hud["trailing_dd_room_usd"]) > 0.0

    # 2. Streaming tick where MTM equity drops below 8.0% trailing HWM floor ($103,100 * 0.92 = $94,852)
    # triggers immediate deterministic auto-flattening of all active positions!
    eval_res = engine.evaluate_market_tick(
        symbol="BTC-USD",
        price=62900.0,
        track="competition",
        latency_ms=11.2,
        mark_to_market_equity_usd=Decimal("94500.00"),
        now=now + timedelta(seconds=1),
    )
    assert eval_res["status"] == "AUTO_FLATTENED"
    assert eval_res["auto_flattened"] is True
    assert engine.kill_switch_engaged is True
    assert sum(1 for p in engine.open_positions if p.status == "open") == 0
    assert any("trailing_hwm_drawdown_floor" in r for r in eval_res["breach_reasons"])


def test_module02_ws_packets_rbac_segregation_and_zero_llm_control_imports() -> None:
    client = TestClient(app)

    # 1. Verify /api/market/module02-snapshot returns all 9 dual-track symbols with execution_permission: "none"
    res = client.get("/api/market/module02-snapshot?track=all")
    assert res.status_code == 200
    snap = res.json()
    assert snap["execution_permission"] == "none"
    assert len(snap["listings"]) == 9
    for pkt in snap["listings"]:
        assert pkt["execution_permission"] == "none"
        assert pkt["track"] in ("open_market", "competition")
        assert "bid_depth_top5" in pkt and "ask_depth_top5" in pkt
        assert "vpin" in pkt and "ofi" in pkt and "kyles_lambda" in pkt
        assert "spread_bps" in pkt and "latency_ms" in pkt and "regime" in pkt
        assert pkt["data_mode"] == "demo"
        assert pkt["feed_origin"] == "labeled_synthetic_fixture"
    assert snap["gateway"]["demo_mode"] is True
    assert snap["gateway"]["feed_origin"] == "labeled_synthetic_fixture"
    assert snap["gateway"]["venue_sessions"] == "unconfigured"

    # 2. Verify WebSocket /ws/market-stream packet schema & execution_permission: "none"
    with client.websocket_connect("/ws/market-stream?symbol=NVDA") as ws:
        pkt = ws.receive_json()
        assert pkt["symbol"] == "NVDA"
        assert pkt["track"] == "open_market"
        assert pkt["execution_permission"] == "none"
        assert pkt["data_mode"] == "demo"
        assert pkt["feed_origin"] == "labeled_synthetic_fixture"
        assert isinstance(pkt["last_price"], float)
        assert "ofi_z" in pkt
        assert "stale_feed_flagged" in pkt
        assert len(pkt["bid_depth_top5"]) == 5
        assert len(pkt["ask_depth_top5"]) == 5
        ws.send_text("close")

    # 3. Verify RBAC Client Segment Segregation (prop_firm_admin, quant_researcher, funded_trader, compliance_auditor)
    assert set(ROLE_PROFILES.keys()) == {
        "prop_firm_admin",
        "quant_researcher",
        "funded_trader",
        "compliance_auditor",
    }
    assert ROLE_PROFILES["quant_researcher"].execution_permission == "none"
    assert ROLE_PROFILES["compliance_auditor"].execution_permission == "none"

    admin_kill = verify_role_action("prop_firm_admin", "trigger_kill_switch", route="/control/risk-hud")
    assert admin_kill["authorized"] is True

    trader_kill = verify_role_action("funded_trader", "trigger_kill_switch", route="/listings")
    assert trader_kill["authorized"] is False

    trader_risk = verify_role_action("funded_trader", "modify_risk_parameters", route="/listings")
    assert trader_risk["authorized"] is False

    quant_trade = verify_role_action("quant_researcher", "submit_bracket_order", route="/market")
    assert quant_trade["authorized"] is False

    auditor_gov = verify_role_action("compliance_auditor", "view", route="/governance")
    assert auditor_gov["authorized"] is True
    auditor_kill = verify_role_action("compliance_auditor", "trigger_kill_switch", route="/governance")
    assert auditor_kill["authorized"] is False

    # Named roles are enforced on the HTTP control plane. An omitted role stays compatible
    # with the operator console. Forbidden roles must not engage the kill switch or flatten.
    before_state = client.get("/api/control/state")
    assert before_state.status_code == 200
    before_body = before_state.json()
    assert before_body["kill_switch_engaged"] is False
    open_before = len(before_body["open_positions"])

    denied_kill = client.post(
        "/api/control/kill-switch",
        headers={"X-Atlas-Role": "funded_trader"},
        json={"engaged": True, "reason": "rbac_probe"},
    )
    assert denied_kill.status_code == 403
    mid_state = client.get("/api/control/state").json()
    assert mid_state["kill_switch_engaged"] is False
    assert len(mid_state["open_positions"]) == open_before

    admin_noop = client.post(
        "/api/control/kill-switch",
        headers={"X-Atlas-Role": "prop_firm_admin"},
        json={"engaged": False, "reason": "rbac_admin_noop_reset"},
    )
    assert admin_noop.status_code == 200
    assert admin_noop.json()["kill_switch_engaged"] is False

    denied_signal = client.post(
        "/api/control/strategy-signal",
        headers={"X-Atlas-Role": "quant_researcher"},
        json={
            "symbol": "BTC-USD",
            "direction": "BUY",
            "suggested_stop_loss": 67000,
            "suggested_take_profit": 70000,
            "reference_price": 68410,
            "execution_permission": "none",
        },
    )
    assert denied_signal.status_code == 403

    denied_flatten = client.post(
        "/api/control/flatten",
        headers={"X-Atlas-Role": "compliance_auditor"},
    )
    assert denied_flatten.status_code == 403
    after_state = client.get("/api/control/state").json()
    assert after_state["kill_switch_engaged"] is False
    assert len(after_state["open_positions"]) == open_before

    # 4. Verify zero imports from atlas.ai inside src/atlas/control/
    control_dir = Path(__file__).resolve().parents[1] / "src" / "atlas" / "control"
    for py_file in control_dir.glob("*.py"):
        lines = [
            line.strip()
            for line in py_file.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not any("atlas.ai" in line for line in lines), f"Forbidden AI import in {py_file}"


def test_auto_optimize_configurations_endpoint():
    """Verify Zero-Touch Autonomous Configuration Engine auto-optimizes track, ATR stop, tactic, and notional."""
    client = TestClient(app)

    res_nvda = client.get("/api/configurations/auto-optimize?symbol=NVDA")
    assert res_nvda.status_code == 200
    body_nvda = res_nvda.json()
    assert body_nvda["execution_permission"] == "none"
    assert body_nvda["autopilot_mode"] == "zero_touch_active"
    assert body_nvda["symbol"] == "NVDA"
    assert body_nvda["auto_track"] == "open_market"
    assert body_nvda["auto_staleness_breaker_ms"] == 2000
    assert body_nvda["auto_atr_stop_bps"] >= 45
    assert body_nvda["auto_optimal_notional_usd"] >= 5000

    res_btc = client.post("/api/configurations/auto-optimize?symbol=BTC-USD")
    assert res_btc.status_code == 200
    body_btc = res_btc.json()
    assert body_btc["execution_permission"] == "none"
    assert body_btc["symbol"] == "BTC-USD"
    assert body_btc["auto_track"] == "competition"
    assert body_btc["auto_staleness_breaker_ms"] == 500
    assert body_btc["configurations"]["auto_flatten_on_breach"] is True


def test_user_lifecycle_state_and_actions():
    """Verify the 4-stage User Lifecycle Engine & Master Spec Invariants across Open-Market and Prop Competition."""
    client = TestClient(app)

    res_state = client.get("/api/lifecycle/state?symbol=BTC-USD")
    assert res_state.status_code == 200
    state = res_state.json()
    assert state["execution_permission"] == "none"
    assert state["active_realm"] == "competition"
    assert state["active_icp"] == "ICP-01"
    assert len(state["stages"]) == 4
    assert state["master_spec_invariants"]["money_ledgers_isolated"] == 8
    assert state["master_spec_invariants"]["custody_by_atlas"] is False

    res_auth = client.post(
        "/api/lifecycle/action",
        json={"action": "authorize_lifecycle_order", "symbol": "SPY", "realm": "open_market"},
    )
    assert res_auth.status_code == 200
    auth_body = res_auth.json()
    assert auth_body["execution_permission"] == "none"
    assert auth_body["active_realm"] == "open_market"
    assert auth_body["active_icp"] == "ICP-02"
    assert auth_body["active_stage"] == "4_evaluation_and_graduation"


def test_perfect_trader_whale_ml_and_auto_submit():
    """Legacy heuristic win rates and automatic submissions are retired, not model evidence."""
    client = TestClient(app)
    responses = [
        client.get("/api/ml/perfect-trader/state?symbol=BTC-USD&force_submit=true"),
        client.post("/api/ml/perfect-trader/train", json={"symbol": "NVDA"}),
        client.post("/api/ml/perfect-trader/auto-submit", json={"action": "scan_multi_asset", "symbol": "BTC-USD"}),
    ]
    for response in responses:
        assert response.status_code == 410
        detail = response.json()["detail"]
        assert detail["status"] == "retired"
        assert detail["execution_permission"] == "none"
        assert detail["replacement"] == "/api/research/vertical-slice"
        assert "oos_meta_precision_win_rate" not in response.text


def test_master_todo_backlog_and_ablation_endpoints():
    """Verify the Master To-Do & Agile Backlog Execution Engine (M01..M06 & TODO-01..TODO-07)."""
    client = TestClient(app)

    res_get = client.get("/api/backlog/todos")
    assert res_get.status_code == 200
    body = res_get.json()
    assert body["execution_permission"] == "none"
    assert body["total_items"] == 13
    assert body["completed_items"] == 13
    assert body["completion_pct"] == 100.0
    assert len(body["completed_milestones"]) == 6
    assert len(body["backlog_todos"]) == 7
    assert len(body["ablation_study"]["ablations"]) == 4
    assert body["cloud_and_ensemble"]["costed_ensemble_gate"]["beats_best_single_member"] is True

    res_post = client.post("/api/backlog/todos/verify", json={})
    assert res_post.status_code == 200
    assert res_post.json()["execution_permission"] == "none"





