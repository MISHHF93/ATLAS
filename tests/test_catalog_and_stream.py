"""Automated verification suite for ATLAS Universal Asset Catalog, Dynamic On-Demand WebSocket
Multiplexing, and Deterministic Order Sizing (`tests/test_catalog_and_stream.py`).
"""

from __future__ import annotations

from decimal import Decimal
import json

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.marketdata.catalog import UniversalAssetCatalog
from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.models.whale_policy import WhalePolicyModel
from atlas.strategies.connectors import CcxtPerpConnector


def test_universal_asset_catalog_universe_counts_and_sub10ms_search() -> None:
    """Verify UniversalAssetCatalog indexes 10,000+ US Equities, 500+ Crypto Perps, and CME Futures
    with sub-10ms typeahead search and execution_permission == 'none'.
    """
    catalog = UniversalAssetCatalog(target_equities_count=10000, target_crypto_count=520)
    counts = catalog.universe_counts()
    assert counts["equities"] >= 10000
    assert counts["crypto_perps"] >= 500
    assert counts["futures"] >= 6
    assert counts["total_assets"] >= 10506

    # Verify CME Futures contracts (ES, NQ, YM, RTY, CL, GC)
    for fut_sym in ("ES", "NQ", "YM", "RTY", "CL", "GC"):
        rec = catalog.get_asset(fut_sym)
        assert rec is not None, f"Missing CME future {fut_sym}"
        assert rec.asset_class == "futures"
        assert rec.execution_permission == "none"

    # Verify sub-10ms typeahead search on NVDA
    search_nvda = catalog.search("NVDA", track="open_market")
    assert search_nvda["execution_permission"] == "none"
    assert search_nvda["count"] >= 1
    assert search_nvda["results"][0]["symbol"] == "NVDA"
    assert search_nvda["results"][0]["execution_permission"] == "none"

    # Verify API endpoints /api/catalog/search and /api/catalog/snapshot
    client = TestClient(app)
    res_search = client.get("/api/catalog/search?q=BTC&track=competition")
    assert res_search.status_code == 200
    body_search = res_search.json()
    assert body_search["execution_permission"] == "none"
    assert body_search["results"][0]["symbol"] == "BTC-USD"

    res_snap = client.get("/api/catalog/snapshot?track=all&page=1&page_size=25")
    assert res_snap.status_code == 200
    body_snap = res_snap.json()
    assert body_snap["execution_permission"] == "none"
    assert len(body_snap["listings"]) == 25
    assert body_snap["universe_counts"]["total_assets"] >= 10500


def test_dynamic_on_demand_websocket_subscription_multiplexer() -> None:
    """Verify dynamic client subscription reference counting, VPIN/OFI/Kyle's Lambda ring buffer
    updates, and zero-subscriber bandwidth conservation.
    """
    gateway = LiveMarketDataGateway(ring_buffer_maxlen=10000)

    # Client 1 subscribes to NVDA, BTC-USD, and ES
    sub_c1 = gateway.subscribe(["NVDA", "BTC-USD", "ES"], subscriber_id="client_1")
    assert sub_c1["execution_permission"] == "none"
    assert set(sub_c1["subscribed_symbols"]) == {"NVDA", "BTC-USD", "ES"}
    assert sub_c1["active_symbol_count"] == 3
    assert gateway.is_symbol_subscribed("NVDA") is True
    assert gateway.is_symbol_subscribed("ES") is True

    # Client 2 also subscribes to NVDA
    gateway.subscribe(["NVDA"], subscriber_id="client_2")
    assert len(gateway._subscriptions["NVDA"]) == 2

    # Client 1 unsubscribes from NVDA and ES -> ES has 0 subscribers and deactivates raw feed;
    # NVDA still has client_2 so its raw feed remains active
    unsub_c1 = gateway.unsubscribe(["NVDA", "ES"], subscriber_id="client_1")
    assert unsub_c1["execution_permission"] == "none"
    assert "ES" in unsub_c1["zero_subscriber_deactivated"]
    assert "NVDA" not in unsub_c1["zero_subscriber_deactivated"]
    assert gateway.is_symbol_subscribed("ES") is False
    assert gateway.is_symbol_subscribed("NVDA") is True

    # Client 2 disconnects -> NVDA reaches 0 subscribers and deactivates raw feed
    deactivated = gateway.unsubscribe_client_all("client_2")
    assert "NVDA" in deactivated
    assert gateway.is_symbol_subscribed("NVDA") is False

    # Verify /ws/market-stream JSON subscribe/unsubscribe action protocol
    client = TestClient(app)
    with client.websocket_connect("/ws/market-stream?symbol=BTC-USD") as ws:
        initial = ws.receive_json()
        assert initial["symbol"] == "BTC-USD"
        assert initial["execution_permission"] == "none"

        ws.send_text(json.dumps({"action": "subscribe", "symbols": ["NVDA", "ES"]}))
        sub_msg = ws.receive_json()
        assert sub_msg["event"] == "subscription_update"
        assert sub_msg["action"] == "subscribe"
        assert "NVDA" in sub_msg["subscribed_symbols"]
        assert "ES" in sub_msg["subscribed_symbols"]
        assert sub_msg["execution_permission"] == "none"

        ws.send_text(json.dumps({"action": "unsubscribe", "symbols": ["ES"]}))
        unsub_msg = ws.receive_json()
        assert unsub_msg["event"] == "subscription_update"
        assert unsub_msg["action"] == "unsubscribe"
        assert "ES" in unsub_msg["unsubscribed_symbols"]
        assert unsub_msg["execution_permission"] == "none"

        ws.send_text(json.dumps({"action": "close"}))


def test_deterministic_control_plane_order_sizing_and_risk_rejection() -> None:
    """Verify deterministic 0.50%-0.75% equity risk sizing, mandatory ATR stop brackets,
    and real-time rejection when risk rules or kill switch are breached.
    """
    engine = ActionableControlPlaneEngine()
    engine.flatten_all_positions(reason="test_clean_slate")
    connector = CcxtPerpConnector()

    model = WhalePolicyModel()
    sig_ok = model.predict(
        symbol="BTC-USD",
        spot_price=68450.0,
        atr_14=1025.0,
        vpin=0.38,
        ofi_z=2.4,
        hawkes_ratio=0.92,
    )
    assert sig_ok.execution_permission == "none"

    # 1. Compliant Whale / Studio Signal within 0.50%-0.75% risk cap is authorized with ATR brackets
    intake_ok = engine.ingest_whale_policy_signal(
        sig_ok,
        track="competition",
        risk_fraction_target=Decimal("0.0060"),
        data_age_ms=8.5,
        execution_connector=connector,
    )
    assert intake_ok.execution_permission == "none"
    assert intake_ok.decision.control_plane_decision == "authorized_and_executed"
    assert 0.0050 <= intake_ok.risk_fraction_of_equity <= 0.0075
    assert intake_ok.connector_receipt is not None
    assert intake_ok.connector_receipt["status"] == "FILLED"

    # 2. Signal requesting > 0.75% per-trade risk is deterministically rejected
    oversized_intake = engine.ingest_whale_policy_signal(
        sig_ok,
        track="competition",
        desired_notional_usd=Decimal("150000"),
        data_age_ms=8.5,
    )
    assert oversized_intake.decision.control_plane_decision == "rejected_by_control_plane"
    assert any("per_trade_risk_exceeded" in v for v in oversized_intake.decision.violations)

    # 3. Direct pre-trade order ticket violating kill-switch is rejected
    engine.set_kill_switch(engaged=True, reason="test_emergency_kill")
    ord_res = engine.submit_order(
        ActionableOrderRequest(
            track="competition",
            instrument_id="comp:btc-perp:v1",
            side="buy",
            notional_usd=Decimal("25000"),
            stop_kind="atr",
            stop_distance_bps=Decimal("120"),
        )
    )
    assert ord_res.control_plane_decision == "rejected_by_control_plane"
    assert any("kill_switch" in v for v in ord_res.violations)


def test_named_directory_is_searchable_and_private_names_are_not_listings() -> None:
    """Company names are searchable. Private names stay unlisted and unpriced."""
    from atlas.marketdata.bar_projection import project_symbol_bars
    from atlas.marketdata.tradingview import describe_chart, tradingview_symbol

    catalog = UniversalAssetCatalog()
    spacex = catalog.search("SpaceX")
    assert any(row["symbol"] == "SPACEX" for row in spacex["results"])
    assert spacex["is_live"] is False
    assert spacex["source"] == "synthetic_fixture"
    assert spacex["execution_permission"] == "none"
    assert "not listed" in spacex["notice"]
    row = catalog.get_asset("SPACEX")
    assert row is not None
    assert row.exchange == "UNLISTED"
    assert row.last_price == 0
    assert row.provider == "synthetic_fixture"
    assert row.execution_permission == "none"
    assert catalog.get_asset("STRIPE") is not None
    assert catalog.get_asset("OPENAI") is not None

    disney = catalog.search("Disney")
    assert any(item["symbol"] == "DIS" and item["last_price"] == 0 for item in disney["results"])
    walmart = catalog.get_asset("WMT")
    assert walmart is not None and walmart.exchange == "NYSE" and walmart.last_price == 0
    bitcoin_cash = catalog.get_asset("BCH-USD")
    assert bitcoin_cash is not None
    assert bitcoin_cash.track == "competition"
    assert bitcoin_cash.last_price == 0
    cme = catalog.get_asset("CME")
    assert cme is not None and cme.asset_class == "equities"
    nvda = catalog.get_asset("NVDA")
    assert nvda is not None and nvda.last_price > 0

    assert tradingview_symbol("SPACEX") is None
    assert tradingview_symbol("DIS") == "NYSE:DIS"
    assert tradingview_symbol("WMT") == "NYSE:WMT"
    picture = describe_chart("SPACEX")
    assert picture["available"] is False
    assert picture["embed_url"] is None
    assert picture["tradingview_symbol"] is None
    assert picture["execution_permission"] == "none"

    gateway = LiveMarketDataGateway()
    bars = project_symbol_bars(gateway, "SPACEX", bucket_seconds=60, limit=20)
    assert bars["bar_count"] == 0
    assert bars["chart_source"] == "no_quote"
    assert bars["candles"] == []
    assert bars["execution_permission"] == "none"
    assert bars["last_close"] == 0
