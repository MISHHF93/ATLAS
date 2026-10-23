"""UDF spec conformance and parity between /api/udf/history and the price-action detectors."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from atlas.api import udf
from atlas.api.app import app

BUCKET = 3600


def _rows(count: int = 120) -> list[tuple[int, float, float, float, float, float]]:
    end = (int(time.time()) // BUCKET) * BUCKET - BUCKET  # last bar fully closed
    start = end - (count - 1) * BUCKET
    out = []
    price = 100.0
    for i in range(count):
        close = price + (0.4 if i % 9 < 5 else -0.3)
        out.append((start + i * BUCKET, price, max(price, close) + 0.5, min(price, close) - 0.5, close, 1000.0 + i))
        price = close
    return out


@pytest.fixture()
def fixture_bars(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, float, float, float, float, float]]:
    rows = _rows()
    monkeypatch.setattr(udf, "_projected_rows", lambda gateway, symbol, bucket: (rows, {"feed_origin": "test_fixture"}))
    return rows


def test_history_matches_detector_bars(fixture_bars) -> None:
    client = TestClient(app)
    now = int(time.time())
    hist = client.get("/api/udf/history", params={"symbol": "SPY", "resolution": "60", "from": 0, "to": now + 1}).json()
    setups = client.get("/api/quant/setups", params={"symbol": "SPY", "resolution": "60"}).json()
    assert hist["s"] == "ok"
    udf_bars = [list(r) for r in zip(hist["t"], hist["o"], hist["h"], hist["l"], hist["c"], hist["v"])]
    assert udf_bars == setups["bars"]
    assert len(udf_bars) == len(fixture_bars)
    assert all(isinstance(x, (int, float)) for x in hist["c"])  # numbers, not strings
    assert hist["t"] == sorted(hist["t"])


def test_countback_takes_priority_over_from(fixture_bars) -> None:
    client = TestClient(app)
    now = int(time.time())
    body = client.get(
        "/api/udf/history",
        params={"symbol": "SPY", "resolution": "60", "from": now - 10, "to": now + 1, "countback": 25},
    ).json()
    assert body["s"] == "ok"
    assert len(body["t"]) == 25
    assert body["t"][-1] == fixture_bars[-1][0]


def test_no_data_reports_next_time_in_the_past(fixture_bars) -> None:
    client = TestClient(app)
    now = int(time.time())
    body = client.get(
        "/api/udf/history", params={"symbol": "SPY", "resolution": "60", "from": now + 7200, "to": now + 9000}
    ).json()
    assert body["s"] == "no_data"
    assert body["nextTime"] == fixture_bars[-1][0]


def test_unknown_symbol_and_resolution_errors() -> None:
    client = TestClient(app)
    assert client.get("/api/udf/symbols", params={"symbol": "ZZZNOTREAL9"}).json() == {
        "s": "error",
        "errmsg": "unknown_symbol",
    }
    now = int(time.time())
    bad = client.get("/api/udf/history", params={"symbol": "SPY", "resolution": "7", "from": now - 99, "to": now}).json()
    assert bad["s"] == "error"


def test_symbol_info_fields() -> None:
    info = TestClient(app).get("/api/udf/symbols", params={"symbol": "SPY"}).json()
    for key in ("name", "ticker", "description", "type", "session", "timezone", "exchange", "listed_exchange",
                "minmov", "pricescale", "has_intraday", "supported_resolutions", "visible_plots_set", "format"):
        assert key in info
    assert info["visible_plots_set"] == "ohlcv"


def test_marks_table_and_timescale_marks(fixture_bars) -> None:
    client = TestClient(app)
    now = int(time.time())
    params = {"symbol": "SPY", "resolution": "60", "from": 0, "to": now + 1}
    table = client.get("/api/udf/marks", params=params).json()
    assert set(table) == set(udf.MARK_KEYS)
    assert len({len(v) for v in table.values()}) == 1
    ts = client.get("/api/udf/timescale_marks", params=params).json()
    assert isinstance(ts, list)
    for mark in ts:
        assert {"id", "time", "color", "label", "tooltip"} <= set(mark)
        assert mark["time"] in {row[0] for row in fixture_bars}
    crypto = client.get("/api/udf/timescale_marks", params={**params, "symbol": "BTC-USD"}).json()
    assert crypto == []
