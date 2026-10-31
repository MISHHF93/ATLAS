"""1-second crypto trade bars from the Kraken v2 ``trade`` and Coinbase ``matches`` websocket channels.

Real exchange trades only. A second in which no trade printed has NO row: nothing is forward-filled, so a missing second
is "no trade", never an invented price. Venues are never mixed (one row per venue, instrument, second).

Side convention (``taker_side``), the aggressor, because that is what order-flow imbalance needs:
* Kraken v2 ``trade``: ``side`` is the taker side already (buy = a buyer lifted the ask).
* Coinbase ``match``: ``side`` is the MAKER order's side (the order that was resting), so the taker is the opposite.

Storage is a separate SQLite file (default ``var/feeds/atlas_1s.sqlite``) so the point-in-time feed store stays small:
* ``bars_1s``   one row per traded second, kept ``RETAIN_1S_DAYS`` days (default 7);
* ``flow_1m``   a per-minute roll-up of the same trades (count, buy/sell volume, vwap numerator, active seconds), kept
                ``RETAIN_FLOW_DAYS`` days (default 90). It is rolled up BEFORE the 1s rows are pruned;
* a hard disk budget (``MAX_DB_MB``, default 2048): when the file is larger, the 1s window is halved until it fits.
Nothing here places an order. ``execution_permission`` is none everywhere downstream.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_DB = "var/feeds/atlas_1s.sqlite"
RETAIN_1S_DAYS = 7
RETAIN_FLOW_DAYS = 90
MAX_DB_MB = 2048
GRACE_S = 3          # a second is closed (and written) once now >= second + 1 + GRACE_S
DEDUP_IDS = 4096     # recent trade ids remembered per (venue, symbol)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_1s(
  venue TEXT NOT NULL, instrument TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  volume REAL NOT NULL, buy_vol REAL NOT NULL, sell_vol REAL NOT NULL, n_trades INTEGER NOT NULL, vwap_num REAL NOT NULL,
  PRIMARY KEY(venue, instrument, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS flow_1m(
  venue TEXT NOT NULL, instrument TEXT NOT NULL, ts INTEGER NOT NULL,
  volume REAL NOT NULL, buy_vol REAL NOT NULL, sell_vol REAL NOT NULL, n_trades INTEGER NOT NULL, vwap_num REAL NOT NULL,
  active_s INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  PRIMARY KEY(venue, instrument, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


@dataclass
class Trade:
    venue: str
    instrument: str
    symbol: str
    trade_id: str
    ts: float          # exchange event time, unix seconds
    price: float
    qty: float
    taker_side: str    # "buy" | "sell"


def _iso(t: str) -> float:
    return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()


def parse_kraken_trades(msg: dict, by_symbol: dict[str, str]) -> list[Trade]:
    if msg.get("channel") != "trade" or msg.get("type") != "update":
        return []   # snapshots are historical replays; only live updates are aggregated
    out = []
    for d in msg.get("data") or []:
        iid = by_symbol.get(d.get("symbol"))
        try:
            side = str(d["side"]).lower()
            if not iid or side not in ("buy", "sell"):
                continue
            p, q = float(d["price"]), float(d["qty"])
            if not (p > 0 and q > 0):
                continue
            out.append(Trade("kraken", iid, d["symbol"], str(d["trade_id"]), _iso(d["timestamp"]), p, q, side))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def parse_coinbase_match(msg: dict, by_product: dict[str, str]) -> list[Trade]:
    if msg.get("type") != "match":   # "last_match" is the replayed snapshot on subscribe and is skipped
        return []
    iid = by_product.get(msg.get("product_id"))
    try:
        maker = str(msg["side"]).lower()
        if not iid or maker not in ("buy", "sell"):
            return []
        p, q = float(msg["price"]), float(msg["size"])
        if not (p > 0 and q > 0):
            return []
        return [Trade("coinbase", iid, msg["product_id"], str(msg["trade_id"]), _iso(msg["time"]), p, q,
                      "sell" if maker == "buy" else "buy")]
    except (KeyError, ValueError, TypeError):
        return []


class SecondAggregator:
    """In-memory open-second buckets. Drain closed ones with :meth:`drain`."""

    def __init__(self, grace_s: int = GRACE_S):
        self.grace_s = grace_s
        self.open: dict[tuple[str, str, int], dict] = {}
        self._seen: dict[tuple[str, str], tuple[deque, set]] = {}
        self._closed_upto: dict[tuple[str, str], int] = {}
        self.stats = {"trades": 0, "duplicates": 0, "late_dropped": 0, "bars": 0}

    def add(self, tr: Trade, now: float | None = None) -> bool:
        key = (tr.venue, tr.instrument)
        q, s = self._seen.setdefault(key, (deque(), set()))
        tid = (tr.symbol, tr.trade_id)
        if tid in s:
            self.stats["duplicates"] += 1
            return False
        sec = int(tr.ts)
        if sec <= self._closed_upto.get(key, -1):
            self.stats["late_dropped"] += 1     # arrived after its second was written; dropped and counted, not merged
            return False
        q.append(tid)
        s.add(tid)
        if len(q) > DEDUP_IDS:
            s.discard(q.popleft())
        b = self.open.get((tr.venue, tr.instrument, sec))
        buy, sell = (tr.qty, 0.0) if tr.taker_side == "buy" else (0.0, tr.qty)
        if b is None:
            self.open[(tr.venue, tr.instrument, sec)] = {"o": tr.price, "h": tr.price, "l": tr.price, "c": tr.price, "t_last": tr.ts,
                                                           "t_first": tr.ts, "v": tr.qty, "bv": buy, "sv": sell, "n": 1, "vn": tr.price * tr.qty}
        else:
            # open/close follow event time, not arrival order
            if tr.ts < b["t_first"]:
                b["o"], b["t_first"] = tr.price, tr.ts
            if tr.ts >= b["t_last"]:
                b["c"], b["t_last"] = tr.price, tr.ts
            b["h"], b["l"] = max(b["h"], tr.price), min(b["l"], tr.price)
            b["v"] += tr.qty
            b["bv"] += buy
            b["sv"] += sell
            b["n"] += 1
            b["vn"] += tr.price * tr.qty
        self.stats["trades"] += 1
        return True

    def drain(self, now: float | None = None, force: bool = False) -> list[tuple]:
        """Rows (venue, instrument, ts, o, h, l, c, vol, buy_vol, sell_vol, n, vwap_num) for seconds that can no longer change."""
        now = time.time() if now is None else now
        cutoff = int(now) - 1 - self.grace_s
        rows, done = [], []
        for (venue, inst, sec), b in self.open.items():
            if force or sec <= cutoff:
                rows.append((venue, inst, sec, b["o"], b["h"], b["l"], b["c"], b["v"], b["bv"], b["sv"], b["n"], b["vn"]))
                done.append((venue, inst, sec))
        for k in done:
            del self.open[k]
            key = (k[0], k[1])
            self._closed_upto[key] = max(self._closed_upto.get(key, -1), k[2])
        self.stats["bars"] += len(rows)
        rows.sort(key=lambda r: (r[2], r[0], r[1]))
        return rows


class TradeBarStore:
    def __init__(self, path: str | Path = DEFAULT_DB, retain_1s_days: float = RETAIN_1S_DAYS,
                 retain_flow_days: float = RETAIN_FLOW_DAYS, max_db_mb: float = MAX_DB_MB):
        self.path = Path(path)
        self.retain_1s_days, self.retain_flow_days, self.max_db_mb = retain_1s_days, retain_flow_days, max_db_mb
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            c.execute("PRAGMA journal_mode=WAL")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def write_bars(self, rows: list[tuple]) -> int:
        if not rows:
            return 0
        with self._lock, self._conn() as c:
            # INSERT OR REPLACE would drop a partially written second after a restart; a re-seen second keeps the larger trade count
            c.executemany(
                "INSERT INTO bars_1s VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(venue,instrument,ts) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, volume=excluded.volume, "
                "buy_vol=excluded.buy_vol, sell_vol=excluded.sell_vol, n_trades=excluded.n_trades, vwap_num=excluded.vwap_num "
                "WHERE excluded.n_trades > bars_1s.n_trades", rows)
        return len(rows)

    def rollup_minutes(self, upto_ts: int | None = None) -> int:
        """Roll COMPLETE minutes of 1s bars into flow_1m (idempotent: a minute is rebuilt from its 1s rows)."""
        upto = (int(time.time() if upto_ts is None else upto_ts) // 60) * 60   # minutes strictly before this one
        with self._lock, self._conn() as c:
            row = c.execute("SELECT v FROM meta WHERE k='flow_done'").fetchone()
            since = int(row[0]) if row else 0
            if since == 0:
                r = c.execute("SELECT MIN(ts) FROM bars_1s").fetchone()
                since = (int(r[0]) // 60) * 60 if r and r[0] is not None else upto
            if since >= upto:
                return 0
            cur = c.execute(
                "INSERT OR REPLACE INTO flow_1m "
                "WITH s AS (SELECT *, (ts/60)*60 AS m, "
                "ROW_NUMBER() OVER (PARTITION BY venue, instrument, ts/60 ORDER BY ts) AS rn, "
                "ROW_NUMBER() OVER (PARTITION BY venue, instrument, ts/60 ORDER BY ts DESC) AS rd "
                "FROM bars_1s WHERE ts>=? AND ts<?) "
                "SELECT venue, instrument, m, SUM(volume), SUM(buy_vol), SUM(sell_vol), SUM(n_trades), SUM(vwap_num), COUNT(*), "
                "MAX(CASE WHEN rn=1 THEN open END), MAX(high), MIN(low), MAX(CASE WHEN rd=1 THEN close END) "
                "FROM s GROUP BY venue, instrument, m", (since, upto))
            c.execute("INSERT INTO meta(k,v) VALUES('flow_done',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(upto),))
            return cur.rowcount

    def db_mb(self) -> float:
        n = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                n += p.stat().st_size
        return n / 1048576

    def prune(self, now: float | None = None) -> dict:
        """Roll up, then drop 1s rows older than the window and flow rows older than theirs. Over budget: halve the 1s window."""
        now = time.time() if now is None else now
        self.rollup_minutes(int(now))
        days = self.retain_1s_days
        with self._lock, self._conn() as c:
            d1 = c.execute("DELETE FROM bars_1s WHERE ts < ?", (int(now - days * 86400),)).rowcount
            d2 = c.execute("DELETE FROM flow_1m WHERE ts < ?", (int(now - self.retain_flow_days * 86400),)).rowcount
        shrunk = 0
        while self.db_mb() > self.max_db_mb and days > 0.25:
            days /= 2
            with self._lock, self._conn() as c:
                shrunk += c.execute("DELETE FROM bars_1s WHERE ts < ?", (int(now - days * 86400),)).rowcount
        if d1 or d2 or shrunk:
            with self._lock, self._conn() as c:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"deleted_1s": d1 + shrunk, "deleted_flow": d2, "window_days": days, "db_mb": round(self.db_mb(), 1)}

    # ------------------------------------------------------------- reads (read-only connection, never blocks the writer)
    def _ro(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=30)

    def bars_1s(self, venue: str, instrument: str, start: int, end: int) -> list[tuple]:
        with self._ro() as c:
            return c.execute("SELECT ts,open,high,low,close,volume,buy_vol,sell_vol,n_trades,vwap_num FROM bars_1s "
                             "WHERE venue=? AND instrument=? AND ts>=? AND ts<? ORDER BY ts", (venue, instrument, int(start), int(end))).fetchall()

    def flow_1m(self, venue: str, instrument: str, start: int, end: int) -> list[tuple]:
        with self._ro() as c:
            return c.execute("SELECT ts,volume,buy_vol,sell_vol,n_trades,vwap_num,active_s,open,high,low,close FROM flow_1m "
                             "WHERE venue=? AND instrument=? AND ts>=? AND ts<? ORDER BY ts", (venue, instrument, int(start), int(end))).fetchall()

    def coverage(self) -> list[dict]:
        with self._ro() as c:
            rows = c.execute("SELECT venue, COUNT(DISTINCT instrument), COUNT(*), MIN(ts), MAX(ts) FROM bars_1s GROUP BY venue").fetchall()
        return [{"venue": v, "instruments": n, "rows": r, "first": a, "last": b} for v, n, r, a, b in rows]
