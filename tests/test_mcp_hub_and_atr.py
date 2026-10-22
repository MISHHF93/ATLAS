"""Tests for the ATLAS internal read-only MCP Hub (`src/atlas/mcp/`), external egress
firewall, the canonical ATR (`atlas.features.microstructure.compute_atr`), and the
per-venue execution connector modules (`src/atlas/connectors/`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.api.app import app
from atlas.connectors.ccxt_perp import CCXTPerpConnector
from atlas.connectors.ctrader import CTradePropAPIConnector
from atlas.connectors.dxtrade import DXtradePropConnector
from atlas.connectors.ibkr import IBKRDMAConnector, IBKRSessionConfig
from atlas.features.microstructure import MicrostructureWhaleFeatureExtractor, compute_atr
from atlas.mcp import MCPFirewall, ToolCallRejectedError
from atlas.mcp.server import AtlasReadonlyMCPServer


# ---------------------------------------------------------------- canonical ATR


def test_compute_atr_true_range_definition():
    highs = [10.0, 10.5, 10.4, 11.0, 10.9, 11.4, 11.3, 11.6, 11.5, 11.9, 11.8, 12.2, 12.1, 12.4, 12.3]
    lows = [9.5, 9.9, 10.0, 10.3, 10.4, 10.8, 11.0, 11.2, 11.1, 11.4, 11.5, 11.7, 11.9, 12.0, 12.1]
    closes = [9.8, 10.3, 10.1, 10.8, 10.6, 11.2, 11.1, 11.4, 11.3, 11.8, 11.7, 12.0, 12.2, 12.1, 12.3]
    atr_10 = compute_atr(highs, lows, closes, window=10)

    first_tr_index = len(closes) - 10
    tr_values = []
    for i in range(first_tr_index, len(closes)):
        pc = closes[i - 1]
        tr_values.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    assert atr_10 == pytest.approx(sum(tr_values) / 10.0)
    assert atr_10 > 0.0

    with pytest.raises(ValueError):
        compute_atr([1.0, 2.0], [0.5, 1.0], [1.5, 1.5], window=14)

    with pytest.raises(ValueError):
        compute_atr([1.0, 2.0, 3.0], [0.5, 1.0], [1.5, 1.5, 2.5], window=2)


def test_compute_atr_gaps_expand_true_range():
    # Gap up: |high - prior close| should exceed the intra-bar range
    highs = [20.0, 30.0, 30.2, 30.4]
    lows = [19.0, 29.0, 29.5, 29.8]
    closes = [20.0, 29.0, 30.0, 30.0]
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    assert compute_atr(highs, lows, closes, window=3) == pytest.approx(sum(trs) / 3.0)


def test_extractor_uses_canonical_atr_not_range_mean():
    candles = []
    px = 100.0
    volumes = [1200.0, 800.0, 1500.0, 900.0, 1300.0, 700.0]
    for i in range(6):
        gap_high = px + 2.4
        candles.append({"open": px, "high": gap_high, "low": px - 0.5, "close": px + 1.0, "volume": volumes[i]})
        px += 1.0
    extractor = MicrostructureWhaleFeatureExtractor()
    closed = extractor.extract_from_candles("TSLA", candles)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    assert closed.atr_14 == pytest.approx(round(compute_atr(highs, lows, closes, window=5), 6))


# ---------------------------------------------------------------- internal MCP server


def _readonly_server() -> AtlasReadonlyMCPServer:
    return AtlasReadonlyMCPServer(
        provide_point_in_time_candles=lambda symbol, max_bars: [
            {"timestamp": "2026-10-20T10:00:00Z", "open": 580.0, "high": 585.0, "low": 579.0, "close": 584.0}
        ],
        provide_microstructure_metrics=lambda symbol: {
            "symbol": symbol.upper(),
            "vpin": 0.42,
            "execution_permission": "none",
        },
        provide_prop_account_health=lambda account_id: {
            "daily_loss_room_usd": "3066.00",
            "drawdown_room_usd": "6998.00",
            "kill_switch_active": False,
        },
    )


def test_internal_mcp_tools_declared_and_airgapped() -> None:
    server = _readonly_server()
    handles = server.list_tools()
    names = [h["name"] for h in handles]
    assert names == [
        "market.point_in_time_candles",
        "market.microstructure_metrics",
        "prop.account_health",
    ]
    for handle in handles:
        assert handle["execution_permission"] == "none"


def test_internal_mcp_results_carry_airgap_metadata() -> None:
    server = _readonly_server()
    res = server.invoke_tool("market.point_in_time_candles", {"symbol": "SPY", "max_bars": 3})
    assert res["metadata"] == {"execution_permission": "none"}
    assert res["execution_permission"] == "none"
    assert res["data"]["symbol"] == "SPY"
    assert len(res["content_sha256"]) == 64

    res_h = server.invoke_tool("prop.account_health", {"account_id": "prop-demo"})
    assert res_h["data"]["health"]["kill_switch_active"] is False
    assert res_h["metadata"]["execution_permission"] == "none"

    res_m = server.invoke_tool("market.microstructure_metrics", {"symbol": "nvda"})
    assert res_m["data"]["metrics"]["vpin"] == 0.42

    with pytest.raises(ToolCallRejectedError):
        server.invoke_tool("market.submit_order", {})
    with pytest.raises(ToolCallRejectedError):
        server.invoke_tool("market.point_in_time_candles", {"symbol": ""})
    with pytest.raises(ToolCallRejectedError):
        server.invoke_tool("market.point_in_time_candles", {"symbol": "SPY", "max_bars": 100000})

    health = server.health_check()
    assert health["healthy"] is True
    assert health["tools_registered"] == 3
    assert health["execution_permission"] == "none"


def test_external_mcp_firewall_quarantine_and_allowlist() -> None:
    fw = MCPFirewall()

    verdict_quarantine = fw.evaluate("irohan0/quant-mcp", "create_watchlist")
    assert verdict_quarantine.allowed is False
    assert verdict_quarantine.verdict_kind == "quarantined_server"

    verdict_unknown = fw.evaluate("some_random_mcp", "get_prices")
    assert verdict_unknown.allowed is False
    assert verdict_unknown.verdict_kind == "unknown_server"

    verdict_keyword = fw.evaluate("alpha_vantage_mcp", "submit_order")
    assert verdict_keyword.allowed is False
    assert verdict_keyword.verdict_kind == "forbidden_keyword"

    verdict_not_allowlisted = fw.evaluate("alpha_vantage_mcp", "DELETE_EVERYTHING")
    assert verdict_not_allowlisted.allowed is False
    assert verdict_not_allowlisted.verdict_kind == "forbidden_keyword"

    verdict_ok = fw.evaluate("alpha_vantage_mcp", "TIME_SERIES_DAILY_ADJUSTED")
    assert verdict_ok.allowed is True
    assert verdict_ok.verdict_kind == "allow"

    with pytest.raises(PermissionError):
        fw.assert_allowed("irohan0/quant-mcp", "read_only_tool")
    allowlist = fw.allowlist_snapshot()
    assert "financial_datasets_mcp" in allowlist
    assert allowlist["fin_data_mcp"][0] == "cboe_delayed_quotes"


def test_mcp_api_endpoints() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)

    res_tools = client.get("/api/mcp/tools")
    assert res_tools.status_code == 200
    tools_body = res_tools.json()
    assert tools_body["execution_permission"] == "none"
    tool_names = [t["name"] for t in tools_body["tools"]]
    assert tool_names == ["market.point_in_time_candles", "market.microstructure_metrics", "prop.account_health"]

    res_health = client.get("/api/mcp/health")
    assert res_health.status_code == 200
    assert res_health.json()["healthy"] is True

    res_invoke = client.post(
        "/api/mcp/invoke",
        json={"tool_name": "prop.account_health", "params": {"account_id": None}},
    )
    assert res_invoke.status_code == 200
    invoke_body = res_invoke.json()
    assert invoke_body["status"] == "ok"
    assert "execution_permission" in invoke_body["metadata"]

    res_reject = client.post("/api/mcp/invoke", json={"tool_name": "market.execute_order", "params": {}})
    assert res_reject.status_code == 200
    assert res_reject.json()["status"] == "rejected"

    res_firewall = client.post(
        "/api/mcp/firewall-check",
        json={"server_id": "irohan0/quant-mcp", "tool_name": "anything"},
    )
    assert res_firewall.status_code == 200
    assert res_firewall.json()["verdict"]["allowed"] is False


# ---------------------------------------------------------------- execution connectors


def test_connector_venue_module_surface() -> None:
    from atlas.connectors.alpaca import AlpacaEquitiesConnector as A
    from atlas.connectors.ccxt_perp import CCXTPerpConnector as C
    from atlas.connectors.dxtrade import DXtradePropConnector as D
    from atlas.connectors.ibkr import IBKRDMAConnector as I
    from atlas.connectors.ctrader import CTradePropAPIConnector as CT

    alpaca = A()
    assert alpaca.connector_id == "alpaca_equities_dma"
    assert alpaca.to_venue_symbol("AAPL") == "AAPL"
    assert alpaca.normalize_symbol("NASDAQ:AAPL") == "AAPL"
    assert alpaca._default_reference_price("SPY") == 584.20

    ccxt = C()
    assert ccxt.to_venue_symbol("BTC-USD") == "BTC/USDT:USDT"
    assert ccxt.normalize_symbol("BTC/USDT:USDT") == "BTC-USD"

    dx = D()
    assert dx.to_venue_symbol("BTC-USD") == "DX:BTCUSD.PROP"
    assert dx.normalize_symbol("DX:BTCUSD.PROP") == "BTC-USD"

    ibkr = I()
    assert ibkr.connector_id == "ibkr_dma"
    assert ibkr.to_venue_symbol("AAPL") == "AAPL:SMART"
    assert ibkr.to_venue_symbol("ES") == "ES:GLOBEX:DEC2026"

    ctrader = CT()
    assert ctrader.to_venue_symbol("BTC-USD") == "CT:BTCUSD.PURE"
    assert ctrader.normalize_symbol("CT:BTCUSD.PURE") == "BTC-USD"


def test_ibkr_fix44_new_order_single_construction() -> None:
    ibkr = IBKRDMAConnector()
    msg = ibkr.build_fix_new_order_single(
        client_order_id="cli-ibkr-0001",
        canonical_symbol="AAPL",
        side="BUY",
        notional_usd=11030.0,
        limit_price=231.45,
        stop_loss_price=228.50,
        take_profit_price=238.75,
        execution_tactic="LIMIT",
    )
    fields = msg["fields"]
    assert msg["fix_version"] == "FIX.4.4"
    assert msg["msg_type"] == "NewOrderSingle"
    assert fields["8"] == "FIX.4.4"
    assert fields["35"] == "D"
    assert fields["54"] == "1"
    assert fields["55"] == "AAPL"
    assert fields["207"] == "SMART"
    assert fields["38"] == "47.656081"
    assert fields["99"] == "228.50"
    assert fields["1102"] == "238.75"

    fut_msg = ibkr.build_fix_new_order_single(
        client_order_id="cli-ibkr-0002",
        canonical_symbol="ES",
        side="SELL",
        notional_usd=68105.0,
        limit_price=None,
        stop_loss_price=6780.0,
        take_profit_price=6890.0,
        execution_tactic="TWAP",
    )
    fut_fields = fut_msg["fields"]
    assert fut_fields["55"] == "ES:GLOBEX:DEC2026"
    assert fut_fields["207"] == "GLOBEX"
    assert fut_fields["167"] == "FUT"
    assert fut_fields["18"] == "TWAP"
    assert fut_fields["54"] == "2"

    with pytest.raises(ValueError):
        IBKRSessionConfig(client_id=0)


def test_ctrader_bracket_envelope_construction() -> None:
    ctrade = CTradePropAPIConnector()
    env = ctrade.build_bracket_envelope(
        client_order_id="cli-ct-0001",
        canonical_symbol="BTC-USD",
        side="BUY",
        entry_price=68410.0,
        stop_loss_price=68110.0,
        take_profit_price=68710.0,
        quantity=0.5,
    )
    assert env["symbol_name"] == "CT:BTCUSD.PURE"
    assert env["trade_side"] == "BUY"
    assert env["stop_loss_ticks"] == 30.0
    assert env["take_profit_ticks"] == 30.0
    assert env["challenge_program_id"] == "ATLAS-PROP-100K-CT"
    assert env["execution_permission"] == "none"

    with pytest.raises(ValueError):
        ctrade.build_bracket_envelope(
            client_order_id="cli-ct-0002",
            canonical_symbol="ETH-USD",
            side="SELL",
            entry_price=2645.5,
            stop_loss_price=2645.5,
            take_profit_price=2680.0,
            quantity=1.0,
        )


def test_ibkr_and_ctrader_route_via_control_plane_only() -> None:
    from atlas.control.engine import ActionableControlPlaneEngine
    from atlas.connectors.base import UnifiedOrderPlacementRequest
    from atlas.models.whale_policy import WhalePolicyModel

    engine = ActionableControlPlaneEngine()
    engine.flatten_all_positions(reason="connector_clean_slate")

    ibkr = IBKRDMAConnector()
    req = UnifiedOrderPlacementRequest(
        client_order_id="cli-ibkr-0003",
        canonical_symbol="SPY",
        venue_symbol=ibkr.to_venue_symbol("SPY"),
        track="open_market",
        side="BUY",
        order_type="LIMIT",
        notional_usd=Decimal("20000"),
        limit_price=584.20,
    )
    cb = ibkr.place_order_via_control_plane(req, engine)
    assert cb.execution_permission == "none"
    assert cb.status == "FILLED"
    assert cb.connector_id == "ibkr_dma"
    assert len(ibkr.get_position_blotter()) == 1

    # Produce a REAL rejected control-plane decision (staleness violation), then
    # feed it to the connector: authorized-and-executed is mandatory for dispatch.
    signal = WhalePolicyModel().predict(
        symbol="BTC-USD",
        spot_price=68450.0,
        atr_14=1025.0,
        vpin=0.38,
        ofi_z=2.4,
        hawkes_ratio=0.92,
    )
    rejected_intake = engine.ingest_whale_policy_signal(
        signal,
        track="competition",
        data_age_ms=640.0,
        execution_connector=ibkr,
    )
    assert rejected_intake.decision.control_plane_decision == "rejected_by_control_plane"
    from atlas.connectors.ctrader import CTradePropAPIConnector

    ctrader = CTradePropAPIConnector()
    with pytest.raises(PermissionError):
        ctrader.route_approved_order(rejected_intake.decision)
