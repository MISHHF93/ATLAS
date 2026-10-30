"""ATLAS live feed: ingest idempotency, parsers, status classification (US holidays), no-fake-price API checks."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.feeds import feed as feed_mod
from atlas.feeds.core import FeedBar
from atlas.feeds.live import KrakenBars, LiveIngest, parse_coinbase, parse_kraken, parse_spark
from atlas.feeds.status import (DELAYED, LIVE, MARKET_CLOSED, NO_DATA, STALE, classify, nyse_open, toronto)
from atlas.feeds.store import FeedStore
from atlas.feeds.universe import resolve, ui_symbols

NY = ZoneInfo("America/New_York")


def et(*a) -> float:
    return datetime(*a, tzinfo=NY).timestamp()


# ------------------------------------------------------------ status classification
def test_crypto_live_and_stale():
    now = et(2026, 10, 23, 20, 0)
    assert classify("24x7", "coinbase", now - 5, now) == LIVE
    assert classify("24x7", "coinbase", now - 3600, now) == STALE
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
    row = {"instrument": "BTCUSDT", "provider": "kraken", "price": 100.0, "event_time": 1000.0, "receipt_time": 1000.0, "kind": "ohlc"}
    s.upsert_quotes([row])
    s.upsert_quotes([row])
    s.upsert_quotes([{**row, "price": 50.0, "event_time": 900.0}])  # older print never replaces newer
    s.upsert_quotes([{**row, "price": 0.0, "event_time": 2000.0}])  # zero/invalid price never stored
    rows = s.last_quotes("BTCUSDT")
    assert len(rows) == 1 and rows[0]["price"] == 100.0 and rows[0]["event_time"] == 1000.0
    s.upsert_quotes([{**row, "price": 101.0, "event_time": 1001.0}])
    assert s.last_quotes("BTCUSDT")[0]["price"] == 101.0


def test_rollup_stores_a_complete_15m_and_skips_a_partial_hour(tmp_path):
    t0 = 1_700_000_000 - 1_700_000_000 % 900
    store = FeedStore(tmp_path / "f.sqlite")
    ing = LiveIngest(store)
    bars = [FeedBar("BTCUSDT", "1m", t0 + i * 60, 1, 2, 0.5, 1.5, 3, "kraken", t0 + (i + 1) * 60, True, "BTCUSDT") for i in range(15)]
    store.ingest(bars)
    rolled = ing._rollup(bars)
    got = [b for b in rolled if b.interval == "15m"]
    assert len(got) == 1 and got[0].event_time == t0 and got[0].confirmed and got[0].close == 1.5
    assert not any(b.interval == "1h" for b in rolled)


def test_ensure_recent_fetches_a_stale_interval_once(tmp_path, monkeypatch):
    from atlas.feeds.feed import AtlasFeed
    store = FeedStore(tmp_path / "f.sqlite")
    feed = AtlasFeed(store=store, clock=lambda: 1_000_000.0)
    calls = []
    monkeypatch.setattr(feed, "fetch", lambda *a, **k: calls.append(a) or ("coinbase", {}))
    monkeypatch.setattr(store, "latest_bar", lambda *a, **k: type("B", (), {"bar_end": 1})())
    assert feed.ensure_recent("BTCUSDT", "15m") is True
    assert feed.ensure_recent("BTCUSDT", "15m") is False
    assert len(calls) == 1 and calls[0][0] == "BTCUSDT" and calls[0][1] == "15m"
    fresh = AtlasFeed(store=store, clock=lambda: 1_000_000.0)
    monkeypatch.setattr(fresh, "fetch", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(store, "latest_bar", lambda *a, **k: type("B", (), {"bar_end": 1_000_000})())
    assert fresh.ensure_recent("BTCUSDT", "15m") is False
    assert len(calls) == 1


def test_ensure_recent_does_not_write_yahoo_bars(tmp_path, monkeypatch):
    from atlas.feeds.feed import AtlasFeed
    store = FeedStore(tmp_path / "f.sqlite")
    feed = AtlasFeed(store=store, clock=lambda: 1_000_000.0)
    monkeypatch.setattr(feed, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no official candidate, no fetch")))
    monkeypatch.setattr(feed, "candidates", lambda *a, **k: [])
    monkeypatch.setattr(store, "latest_bar", lambda *a, **k: type("B", (), {"bar_end": 1_000, "provider": "yahoo"})())
    assert feed.ensure_recent("SPY", "15m") is False
    assert store.bars("SPY", "15m") == []


def test_provider_switch_wider_than_25bp_is_left_as_a_hole(tmp_path):
    from atlas.feeds.feed import AtlasFeed
    store = FeedStore(tmp_path / "f.sqlite")
    feed = AtlasFeed(store=store)
    t0 = 1_700_000_000
    store.ingest([
        FeedBar("BTCUSDT", "1h", t0, 100, 101, 99, 100, 1, "alpaca_crypto", t0 + 3600, True, "BTC/USD"),
        FeedBar("BTCUSDT", "1h", t0 + 3600, 100.1, 101, 99, 100.2, 1, "coinbase", t0 + 7200, True, "BTC-USD"),
        FeedBar("BTCUSDT", "1h", t0 + 7200, 105, 106, 104, 105, 1, "kraken", t0 + 10800, True, "XBTUSD"),
        FeedBar("BTCUSDT", "1h", t0 + 10800, 105.2, 106, 104, 105.4, 1, "coinbase", t0 + 14400, True, "BTC-USD"),
    ])
    out = feed.bars("BTCUSDT", "1h")
    assert [b.event_time for b in out] == [t0, t0 + 3600, t0 + 10800]
    assert [b.provider for b in out] == ["alpaca_crypto", "coinbase", "coinbase"]
    # A new venue that stays dislocated does not take over the rest of the series.
    store.ingest([
        FeedBar("ETHUSDT", "1h", t0, 100, 101, 99, 100, 1, "alpaca_crypto", t0 + 3600, True, "ETH/USD"),
        FeedBar("ETHUSDT", "1h", t0 + 3600, 100.5, 101, 99, 100.6, 1, "coinbase", t0 + 7200, True, "ETH-USD"),
        FeedBar("ETHUSDT", "1h", t0 + 7200, 100.7, 101, 99, 100.8, 1, "coinbase", t0 + 10800, True, "ETH-USD"),
    ])
    eth = feed.bars("ETHUSDT", "1h")
    assert [b.event_time for b in eth] == [t0]


def test_authoritative_bars_omit_yahoo(tmp_path):
    from atlas.feeds.feed import AtlasFeed
    store = FeedStore(tmp_path / "f.sqlite")
    feed = AtlasFeed(store=store)
    store.ingest([FeedBar("SPY", "15m", 1_000, 1, 2, 0.5, 1.5, 3, "yahoo", 2_000, True, "SPY")])
    assert store.bars("SPY", "15m")[-1].provider == "yahoo"
    assert feed.bars("SPY", "15m") == []


def _ohlc(sym, begin, o, h, l, c, v, typ="update"):
    return {"channel": "ohlc", "type": typ, "data": [{"symbol": sym, "open": o, "high": h, "low": l, "close": c, "volume": v,
                                                       "interval_begin": begin, "interval": 1}]}


def test_kraken_ohlc_emits_a_bar_only_once_a_newer_minute_arrives():
    kb, by = KrakenBars(), {"BTC/USD": "BTCUSDT"}
    qs, bars = kb.feed(_ohlc("BTC/USD", "2026-10-30T12:00:00.000000Z", 1, 2, 0.5, 1.2, 3), 1_700_000_100.0, by)
    assert qs[0]["provider"] == "kraken" and qs[0]["instrument"] == "BTCUSDT" and bars == []
    qs, bars = kb.feed(_ohlc("BTC/USD", "2026-10-30T12:00:00.000000Z", 1, 2, 0.5, 1.5, 4), 1_700_000_110.0, by)   # same minute, still forming
    assert bars == []
    qs, bars = kb.feed(_ohlc("BTC/USD", "2026-10-30T12:01:00.000000Z", 1.5, 2, 1, 1.6, 1), 1_700_000_160.0, by)
    assert len(bars) == 1 and bars[0].confirmed and bars[0].close == 1.5 and bars[0].volume == 4 and bars[0].provider == "kraken"
    assert bars[0].interval == "1m" and bars[0].event_time == 1_793_361_600
    assert kb.feed(_ohlc("BTC/USD", "2026-10-30T11:59:00.000000Z", 9, 9, 9, 9, 9), 1_700_000_170.0, by)[1] == []   # stale
    assert kb.feed(_ohlc("ETH/USD", "2026-10-30T12:00:00.000000Z", 1, 1, 1, 1, 1), 1.0, by) == ([], [])             # not subscribed
    assert kb.feed({"channel": "ticker", "type": "update", "data": []}, 1.0, by) == ([], [])


def test_kraken_snapshot_closed_candles_are_bars():
    kb = KrakenBars()
    snap = {"channel": "ohlc", "type": "snapshot", "data": [
        {"symbol": "BTC/USD", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, "interval_begin": "2026-10-30T12:01:00Z"},
        {"symbol": "BTC/USD", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "interval_begin": "2026-10-30T12:00:00Z"}]}
    _, bars = kb.feed(snap, 1.0, {"BTC/USD": "BTCUSDT"})
    assert [b.close for b in bars] == [1.0]   # the older candle is closed, the newest is still forming


def test_live_ingest_subscribes_to_coinbase_and_kraken_usd_only(tmp_path):
    ing = LiveIngest(FeedStore(tmp_path / "f.sqlite"))
    assert ing.coinbase["BTC-USD"] == "BTCUSDT" and ing.kraken["BTC/USD"] == "BTCUSDT" and ing.kraken["DOGE/USD"] == "DOGEUSDT"
    assert all(k.endswith("-USD") for k in ing.coinbase) and all(k.endswith("/USD") for k in ing.kraken)
    assert not hasattr(ing, "binance") and not hasattr(ing, "okx")


def test_bars_ingest_idempotent(tmp_path):
    s = FeedStore(tmp_path / "f.sqlite")
    kb, by = KrakenBars(), {"BTC/USD": "BTCUSDT"}
    kb.feed(_ohlc("BTC/USD", "2026-10-30T12:00:00Z", 1, 2, 0.5, 1.5, 10), 1.0, by)
    _, bars = kb.feed(_ohlc("BTC/USD", "2026-10-30T12:01:00Z", 1, 2, 0.5, 1.5, 10), 2.0, by)
    for _ in range(3):
        s.ingest(bars)
    assert len(s.bars("BTCUSDT", "1m")) == 1


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
    store.upsert_quotes([{"instrument": "BTCUSDT", "provider": "coinbase", "price": 12345.0, "event_time": now - 2,
                          "receipt_time": now, "kind": "ticker"}])
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
            assert r["price"] == "12345.00" and r["quote_source"] == "coinbase" and r["quote_status"] == "live"
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
