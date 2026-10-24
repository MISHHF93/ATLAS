"""/api/feeds/health performance: index migration on existing stores + synthetic large store under 1 s."""
from __future__ import annotations

import sqlite3
import time

import pytest

from atlas.feeds import feed as feed_mod
from atlas.feeds.core import FeedBar
from atlas.feeds.store import REQUIRED_INDEXES, FeedStore
from atlas.feeds.universe import resolve, ui_symbols


def test_new_store_has_required_indexes(tmp_path):
    store = FeedStore(tmp_path / "f.sqlite")
    assert set(REQUIRED_INDEXES) <= store.indexes()
    assert store._fetchone("PRAGMA journal_mode")[0] == "wal"
    assert store._fetchone("PRAGMA busy_timeout")[0] >= 1000


def test_migration_adds_index_to_existing_store_and_keeps_data(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)  # pre-migration schema: only the original lookup index
    db.executescript("""CREATE TABLE bar_revisions (provider TEXT NOT NULL, instrument TEXT NOT NULL, interval TEXT NOT NULL,
      event_time INTEGER NOT NULL, receipt_time INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL,
      confirmed INTEGER NOT NULL, provider_symbol TEXT, PRIMARY KEY (provider, instrument, interval, event_time, receipt_time));
      CREATE INDEX ix_rev_lookup ON bar_revisions(instrument, interval, provider, event_time);
      INSERT INTO bar_revisions VALUES ('binance','BTCUSDT','1m',60,120,1,1,1,1,1,1,'');""")
    db.commit(); db.close()
    store = FeedStore(path)
    assert "ix_rev_latest" in store.indexes()
    assert store.latest_bar("BTCUSDT").close == 1
    plan = " ".join(str(r) for r in store._fetchall(
        "EXPLAIN QUERY PLAN SELECT * FROM bar_revisions WHERE instrument=? AND interval=? "
        "ORDER BY event_time DESC, receipt_time DESC LIMIT 1", ("BTCUSDT", "1m")))
    assert "TEMP B-TREE" not in plan
    FeedStore(path)  # re-open is a no-op


@pytest.fixture()
def big_feed(tmp_path):
    store = FeedStore(tmp_path / "big.sqlite")
    now = int(time.time()) // 60 * 60
    insts = sorted({resolve(s) or s.upper() for s in ui_symbols()})
    rows = []
    for inst in insts:
        for iv, step, n in (("1m", 60, 1500), ("15m", 900, 1500), ("1d", 86400, 300)):
            for k in range(n):
                t = now - (k + 1) * step
                rows.append(("synthetic", inst, iv, t, t + step + 1, 100.0, 101.0, 99.0, 100.5, 10.0, 1, ""))
    with store._db:
        store._db.executemany("INSERT INTO bar_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    old = feed_mod._DEFAULT
    feed_mod._DEFAULT = feed_mod.AtlasFeed(store)
    yield store, len(rows)
    feed_mod._DEFAULT = old


def test_health_fast_on_large_synthetic_store(big_feed):
    from atlas.api.feeds_api import feed_health
    store, n = big_feed
    assert n > 200_000
    t = time.perf_counter()
    out = feed_health(None)
    dt = time.perf_counter() - t
    assert out["store_present"] and len(out["symbols"]) == len(ui_symbols())
    assert any(r["last_bar_interval"] for r in out["symbols"])
    assert dt < 1.0, f"/api/feeds/health took {dt:.2f}s"


def test_health_ttl_cache(big_feed, monkeypatch):
    from atlas.api import feeds_api
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    feeds_api._health_cache.clear()
    a = feeds_api.api_feed_health("BTC-USD", fresh=False)
    b = feeds_api.api_feed_health("BTC-USD", fresh=False)
    c = feeds_api.api_feed_health("BTC-USD", fresh=True)
    assert a is b and c is not a
    feeds_api._health_cache.clear()
