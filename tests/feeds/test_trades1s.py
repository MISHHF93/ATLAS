"""1s crypto trade bars: parsers, aggregation (no forward fill, taker side, dedup, late drop), storage, rollup, retention."""
from __future__ import annotations

import sqlite3

from atlas.feeds.trades1s import (SecondAggregator, Trade, TradeBarStore, parse_coinbase_match, parse_kraken_trades)

T0 = 1_800_000_000


def tr(ts, price, qty, side="buy", tid=None, venue="kraken", inst="BTCUSDT"):
    return Trade(venue, inst, "BTC/USD", str(tid if tid is not None else f"{ts}-{price}-{qty}"), ts, price, qty, side)


def test_kraken_parser_uses_taker_side_and_ignores_snapshot():
    msg = {"channel": "trade", "type": "update", "data": [
        {"symbol": "BTC/USD", "side": "sell", "price": 100.5, "qty": 0.25, "ord_type": "market", "trade_id": 7, "timestamp": "2026-10-30T23:00:01.250000Z"},
        {"symbol": "XXX/USD", "side": "buy", "price": 1, "qty": 1, "trade_id": 8, "timestamp": "2026-10-30T23:00:01Z"},
        {"symbol": "BTC/USD", "side": "buy", "price": 0, "qty": 1, "trade_id": 9, "timestamp": "2026-10-30T23:00:01Z"}]}
    out = parse_kraken_trades(msg, {"BTC/USD": "BTCUSDT"})
    assert len(out) == 1 and out[0].taker_side == "sell" and out[0].instrument == "BTCUSDT" and out[0].qty == 0.25
    assert parse_kraken_trades({**msg, "type": "snapshot"}, {"BTC/USD": "BTCUSDT"}) == []


def test_coinbase_side_is_maker_so_taker_is_opposite():
    m = {"type": "match", "product_id": "BTC-USD", "side": "buy", "price": "100", "size": "0.5", "trade_id": 5, "time": "2026-10-30T23:00:01.5Z"}
    out = parse_coinbase_match(m, {"BTC-USD": "BTCUSDT"})
    assert len(out) == 1 and out[0].taker_side == "sell" and out[0].venue == "coinbase"
    assert parse_coinbase_match({**m, "side": "sell"}, {"BTC-USD": "BTCUSDT"})[0].taker_side == "buy"
    assert parse_coinbase_match({**m, "type": "last_match"}, {"BTC-USD": "BTCUSDT"}) == []
    assert parse_coinbase_match({**m, "product_id": "ZZZ-USD"}, {"BTC-USD": "BTCUSDT"}) == []


def test_aggregate_ohlcv_by_event_time_and_flow():
    a = SecondAggregator()
    # arrival order differs from event order inside the same second
    a.add(tr(T0 + 0.9, 101, 1, "buy", 1)); a.add(tr(T0 + 0.1, 100, 2, "sell", 2)); a.add(tr(T0 + 0.5, 103, 1, "buy", 3)); a.add(tr(T0 + 0.6, 99, 1, "sell", 4))
    assert a.drain(now=T0 + 1) == []                    # grace: still open
    (row,) = a.drain(now=T0 + 10)
    _v, _i, ts, o, h, l, c, vol, bv, sv, n, vn = row
    assert (ts, o, h, l, c, vol, bv, sv, n) == (T0, 100, 103, 99, 101, 5, 2, 3, 4)
    assert abs(vn - (101 * 1 + 100 * 2 + 103 * 1 + 99 * 1)) < 1e-9


def test_no_forward_fill_gap_seconds_have_no_rows():
    a = SecondAggregator()
    a.add(tr(T0, 10, 1, tid=1)); a.add(tr(T0 + 5, 11, 1, tid=2))
    rows = a.drain(now=T0 + 100)
    assert [r[2] for r in rows] == [T0, T0 + 5]


def test_dedup_and_late_drop_are_counted_not_merged():
    a = SecondAggregator()
    assert a.add(tr(T0, 10, 1, tid=1)) and not a.add(tr(T0, 10, 1, tid=1))
    a.add(tr(T0 + 10, 11, 1, tid=2))
    a.drain(now=T0 + 20)
    assert not a.add(tr(T0 + 1, 10, 1, tid=3))     # second T0+1 is already closed for this key
    assert a.stats["duplicates"] == 1 and a.stats["late_dropped"] == 1


def test_venues_are_never_mixed():
    a = SecondAggregator()
    a.add(tr(T0, 10, 1, venue="kraken", tid=1)); a.add(tr(T0, 20, 1, venue="coinbase", tid=1))
    rows = a.drain(now=T0 + 10)
    assert sorted((r[0], r[3]) for r in rows) == [("coinbase", 20), ("kraken", 10)]


def test_store_roundtrip_rollup_and_idempotence(tmp_path):
    st = TradeBarStore(tmp_path / "s.sqlite")
    a = SecondAggregator()
    base = (T0 // 60) * 60
    for k, (sec, p) in enumerate([(0, 10), (1, 12), (30, 9), (59, 11)]):
        a.add(tr(base + sec + 0.1, p, 1, "buy" if k % 2 == 0 else "sell", tid=k))
    a.add(tr(base + 61, 50, 1, tid=99))      # next minute, must not be rolled up yet
    assert st.write_bars(a.drain(now=base + 200)) == 5
    assert st.rollup_minutes(base + 61) == 1
    (m,) = st.flow_1m("kraken", "BTCUSDT", base, base + 60)
    ts, vol, bv, sv, n, vn, active, o, h, l, c = m
    assert (ts, vol, bv, sv, n, active, o, h, l, c) == (base, 4, 2, 2, 4, 4, 10, 12, 9, 11)
    assert st.rollup_minutes(base + 61) == 0 and len(st.flow_1m("kraken", "BTCUSDT", base, base + 60)) == 1
    assert len(st.bars_1s("kraken", "BTCUSDT", base, base + 60)) == 4
    cov = st.coverage()
    assert cov[0]["venue"] == "kraken" and cov[0]["rows"] == 5


def test_rewrite_keeps_the_fuller_second(tmp_path):
    st = TradeBarStore(tmp_path / "s.sqlite")
    row = ("kraken", "BTCUSDT", T0, 1, 2, 1, 2, 3, 1, 2, 3, 6.0)
    st.write_bars([row])
    st.write_bars([("kraken", "BTCUSDT", T0, 9, 9, 9, 9, 1, 1, 0, 1, 9.0)])   # fewer trades: ignored
    assert st.bars_1s("kraken", "BTCUSDT", T0, T0 + 1)[0][4] == 2
    st.write_bars([("kraken", "BTCUSDT", T0, 1, 5, 1, 5, 9, 1, 2, 5, 9.0)])   # more trades: replaces
    assert st.bars_1s("kraken", "BTCUSDT", T0, T0 + 1)[0][8] == 5


def test_prune_rolls_up_before_deleting_and_respects_windows(tmp_path):
    st = TradeBarStore(tmp_path / "s.sqlite", retain_1s_days=1, retain_flow_days=3)
    now = T0 + 10 * 86400
    old = ((now - 2 * 86400) // 60) * 60
    ancient = ((now - 5 * 86400) // 60) * 60
    st.write_bars([("kraken", "BTCUSDT", old + 1, 1, 1, 1, 1, 1, 1, 0, 1, 1.0), ("kraken", "BTCUSDT", ancient + 1, 1, 1, 1, 1, 1, 1, 0, 1, 1.0)])
    r = st.prune(now)
    assert r["deleted_1s"] == 2
    assert st.bars_1s("kraken", "BTCUSDT", 0, now) == []
    assert len(st.flow_1m("kraken", "BTCUSDT", 0, now)) == 1     # 2-day-old minute survives in the flow table; the 5-day-old one is gone


def test_disk_budget_halves_the_window(tmp_path):
    st = TradeBarStore(tmp_path / "s.sqlite", retain_1s_days=8, max_db_mb=0.0001)
    now = T0
    st.write_bars([("kraken", "BTCUSDT", now - int(d * 86400) + 1, 1, 1, 1, 1, 1, 1, 0, 1, 1.0) for d in (0.1, 0.5, 2, 5)])
    r = st.prune(now)
    assert r["window_days"] < 8 and r["deleted_1s"] >= 1


def test_live_ingest_routes_trade_messages(tmp_path):
    from atlas.feeds.live import LiveIngest
    from atlas.feeds.store import FeedStore
    ing = LiveIngest(FeedStore(tmp_path / "f.sqlite"))
    assert ing.trade_store is not None and str(ing.trade_store.path).endswith("atlas_1s.sqlite")
    iid = next(iter(ing.coinbase.values()))
    prod = next(iter(ing.coinbase))
    ing._on_coinbase({"type": "match", "product_id": prod, "side": "buy", "price": "10", "size": "1", "trade_id": 1, "time": "2026-10-30T23:00:01Z"}, 1.0)
    sym = next(iter(ing.kraken))
    kid = ing.kraken[sym]
    ing._on_kraken({"channel": "trade", "type": "update", "data": [{"symbol": sym, "side": "buy", "price": 5, "qty": 2, "trade_id": 1,
                                                                    "timestamp": "2026-10-30T23:00:01Z"}]}, 1.0)
    rows = ing.trades.drain(now=4_000_000_000)
    assert {(r[0], r[1]) for r in rows} == {("coinbase", iid), ("kraken", kid)}
    assert not (tmp_path / "f.sqlite").exists() or sqlite3.connect(tmp_path / "f.sqlite").execute("SELECT COUNT(*) FROM bar_revisions").fetchone()[0] == 0
