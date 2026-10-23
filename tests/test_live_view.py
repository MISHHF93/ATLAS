"""The native chart and observer share real, resolution-labelled provider data."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from atlas.marketdata import live_view, public_quotes
from atlas.models import live_observer


NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


def bars(now=NOW, *, count=8, seconds=60):
    return [
        {"timestamp": (now - timedelta(seconds=(count - 1 - i) * seconds)).isoformat(),
         "open": 100 + i, "high": 102 + i, "low": 99 + i,
         "close": 101 + i, "volume": 5 + i}
        for i in range(count)
    ]


def payload(rows=None, *, as_of=NOW, metadata=None):
    return {"symbol": "NVDA", "bucket_seconds": 60,
            "candles": bars() if rows is None else rows,
            "feed_source": "yahoo_chart_public", "as_of": as_of.isoformat(),
            "provider_metadata": metadata or {}, "execution_permission": "none"}


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch):
    monkeypatch.setattr(live_view, "_CACHE", OrderedDict())
    monkeypatch.setattr(live_observer, "_SESSIONS", {})
    monkeypatch.setattr(live_view, "artifact_store", lambda: None)
    monkeypatch.setattr(live_observer, "artifact_store", lambda: None)
    monkeypatch.setattr(live_view, "snapshot", lambda *args, **kwargs: {
        "candles": [], "chart_source": "withheld", "feed_origin": "none",
        "notice": "No connected trade feed.", "feed_health": {}})
    # No test may accidentally reach a public service.
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: None)
    monkeypatch.setattr(public_quotes, "_get_json", lambda *args, **kwargs: pytest.fail("Unexpected HTTP request"))


def test_equity_chart_and_model_share_candles_at_actual_minute_resolution(monkeypatch):
    calls = []

    def fetch(symbol, bucket_seconds, *, limit):
        calls.append((symbol, bucket_seconds, limit))
        return payload()

    monkeypatch.setattr(public_quotes, "fetch_public_candles", fetch)
    result = live_view.live_view_snapshot(" nvda ", sampling=True, now=NOW)
    assert calls == [("NVDA", 60, 180)]
    assert result["symbol"] == "NVDA"
    assert result["bucket_seconds"] == 60
    assert result["refresh_seconds"] == 10
    assert result["chart_source"] == "public_market_candles"
    assert result["data_mode"] == "observed"
    assert result["feed_origin"] == "yahoo_chart_public"
    assert result["candles"] == bars()
    active = result["active"]
    assert active["candles"] == result["candles"][:-1]
    assert active["bars_read"] == 7
    assert active["last_bar_close"] == NOW.isoformat()
    assert active["online_observer"]["bucket_seconds"] == 60
    assert active["online_observer"]["samples_learned"] == 0
    assert result["orders_submitted"] == 0
    assert result["execution_permission"] == active["execution_permission"] == "none"


@pytest.mark.parametrize("reported,expected_status,expected_delay", [
    (None, "unknown", None), (900, "provider_reported_delay", 900),
    (-1, "unknown", None), (float("nan"), "unknown", None),
])
def test_provider_delay_is_reported_without_assuming_realtime(monkeypatch, reported, expected_status, expected_delay):
    metadata = {"exchangeDataDelayedBy": reported, "marketState": "REGULAR"}
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: payload(metadata=metadata))
    result = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    health = result["feed_health"]
    assert health["delay_status"] == expected_status
    assert health["delay_reported"] == expected_delay
    assert health["delay_seconds"] is None  # Provider field units are not assumed.
    assert health["provider_metadata"]["marketState"] == "REGULAR"
    assert health["candle_resolution_seconds"] == 60
    assert health["transport"] == "https_poll"


def test_success_and_missing_symbols_are_cached_then_refreshed(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(live_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def fetch(symbol, *args, **kwargs):
        calls.append(symbol)
        return payload() if symbol == "NVDA" else None

    monkeypatch.setattr(public_quotes, "fetch_public_candles", fetch)
    for _ in range(2):
        live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
        missing = live_view.live_view_snapshot("MISSING", sampling=True, now=NOW)
        assert missing["candles"] == []
        assert missing["active"]["direction"] == "WITHHELD"
    assert calls == ["NVDA", "MISSING"]
    clock[0] = live_view.REFRESH_SECONDS + 0.1
    live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    live_view.live_view_snapshot("MISSING", sampling=True, now=NOW)
    assert calls == ["NVDA", "MISSING", "NVDA", "MISSING"]


def test_refresh_failure_retains_original_provider_timestamp(monkeypatch):
    clock = [0.0]
    replies = iter([payload(as_of=NOW - timedelta(seconds=2)), None])
    monkeypatch.setattr(live_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: next(replies))
    first = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    clock[0] = live_view.REFRESH_SECONDS + 1
    retained = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW + timedelta(seconds=12))
    assert retained["candles"] == first["candles"]
    assert retained["feed_health"]["last_received_at"] == (NOW - timedelta(seconds=2)).isoformat()
    assert retained["feed_health"]["receive_age_seconds"] == 14
    assert retained["feed_health"]["connection"] == "stale"
    assert "refresh failed" in retained["notice"]


def test_sampling_disabled_never_fetches_or_substitutes_prices(monkeypatch):
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: pytest.fail("Sampling is disabled"))
    result = live_view.live_view_snapshot("NVDA", sampling=False, now=NOW)
    assert result["candles"] == result["active"]["candles"] == []
    assert result["chart_source"] == "withheld"
    assert result["data_mode"] == "withheld"
    assert result["active"]["direction"] == "WITHHELD"
    assert result["feed_origin"] == "none"


def test_missing_and_gapped_candles_are_not_interpolated(monkeypatch):
    original = [bars()[i] for i in (0, 2, 5, 7)]
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: payload(original))
    result = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    assert result["candles"] == original
    assert result["active"]["candles"] == original[:-1]
    assert result["active"]["online_observer"]["status"] == "waiting"
    assert result["active"]["direction"] == "WITHHELD"


@pytest.mark.parametrize("changes", [
    {"open": float("nan")}, {"close": float("inf")}, {"low": -1},
    {"high": 99}, {"low": 103}, {"volume": -1}, {"volume": float("inf")},
    {"timestamp": "invalid"}, {"timestamp": "2026-10-22T14:59:00"},
    {"timestamp": (NOW + timedelta(minutes=1)).isoformat()},
])
def test_invalid_ohlcv_cannot_reach_chart_or_model(monkeypatch, changes):
    good = bars()[0]
    invalid = {**good, "timestamp": (NOW - timedelta(seconds=30)).isoformat(), **changes}
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: payload([good, invalid]))
    result = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    assert result["candles"] == result["active"]["candles"] == [good]


def test_real_crypto_stream_keeps_seconds_and_does_not_call_minute_provider(monkeypatch):
    rows = bars(seconds=1)
    monkeypatch.setattr(live_view, "snapshot", lambda symbol, *, sampling: {
        "candles": rows, "chart_source": "public_last_trade",
        "feed_origin": "coinbase_exchange_public", "notice": "Observed trades",
        "feed_health": {"connection": "connected"}})
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: pytest.fail("Crypto uses its stream"))
    result = live_view.live_view_snapshot("BTC-USD", sampling=True, now=NOW)
    assert result["bucket_seconds"] == 1
    assert result["refresh_seconds"] == .4
    assert result["candles"] == rows
    assert result["active"]["candles"] == rows[:-1]
    assert result["active"]["online_observer"]["bucket_seconds"] == 1


def test_stale_market_data_pauses_learning_without_hiding_chart(monkeypatch):
    rows = bars(NOW - timedelta(hours=2))
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: payload(rows))
    result = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW)
    assert result["candles"] == rows
    assert result["feed_health"]["connection"] == "stale"
    assert result["active"]["online_observer"]["status"] == "paused"
    assert result["active"]["direction"] == "WITHHELD"
    assert "Learning is paused" in result["notice"]


def test_minute_observer_labels_only_after_next_candle_completes():
    rows = bars()
    first = live_observer.observe_public_bars("NVDA", rows, now=NOW, bucket_seconds=60, feed_origin="yahoo_chart_public")
    assert first["samples_learned"] == 0
    assert first["prediction_at"] == rows[-2]["timestamp"]
    forming = live_observer.observe_public_bars("NVDA", rows, now=NOW + timedelta(seconds=59), bucket_seconds=60, feed_origin="yahoo_chart_public")
    assert forming["samples_learned"] == 0
    closed = live_observer.observe_public_bars("NVDA", rows, now=NOW + timedelta(seconds=60), bucket_seconds=60, feed_origin="yahoo_chart_public")
    assert closed["samples_learned"] == 1
    assert closed["recent_outcomes"][-1]["resolved_at"] == rows[-1]["timestamp"]
    repeated = live_observer.observe_public_bars("NVDA", rows, now=NOW + timedelta(seconds=61), bucket_seconds=60, feed_origin="yahoo_chart_public")
    assert repeated["samples_learned"] == 1
    assert repeated["weights"] == closed["weights"]
    separate_provider = live_observer.observe_public_bars("NVDA", rows, now=NOW + timedelta(seconds=61), bucket_seconds=60, feed_origin="other_provider")
    separate_period = live_observer.observe_public_bars("NVDA", bars(NOW + timedelta(seconds=61), seconds=1), now=NOW + timedelta(seconds=61), bucket_seconds=1, feed_origin="yahoo_chart_public")
    assert separate_provider["samples_learned"] == separate_period["samples_learned"] == 0


def test_live_view_endpoint_keeps_sampling_policy_and_shared_response(monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app, live_market_gateway

    monkeypatch.setattr(live_market_gateway, "public_fetch_enabled", True)
    received = datetime.now(timezone.utc)
    minute = received.replace(second=0, microsecond=0)
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *args, **kwargs: payload(bars(minute), as_of=received))
    response = TestClient(app).get("/api/market/live-view", params={"symbol": "NVDA"})
    assert response.status_code == 200
    body = response.json()
    assert body["bucket_seconds"] == body["active"]["bucket_seconds"] == 60
    assert body["active"]["candles"] == body["candles"][:-1]
    monkeypatch.setattr(live_market_gateway, "public_fetch_enabled", False)
    disabled = TestClient(app).get("/api/market/live-view", params={"symbol": "NVDA"}).json()
    assert disabled["candles"] == []
    assert disabled["chart_source"] == "withheld"


@pytest.mark.parametrize("symbol,encoded", [("ES", "ES%3DF"), ("BRK.B", "BRK-B")])
def test_public_minute_fetch_uses_provider_symbol_mapping_and_metadata(monkeypatch, symbol, encoded):
    # Exercise the provider adapter too, without reaching an external service.
    function = _REAL_FETCH_PUBLIC_CANDLES
    calls = []
    rows = bars()

    def fake_http(url, *args, **kwargs):
        calls.append(url)
        return {"chart": {"result": [{
            "timestamp": [int(datetime.fromisoformat(row["timestamp"]).timestamp()) for row in rows],
            "meta": {"exchangeDataDelayedBy": 600, "marketState": "REGULAR"},
            "indicators": {"quote": [{key: [row[key] for row in rows] for key in ("open", "high", "low", "close", "volume")}]},
        }]}}

    monkeypatch.setattr(public_quotes, "_get_json", fake_http)
    result = function(symbol, 60)
    assert result is not None
    assert encoded in calls[0]
    assert "interval=1m" in calls[0]
    assert result["bucket_seconds"] == 60
    assert result["candles"] == rows
    assert result["provider_metadata"]["exchangeDataDelayedBy"] == 600


_REAL_FETCH_PUBLIC_CANDLES = public_quotes.fetch_public_candles
