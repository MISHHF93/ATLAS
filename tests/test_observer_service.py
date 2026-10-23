"""Autonomous observation scope and isolation, with no network dependency."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

import pytest

from atlas.marketdata import live_view
from atlas.models import live_observer, observer_service


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("ATLAS_OBSERVER_SYMBOLS", raising=False)
    monkeypatch.setattr(live_view, "_INTERESTS", OrderedDict())
    monkeypatch.setattr(live_view, "_INTEREST_EXPIRED", 0)
    monkeypatch.setattr(live_view, "_INTEREST_EVICTED", 0)
    monkeypatch.setattr(live_view, "_CACHE", OrderedDict())
    monkeypatch.setattr(observer_service, "note_interest", lambda symbol: None)
    monkeypatch.setattr(observer_service, "live_view_snapshot", lambda *args, **kwargs: pytest.fail("Unexpected source request"))
    monkeypatch.setattr(live_view.public_quotes, "fetch_public_candles", lambda *args, **kwargs: pytest.fail("Unexpected HTTP request"))


def response(symbol, *, samples=3, connection="connected", status="learning", source="public_market_candles"):
    return {"symbol": symbol, "bucket_seconds": 1 if symbol.endswith("-USD") else 60,
            "chart_source": source, "feed_origin": "real_test_provider",
            "feed_health": {"connection": connection, "trade_age_seconds": 2},
            "active": {"bars_read": 8, "last_bar_close": "2026-10-22T15:00:00+00:00", "direction": "UNCERTAIN",
                       "online_observer": {"status": status, "samples_learned": samples, "skipped_outcomes": 1}}}


def test_default_scope_is_provider_core_not_gateway_projected_prices():
    service = observer_service.ObserverService(sampling=True)
    status = service.status()
    assert set(status["default_symbols"]) == {"BTC-USD", "ETH-USD", "SOL-USD", "SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA"}
    assert status["state"] == "stopped"
    assert status["execution_permission"] == "none"
    assert status["autonomous"] is True
    assert all(item["status"] == "not_checked" for item in status["symbols"])


def test_viewer_interest_is_normalized_bounded_refreshed_and_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(live_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    for index in range(13):
        live_view.note_live_interest(f" symbol{index} ")
        clock[0] += 1
    interest = live_view.viewer_interest_status()
    assert interest["capacity"] == len(interest["active"]) == 12
    assert interest["evicted_total"] == 1
    assert interest["active"][0]["symbol"] == "SYMBOL12"
    assert "SYMBOL0" not in [entry["symbol"] for entry in interest["active"]]
    clock[0] = 400
    live_view.note_live_interest("symbol1")
    clock[0] = 414
    remaining = live_view.viewer_interest_status()
    assert [entry["symbol"] for entry in remaining["active"]] == ["SYMBOL1"]
    assert remaining["expired_total"] == 11
    assert remaining["active"][0]["expires_in_seconds"] == 286


def test_config_extends_defaults_but_transport_budget_is_honest(monkeypatch):
    monkeypatch.setenv("ATLAS_OBSERVER_SYMBOLS", " amd, doge-usd, ADA-USD,AVAX-USD,LTC-USD,amd ")
    service = observer_service.ObserverService(sampling=True)
    status = service.status()
    symbols = {item["symbol"]: item for item in status["symbols"]}
    assert "AMD" in service._targets["minute"]
    assert len(service._targets["crypto"]) == len(observer_service.CORE_SYMBOLS) + 3
    assert symbols["LTC-USD"]["status"] == "capacity_limited"
    assert symbols["LTC-USD"]["feed_status"] == "not_subscribed"
    assert symbols["LTC-USD"]["direction"] == "WITHHELD"
    live_view.note_live_interest("LTC-USD")
    updated = {item["symbol"]: item for item in service.status()["symbols"]}
    assert updated["LTC-USD"]["status"] == "not_checked"
    assert updated["AVAX-USD"]["status"] == "capacity_limited"


def test_extra_scope_is_bounded_and_viewers_have_priority(monkeypatch):
    monkeypatch.setenv("ATLAS_OBSERVER_SYMBOLS", ",".join(f"CONFIG{index}" for index in range(20)))
    service = observer_service.ObserverService(sampling=True)
    assert len(service.status()["omitted_symbols"]) == 8
    live_view.note_live_interest("NEW")
    updated = service.status()
    assert "NEW" in service._targets["minute"]
    assert "CONFIG11" in updated["omitted_symbols"]
    assert len(updated["symbols"]) == len(service.defaults) + 12


def test_expired_view_is_removed_without_extending_its_own_interest(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(live_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    live_view.note_live_interest("AMD")
    service = observer_service.ObserverService(sampling=True)
    assert "AMD" in service._targets["minute"]
    clock[0] = live_view.INTEREST_TTL_SECONDS
    status = service.status()
    assert "AMD" not in [item["symbol"] for item in status["symbols"]]
    assert len(status["symbols"]) == len(service.defaults)


def test_both_paths_observe_without_browser_and_slow_http_cannot_stall_crypto(monkeypatch):
    calls = []
    block = threading.Event()
    minute_started = threading.Event()
    monkeypatch.setattr(observer_service, "CRYPTO_INTERVAL_SECONDS", .01)
    monkeypatch.setattr(observer_service, "MINUTE_INTERVAL_SECONDS", .01)

    def source(symbol, *, sampling, register_interest):
        assert sampling is True
        assert register_interest is False
        calls.append(symbol)
        if not symbol.endswith("-USD"):
            minute_started.set()
            assert block.wait(3)
        return response(symbol)

    monkeypatch.setattr(observer_service, "live_view_snapshot", source)
    service = observer_service.ObserverService(sampling=True)

    async def run():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            for _ in range(150):
                if minute_started.is_set() and calls.count("BTC-USD") >= 3:
                    break
                await asyncio.sleep(.01)
            assert minute_started.is_set()
            assert calls.count("BTC-USD") >= 3
            status = service.status()
            assert status["state"] == "running"
            assert status["summary"]["observing"] >= 3
            assert status["coverage_status"] == "partially_available"
            # Cancellation does not wait for a blocked HTTP worker to return.
            stop.set()
            await asyncio.wait_for(task, timeout=.5)
            assert service.status()["state"] == "stopped"
        finally:
            block.set()
            stop.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert set(calls) == set(service.defaults)


def test_autonomous_minute_path_learns_only_new_completed_provider_candles(monkeypatch):
    clock = [datetime(2026, 10, 22, 15, tzinfo=timezone.utc)]
    epoch = clock[0]
    monkeypatch.setattr(live_observer, "_SESSIONS", {})
    monkeypatch.setattr(live_observer, "artifact_store", lambda: None)
    monkeypatch.setattr(live_view, "artifact_store", lambda: None)
    monkeypatch.setattr(live_view, "time", SimpleNamespace(monotonic=lambda: (clock[0] - epoch).total_seconds()))

    def fetch(symbol, *args, **kwargs):
        offset = int((clock[0] - epoch).total_seconds() / 60)
        return {"as_of": clock[0].isoformat(), "feed_source": "yahoo_chart_public", "candles": [
            {"timestamp": (clock[0] - timedelta(minutes=7 - index)).isoformat(), "open": 100 + index + offset,
             "high": 102 + index + offset, "low": 99 + index + offset, "close": 101 + index + offset, "volume": 10}
            for index in range(8)]}

    monkeypatch.setattr(live_view.public_quotes, "fetch_public_candles", fetch)
    monkeypatch.setattr(live_view, "snapshot", lambda *args, **kwargs: {"candles": [], "chart_source": "withheld", "feed_origin": "none"})
    monkeypatch.setattr(observer_service, "live_view_snapshot", lambda symbol, **kwargs: live_view.live_view_snapshot(symbol, now=clock[0], **kwargs))
    service = observer_service.ObserverService(sampling=True)

    async def run():
        await service._observe("NVDA")
        first = next(entry for entry in service.status()["symbols"] if entry["symbol"] == "NVDA")
        assert first["samples_learned"] == 0
        await service._observe("NVDA")
        repeated = next(entry for entry in service.status()["symbols"] if entry["symbol"] == "NVDA")
        assert repeated["samples_learned"] == 0
        clock[0] += timedelta(minutes=1)
        await service._observe("NVDA")

    asyncio.run(run())
    observed = next(entry for entry in service.status()["symbols"] if entry["symbol"] == "NVDA")
    assert observed["samples_learned"] == 1
    assert observed["status"] == "observing"
    assert observed["bucket_seconds"] == 60
    assert observed["feed_origin"] == "yahoo_chart_public"
    assert live_view.viewer_interest_status()["active"] == []


def test_symbol_failure_is_isolated_and_health_is_not_called_accuracy(monkeypatch):
    def source(symbol, **kwargs):
        if symbol == "BTC-USD":
            raise ValueError("malformed public response")
        if symbol == "ETH-USD":
            return response(symbol, connection="stale", status="stale")
        return response(symbol, status="warming_up")

    monkeypatch.setattr(observer_service, "live_view_snapshot", source)
    service = observer_service.ObserverService(sampling=True)

    async def run():
        await asyncio.gather(*(service._observe(symbol) for symbol in ("BTC-USD", "ETH-USD", "NVDA")))

    asyncio.run(run())
    result = service.status()
    entries = {entry["symbol"]: entry for entry in result["symbols"]}
    assert entries["BTC-USD"]["status"] == "error"
    assert entries["BTC-USD"]["failures"] == 1
    assert entries["ETH-USD"]["status"] == "stale"
    assert entries["NVDA"]["status"] == "observing"
    assert entries["NVDA"]["model_status"] == "warming_up"
    assert entries["NVDA"]["samples_learned"] == 3
    assert entries["NVDA"]["last_checked_at"] is not None
    assert "accuracy" not in json.dumps(result)
    # Status callers cannot alter the service's records.
    mutated = deepcopy(result)
    mutated["symbols"][0]["samples_learned"] = -100
    assert service.status()["symbols"][0]["samples_learned"] != -100


def test_sampling_disabled_never_requests_sources(monkeypatch):
    service = observer_service.ObserverService(sampling=False)

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        await asyncio.sleep(.01)
        assert service.status()["state"] == "disabled"
        stop.set()
        await asyncio.wait_for(task, .5)

    asyncio.run(run())
    assert all(item["status"] == "disabled" for item in service.status()["symbols"])
    assert service.status()["summary"]["observing"] == 0


def test_background_snapshot_does_not_refresh_browser_interest(monkeypatch):
    registrations = []
    monkeypatch.setattr(live_view, "snapshot", lambda symbol, **kwargs: (
        registrations.append(kwargs) or {"candles": [], "chart_source": "withheld", "feed_origin": "none", "feed_health": {}}))
    # Crypto remains on the stream path and never reaches the minute adapter.
    result = live_view.live_view_snapshot("BTC-USD", sampling=True, register_interest=False)
    assert result["candles"] == []
    assert live_view.viewer_interest_status()["active"] == []
    assert registrations == [{"sampling": True, "register_interest": False}]


def test_minute_requests_single_flight_per_symbol_without_blocking_other_names(monkeypatch):
    slow_started = threading.Event()
    release_slow = threading.Event()
    fast_finished = threading.Event()
    calls = []

    def fetch(symbol, *args, **kwargs):
        calls.append(symbol)
        if symbol == "SLOW":
            slow_started.set()
            assert release_slow.wait(3)
        else:
            fast_finished.set()
        return None

    monkeypatch.setattr(live_view.public_quotes, "fetch_public_candles", fetch)
    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(live_view._minute_payload, "SLOW")
        assert slow_started.wait(1)
        second = executor.submit(live_view._minute_payload, "SLOW")
        fast = executor.submit(live_view._minute_payload, "FAST")
        try:
            assert fast_finished.wait(1)
            assert fast.result(timeout=1) == (None, True)
        finally:
            release_slow.set()
        assert first.result(timeout=1) == second.result(timeout=1) == (None, True)
    assert calls.count("SLOW") == 1
    assert calls.count("FAST") == 1
