"""Catalog coverage: every asset the desk lists resolves to at least one provider, the free keyless sources serve what they can,
and a missing key / the free-data policy is reported as such (never as a silent empty chart)."""
from __future__ import annotations

import pytest

from atlas.feeds.coverage import PROXIES, asset_coverage, catalog_coverage
from atlas.feeds.feed import AtlasFeed, ProviderRegistry
from atlas.feeds.free_sources import SOURCES
from atlas.feeds.instruments import InstrumentMaster
from atlas.feeds.store import FeedStore
from atlas.feeds.universe import resolve, ui_symbols

KEYS = {"ALPACA_API_KEY_ID": "PKTEST", "ALPACA_API_SECRET_KEY": "secret"}


def _feed(env):
    return AtlasFeed(FeedStore(":memory:"), ProviderRegistry(env=env), InstrumentMaster())


def test_every_catalog_asset_resolves_to_a_provider_chain():
    feed = _feed({})
    names = set(feed.registry.names())
    unresolved = [s for s in ui_symbols() if not resolve(s)]
    assert unresolved == [], f"UI symbols with no feed instrument: {unresolved}"
    for s in ui_symbols():
        inst = feed.instruments.get(resolve(s))
        assert inst.provider_priority, f"{s} has no provider chain"
        for p in inst.provider_priority:
            assert p in names, f"{s}: provider {p} is not registered"
            assert p in SOURCES, f"{s}: provider {p} has no free-data terms entry"
    for fx in ("EUR_USD", "USD_CAD"):
        assert feed.instruments.get(fx).provider_priority


def test_proxy_targets_are_real_instruments():
    feed = _feed({})
    for alias, p in PROXIES.items():
        assert p["proxy"] in feed.instruments, alias
        assert p["instrument"] in feed.instruments, alias


def test_without_keys_fx_and_crypto_are_served_stocks_report_needs_key_futures_policy_blocked():
    cov = catalog_coverage(_feed({}))
    by = {a["instrument"]: a for a in cov["assets"]}
    assert by["EUR_USD"]["served_by"] == "ecb_fx" and by["EUR_USD"]["intervals"] == ["1d"] and by["EUR_USD"]["daily_only"]
    assert by["USD_CAD"]["served_by"] in ("boc_valet", "ecb_fx") and by["USD_CAD"]["daily_only"]
    assert by["BTCUSDT"]["served_by"] == "alpaca_crypto"
    for sym in ("AAPL", "SPY", "GLD", "QQQ"):
        assert by[sym]["status"] == "needs_key" and by[sym]["served_by"] is None
        assert "ALPACA_API_KEY_ID" in by[sym]["fix"]
    assert by["GC"]["status"] == "policy_blocked"           # databento is paid, yahoo is unofficial: both stay off
    assert not any(p["usable"] for p in by["GC"]["chain"])
    assert by["AAPL"]["label"] == "" and by["EUR_USD"]["label"].startswith("Daily reference rate only")


def test_alpaca_is_primary_when_keys_exist_and_falls_back_otherwise():
    with_alpaca = asset_coverage(_feed(dict(KEYS)), "AAPL")
    assert with_alpaca["served_by"] == "alpaca" and "1h" in with_alpaca["intervals"] and with_alpaca["status"] == "awaiting_data"
    only_tiingo = asset_coverage(_feed({"TIINGO_API_KEY": "x"}), "AAPL")
    assert only_tiingo["served_by"] == "tiingo"
    gld = asset_coverage(_feed(dict(KEYS)), "GLD")
    assert gld["served_by"] == "alpaca"


def test_free_data_gate_is_not_loosened_by_coverage():
    from atlas.feeds.free_sources import allowed
    assert not allowed("yahoo", {}) and not allowed("databento", {})
    chain = {p["provider"]: p for p in asset_coverage(_feed({}), "AAPL")["chain"]}
    assert chain["yahoo"]["policy_allowed"] is False and chain["yahoo"]["usable"] is False
    assert "ATLAS_ALLOW_UNOFFICIAL_DATA" in chain["yahoo"]["why"]


def test_a_key_saved_after_startup_enables_the_provider_without_restart(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    reg = ProviderRegistry()                       # env=None: the adapter follows the live environment
    a = reg.get("alpaca")
    assert not a.enabled and a.health().reason.startswith("missing_env")
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    a.refresh_env()
    assert a.enabled and a.health().reason is None


def test_aliases_for_the_alpaca_env_names(monkeypatch):
    for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "PKX")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sec")
    a = ProviderRegistry().get("alpaca")
    assert a.enabled


def test_catalog_health_endpoint_shape():
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    r = TestClient(app).get("/api/feeds/catalog-health?symbols=AAPL,EURUSD,XAUUSD,BTC-USD")
    assert r.status_code == 200
    j = r.json()
    assert j["timezone"] == "America/Toronto" and {a["instrument"] for a in j["assets"]} >= {"AAPL", "EUR_USD", "BTCUSDT"}
    assert all("chain" in a and "status" in a and "fix" in a for a in j["assets"])
    assert {p["symbol"] for p in j["proxies"]} == set(PROXIES)
