"""Labeled bar history is available for every catalog symbol, with a stream tail when ticks exist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.marketdata.bar_projection import project_symbol_bars
from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG
from atlas.marketdata.live_stream import LiveMarketDataGateway


def _assert_ohlc(candles: list[dict[str, object]]) -> None:
    stamps = [str(bar["timestamp"]) for bar in candles]
    assert stamps == sorted(set(stamps))
    for bar in candles:
        low = float(bar["low"])
        high = float(bar["high"])
        assert low <= float(bar["open"]) <= high
        assert low <= float(bar["close"]) <= high
        assert low > 0


def test_projected_bars_cover_catalog_assets_outside_the_nine_name_pump() -> None:
    gateway = LiveMarketDataGateway(demo_mode=True)
    equity = project_symbol_bars(gateway, "EQ0001", bucket_seconds=60, limit=80)
    asset = GLOBAL_ASSET_CATALOG.get_asset("EQ0001")
    assert asset is not None
    assert equity["catalog_found"] is True
    assert equity["track"] == "open_market"
    assert equity["chart_source"] == "labeled_fixture_bars"
    assert equity["feed_origin"] == "labeled_synthetic_fixture"
    assert equity["execution_permission"] == "none"
    assert equity["bar_count"] == 80
    assert abs(float(equity["last_close"]) - asset.last_price) / asset.last_price < 0.02
    _assert_ohlc(equity["candles"])

    doge = project_symbol_bars(gateway, "DOGE-USD", bucket_seconds=60, limit=40)
    assert doge["track"] == "competition"
    assert float(doge["last_close"]) < 1
    assert doge["bar_count"] == 40

    futures = project_symbol_bars(gateway, "ES", bucket_seconds=3600, limit=48)
    assert futures["track"] == "competition"
    assert float(futures["last_close"]) > 1000
    assert futures["bar_count"] == 48

    unknown = project_symbol_bars(gateway, "NOT-A-THING", bucket_seconds=60, limit=12)
    assert unknown["catalog_found"] is False
    assert unknown["bar_count"] == 12
    assert unknown["execution_permission"] == "none"


def test_stream_ticks_replace_the_right_edge_without_dropping_history() -> None:
    gateway = LiveMarketDataGateway(demo_mode=True)
    now = datetime.now(timezone.utc)
    for idx in range(6):
        stamp = now - timedelta(seconds=50 - idx * 8)
        gateway.ingest_tick(
            symbol="NVDA",
            price=142.0 + idx * 0.2,
            size=10.0,
            side="buy",
            exchange_timestamp=stamp,
            system_receipt_timestamp=stamp + timedelta(milliseconds=4),
        )
    report = project_symbol_bars(gateway, "NVDA", bucket_seconds=60, limit=30)
    latest = gateway.ring_buffer.latest("NVDA")
    assert latest is not None
    assert report["chart_source"] == "fixture_history_plus_stream_tail"
    assert report["bar_count"] == 30
    assert float(report["candles"][-1]["close"]) == pytest.approx(latest.price, rel=1e-6)
    assert report["execution_permission"] == "none"


def test_watched_catalog_symbol_gets_a_demo_tick() -> None:
    gateway = LiveMarketDataGateway(demo_mode=True)
    frames = gateway.ingest_watched_catalog_snapshot(["EQ0001", "NVDA"])
    assert [frame["symbol"] for frame in frames] == ["EQ0001"]
    assert frames[0]["data_mode"] == "demo"
    assert frames[0]["execution_permission"] == "none"
    assert gateway.ring_buffer.latest("EQ0001") is not None


def test_public_cache_replaces_the_fixture_without_a_network_call() -> None:
    gateway = LiveMarketDataGateway(demo_mode=True)
    gateway.store_public_bars(
        {
            "symbol": "BTC-USD",
            "bucket_seconds": 3600,
            "feed_source": "coinbase_exchange_public",
            "candles": [
                {
                    "timestamp": f"2026-10-20T{hour:02d}:00:00+00:00",
                    "open": 84000 + hour,
                    "high": 84100 + hour,
                    "low": 83900 + hour,
                    "close": 84050 + hour,
                    "volume": 12 + hour,
                }
                for hour in range(10)
            ],
        }
    )
    report = project_symbol_bars(gateway, "BTC-USD", bucket_seconds=3600, limit=20)
    assert report["chart_source"] == "public_market_candles"
    assert report["feed_origin"] == "coinbase_exchange_public"
    assert report["bar_count"] == 10
    assert float(report["last_close"]) == pytest.approx(84059)
    assert report["execution_permission"] == "none"
    assert gateway.public_fetch_enabled is False


def test_live_training_uses_desk_candles_and_stays_air_gapped() -> None:
    from atlas.models.live_training import train_live_books
    from atlas.models.whale_policy import WhalePolicyModel, WhalePolicyTrainer

    gateway = LiveMarketDataGateway(demo_mode=True)
    result = train_live_books(gateway, WhalePolicyTrainer(), served_model=WhalePolicyModel())
    model = result.pop("served_model")
    assert result["execution_permission"] == "none"
    assert result["order_authority"] == "control_plane_only"
    assert {row["symbol"] for row in result["competition"]} == {"BTC-USD", "ETH-USD", "SOL-USD"}
    assert {row["symbol"] for row in result["open_market"]} >= {"SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA"}
    assert model.model_id.startswith("whale_policy_gbdt_ac:")
    assert [stage["name"] for stage in result["stages"]] == [
        "read_public_candles",
        "label_printed_closes",
        "walk_forward_gate",
        "fit_track_weights",
        "score_both_books",
        "withhold_orders",
    ]
    assert result["orders_submitted"] == 0
    assert result["stages"][-1]["orders_submitted"] == 0
    assert result["open_market_model"].model_id.startswith("whale_policy_gbdt_ac:open_market:")
    assert all(row["execution_permission"] == "none" for row in result["competition"])
    trained = [row for row in result["competition"] + result["open_market"] if row["status"] == "trained"]
    assert trained
    assert all(row["paper_ready"] is False for row in trained)
    assert all(row["data_mode"] == "synthetic_fixture_training" for row in trained)


def test_market_bars_endpoint_and_original_candle_fixture() -> None:
    client = TestClient(app)
    bars = client.get("/api/market/bars", params={"symbol": "SOL-USD", "bucket_seconds": 60, "limit": 24})
    assert bars.status_code == 200
    body = bars.json()
    assert body["symbol"] == "SOL-USD"
    assert body["bar_count"] >= 24
    assert body["track"] == "competition"
    assert body["feed_origin"] == "labeled_synthetic_fixture"
    assert body["execution_permission"] == "none"
    _assert_ohlc(body["candles"])

    seconds = client.get("/api/market/bars", params={"symbol": "BTC-USD", "bucket_seconds": 1, "limit": 40})
    assert seconds.status_code == 200
    one_second = seconds.json()
    assert one_second["bucket_seconds"] == 1
    assert one_second["bar_count"] >= 8
    assert one_second["feed_origin"] == "labeled_synthetic_fixture"
    assert one_second["chart_source"] != "public_market_candles"
    assert one_second["execution_permission"] == "none"
    _assert_ohlc(one_second["candles"])

    page = client.get("/api/market/candles", params={"symbol": "BTC-USD", "interval": "1h"})
    assert page.status_code == 200
    assert page.json()["source"] == "fixture"
    assert page.json()["candles"][0]["close"] == "67110.50"
    assert client.get("/api/market/candles", params={"symbol": "AAPL", "interval": "1h"}).json()["candles"] == []
