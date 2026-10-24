"""ATLAS live feed: ingest idempotency, parsers, status classification (US holidays), no-fake-price API checks."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.feeds import feed as feed_mod
from atlas.feeds.live import parse_binance, parse_coinbase, parse_kraken, parse_spark
from atlas.feeds.status import (DELAYED, LIVE, MARKET_CLOSED, NO_DATA, STALE, classify, nyse_open, toronto)
from atlas.feeds.store import FeedStore
from atlas.feeds.universe import resolve, ui_symbols

NY = ZoneInfo("America/New_York")


def et(*a) -> float:
    return datetime(*a, tzinfo=NY).timestamp()


# ------------------------------------------------------------ status classification
def test_crypto_live_and_stale():
    now = et(2026, 10, 23, 20, 0)
    assert classify("24x7", "binance", now - 5, now) == LIVE
    assert classify("24x7", "binance", now - 3600, now) == STALE
    assert classify("24x7", None, None, now) == NO_DATA


def test_equity_friday_evening_is_market_closed_with_last_close():
    now = et(2026, 10, 23, 20, 30)  # Fri evening after the close
    assert not nyse_open(now)
    assert classify("us_equity_rth", "yahoo", et(2026, 10, 23, 16, 0), now) == MARKET_CLOSED
    assert classify("us_equity_rth", "yahoo", et(2026, 10, 22, 16, 0), now) == STALE  # missed Friday's session


def test_equity_open_session_yahoo_is_delayed_then_stale():
    now = et(2026, 10, 22, 11, 0)
    assert nyse_open(now)
    assert classify("us_equity_rth", "yahoo", now - 600, now) == DELAYED
    assert classify("us_equity_rth", "yahoo", now - 3 * 3600, now) == STALE


@pytest.mark.parametrize("holiday, prev_close", [
    ((2026, 11, 26), (2026, 11, 25)),  # Thanksgiving (Thu)
    ((2026, 7, 3), (2026, 7, 2)),      # Independence Day observed (Fri)
    ((2026, 12, 25), (2026, 12, 24)),  # Christmas
])
def test_us_holidays_are_market_closed(holiday, prev_close):
    now = et(*holiday, 12, 0)
    assert not nyse_open(now)
    close = et(*prev_close, 13, 0) if prev_close == (2026, 12, 24) else et(*prev_close, 16, 0)
    assert classify("us_equity_rth", "yahoo", close, now) == MARKET_CLOSED


def test_weekend_is_market_closed():
    now = et(2026, 10, 25, 12, 0)
    assert classify("us_equity_rth", "yahoo", et(2026, 10, 23, 16, 0), now) == MARKET_CLOSED


def test_toronto_label():
    assert toronto(et(2026, 10, 23, 16, 0)).startswith("2026-10-23 16:00:00 E")


# ------------------------------------------------------------ parsers
def test_parsers():
    now = 1_800_000_000.0
    msg = {"stream": "btcusdt@kline_1m", "data": {"E": 1_800_000_000_000, "k": {
        "s": "BTCUSDT", "t": 1_799_999_940_000, "T": 1_799_999_999_999, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True}}}
    qs, bars = parse_binance(msg, now, {"BTCUSDT": "BTCUSDT"})
    assert qs[0]["price"] == 1.5 and qs[0]["provider"] == "binance" and len(bars) == 1
    cb = parse_coinbase({"type": "ticker", "product_id": "BTC-USD", "price": "100", "open_24h": "90",
                         "time": "2027-01-15T08:00:00Z"}, now, {"BTC-USD": "BTCUSDT"})
    assert cb[0]["price"] == 100 and cb[0]["prev_close"] == 90
    kr = parse_kraken({"channel": "ticker", "type": "update", "data": [{"symbol": "BTC/USD", "last": 101}]}, now, {"BTC/USD": "BTCUSDT"})
    assert kr[0]["price"] == 101 and kr[0]["event_time"] == now
    sp = parse_spark({"spark": {"result": [{"symbol": "AAPL", "response": [{"meta": {
        "regularMarketPrice": 200.0, "regularMarketTime": 1_799_990_000, "previousClose": 198.0}}]}]}}, now, {"AAPL": "AAPL"})
    assert sp[0]["price"] == 200.0 and sp[0]["provider"] == "yahoo"
    assert parse_coinbase({"type": "heartbeat"}, now, {}) == []


# ------------------------------------------------------------ ingest idempotency
def test_upsert_quotes_idempotent_and_never_older(tmp_path):
    s = FeedStore(tmp_path / "f.sqlite")
    row = {"instrument": "BTCUSDT", "provider": "binance", "price": 100.0, "event_time": 1000.0, "receipt_time": 1000.0, "kind": "kline"}
    s.upsert_quotes([row])
    s.upsert_quotes([row])
    s.upsert_quotes([{**row, "price": 50.0, "event_time": 900.0}])  # older print never replaces newer
    s.upsert_quotes([{**row, "price": 0.0, "event_time": 2000.0}])  # zero/invalid price never stored
    rows = s.last_quotes("BTCUSDT")
    assert len(rows) == 1 and rows[0]["price"] == 100.0 and rows[0]["event_time"] == 1000.0
    s.upsert_quotes([{**row, "price": 101.0, "event_time": 1001.0}])
    assert s.last_quotes("BTCUSDT")[0]["price"] == 101.0


def test_bars_ingest_idempotent(tmp_path):
    s = FeedStore(tmp_path / "f.sqlite")
    msg = {"data": {"E": 1_800_000_000_000, "k": {"s": "BTCUSDT", "t": 1_799_999_940_000, "T": 1_799_999_999_999,
                                                  "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True}}}
    for _ in range(3):
        _, bars = parse_binance(msg, 1_800_000_001.0, {"BTCUSDT": "BTCUSDT"})
        s.ingest(bars)
    n = len(s.bars("BTCUSDT", "1m"))
    assert n == 1


# ------------------------------------------------------------ universe coverage
def test_every_listing_symbol_resolves_to_feed():
    from atlas.api.app import _LIVE_LISTINGS_STATE
    missing = [r["symbol"] for r in _LIVE_LISTINGS_STATE if resolve(str(r["symbol"])) is None]
    assert missing == []
    assert len(ui_symbols()) >= 200


# ------------------------------------------------------------ no fake prices across UI data sources
@pytest.fixture()
def feed_store(tmp_path, monkeypatch):
    path = tmp_path / "feed.sqlite"
    store = FeedStore(path)
    now = time.time()
    store.upsert_quotes([{"instrument": "BTCUSDT", "provider": "binance", "price": 12345.0, "event_time": now - 2,
                          "receipt_time": now, "kind": "kline"}])
    old = feed_mod._DEFAULT
    feed_mod._DEFAULT = feed_mod.AtlasFeed(store)
    yield store
    feed_mod._DEFAULT = old


def _client():
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    return TestClient(app)


def test_listings_prices_come_only_from_feed(feed_store):
    body = _client().get("/api/listings").json()
    for r in body["listings"]:
        assert r["quote_status"] in ("live", "delayed", "market_closed", "stale", "no_data")
        if r["symbol"] in ("BTC-USD", "BTCUSDT", "BTC"):
            assert r["price"] == "12345.00" and r["quote_source"] == "binance" and r["quote_status"] == "live"
        elif r["quote_source"] is None:
            assert r["price"] is None, r  # no feed print -> no number
        for k in ("change_24h", "volume_24h", "spread_bps", "model_signal"):
            assert r.get(k) in (None,), (k, r)


def test_catalog_prices_come_only_from_feed(feed_store):
    c = _client()
    for path, key in (("/api/catalog/search?q=&limit=200", "results"), ("/api/catalog/snapshot", "listings")):
        rows = c.get(path).json().get(key) or []
        assert rows, path
        for r in rows:
            assert r["quote_status"] in ("live", "delayed", "market_closed", "stale", "no_data")
            if r["last_price"] is not None:
                assert r["quote_source"], r
            else:
                assert r["quote_status"] == "no_data"


def test_catalog_quotes_carry_status_and_source(feed_store):
    body = _client().get("/api/catalog/quotes?symbols=BTC-USD,AAPL").json()
    rows = {r["symbol"]: r for r in body.get("quotes", [])}
    assert rows["BTC-USD"]["price"] == 12345.0 and rows["BTC-USD"]["status"] == "live"
    for r in rows.values():
        assert r.get("status") and (r.get("source") or r.get("feed_origin"))
