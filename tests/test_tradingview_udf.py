"""TradingView UDF, causal Pine features, and the chart-policy air gap."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.api.udf import causal_bars
from atlas.features.pine_features import vwap_bands
from atlas.models.chart_policy import train_chart_policy

ROOT = Path(__file__).resolve().parents[1]


def _candles(count: int = 220) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    price = 100.0
    for index in range(count):
        drift = 0.35 if index % 37 < 18 else -0.12
        close = price + drift
        rows.append(
            {
                "open": price,
                "high": max(price, close) + 0.55,
                "low": min(price, close) - 0.28,
                "close": close,
                "volume": 1000.0 + float(index),
            }
        )
        price = close
    return rows


def test_udf_config_symbols_and_clock() -> None:
    client = TestClient(app)
    config = client.get("/api/udf/config").json()
    assert config["supported_resolutions"] == ["1", "5", "15", "60", "D"]
    assert config["supports_search"] is True
    assert config["supports_group_request"] is False
    assert config["supports_marks"] is True
    assert config["supports_timescale_marks"] is False
    assert {item["value"] for item in config["symbols_types"]} == {"stock", "crypto", "futures", "bond"}
    assert config["execution_permission"] == "none"

    btc = client.get("/api/udf/symbols", params={"symbol": "COINBASE:BTCUSD"}).json()
    assert btc["ticker"] == "BTC-USD"
    assert btc["type"] == "crypto"
    assert btc["session"] == "24x7"
    assert btc["timezone"] == "America/New_York"
    assert btc["supported_resolutions"] == ["1", "5", "15", "60", "D"]
    assert btc["execution_permission"] == "none"

    spy = client.get("/api/udf/symbols", params={"symbol": "SPY"}).json()
    assert spy["type"] == "stock"
    assert spy["session"] == "0930-1600"
    assert spy["timezone"] == "America/New_York"

    bond = client.get("/api/udf/symbols", params={"symbol": "MUB"}).json()
    assert bond["type"] == "bond"
    assert bond["session"] == "0930-1600"

    futures = client.get("/api/udf/symbols", params={"symbol": "ES"}).json()
    assert futures["type"] == "futures"
    assert futures["session"] == "24x7"

    stamp = client.get("/api/udf/time").json()
    assert isinstance(stamp, int)
    assert abs(stamp - time.time()) < 5

    found = client.get("/api/udf/search", params={"query": "SPY", "type": "stock", "limit": 5}).json()
    assert isinstance(found, list)
    assert any(item["symbol"] == "SPY" and item["execution_permission"] == "none" for item in found)


def test_history_is_causal_and_marks_do_not_invent_news() -> None:
    kept = causal_bars(
        [(1000, 1, 2, 1, 1.5, 10), (1060, 1, 2, 1, 1.5, 10), (1120, 1, 2, 1, 1.5, 10), (1180, 1, 2, 1, 1.5, 10)],
        bucket_seconds=60,
        start=0,
        end=1120,
        as_of=1120,
    )
    assert [row[0] for row in kept] == [1000, 1060]

    client = TestClient(app)
    now = int(time.time())
    history = client.get(
        "/api/udf/history",
        params={"symbol": "BTC-USD", "resolution": "60", "from": now - 20 * 24 * 3600, "to": now + 3600},
    ).json()
    assert history["s"] in {"ok", "no_data"}
    assert history["execution_permission"] == "none"
    if history["s"] == "ok":
        arrays = [history["t"], history["o"], history["h"], history["l"], history["c"], history["v"]]
        assert len({len(column) for column in arrays}) == 1
        assert arrays[0]
        assert all(stamp < now + 3600 for stamp in history["t"])
        assert all(stamp + 3600 <= now + 2 for stamp in history["t"])
        assert history["t"] == sorted(history["t"])

    future = client.get(
        "/api/udf/history",
        params={"symbol": "BTC-USD", "resolution": "60", "from": now + 10 * 24 * 3600, "to": now + 20 * 24 * 3600},
    ).json()
    assert future["s"] == "no_data"
    assert all(stamp < now + 10 * 24 * 3600 for stamp in future.get("t", []))

    bounded = client.get(
        "/api/udf/history",
        params={"symbol": "SPY", "resolution": "D", "from": now - 400 * 24 * 3600, "to": now - 30 * 24 * 3600},
    )
    assert bounded.status_code == 200
    body = bounded.json()
    if body["s"] == "ok":
        assert all(stamp < now - 30 * 24 * 3600 for stamp in body["t"])

    rejected = client.get(
        "/api/udf/history",
        params={"symbol": "SPY", "resolution": "D", "from": now, "to": now},
    )
    assert rejected.status_code == 400

    marks = client.get(
        "/api/udf/marks",
        params={"symbol": "BTC-USD", "resolution": "60", "from": now - 20 * 24 * 3600, "to": now + 3600},
    ).json()
    assert isinstance(marks, list)
    assert len(marks) <= 40
    for mark in marks:
        text = str(mark["text"]).lower()
        assert "news feed" not in text
        assert "identified iceberg" not in text or "not an identified iceberg" in text
        assert mark["time"] < now + 3600


def test_pine_vwap_ignores_future_prices() -> None:
    highs = [10, 11, 12, 13, 14]
    lows = [8, 9, 10, 11, 12]
    closes = [9, 10, 11, 12, 13]
    volumes = [1, 1, 1, 1, 1]
    first = vwap_bands(highs, lows, closes, volumes)
    closes[4] = 100
    second = vwap_bands(highs, lows, closes, volumes)
    assert first["execution_permission"] == "none"
    assert first["vwap"][2] is not None
    assert first["vwap"][2] == second["vwap"][2]
    assert first["vwap"][3] == second["vwap"][3]
    assert first["vwap"][4] != second["vwap"][4]


def test_chart_policy_signal_cannot_submit() -> None:
    source = (ROOT / "src" / "atlas" / "models" / "chart_policy.py").read_text(encoding="utf-8")
    assert "submit_order" not in source
    assert "process_strategy_signal" not in source
    assert "ActionableControlPlane" not in source
    assert "import lightgbm" not in source
    assert "import xgboost" not in source

    report = train_chart_policy(_candles(), symbol="BTC-USD", horizon_bars=30, embargo_bars=5)
    assert report["orders_submitted"] == 0
    assert report["execution_permission"] == "none"
    assert report["signal"]["execution_permission"] == "none"
    assert report["signal"]["strategy_id"] == "chart-policy:v1"
    assert report["status"] in {"trained", "insufficient_bars"}
    if report["status"] == "trained":
        assert report["signal"]["telemetry"]["model_library"] == "causal_stump"
        assert report["signal"]["telemetry"]["embargo_bars"] == 5
