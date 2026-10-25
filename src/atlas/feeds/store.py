"""Point-in-time bar store (SQLite under var/, never committed).

Every received version of a bar is kept (``bar_revisions``) keyed by provider/instrument/interval/event_time/receipt_time;
identical re-ingests are deduplicated (idempotent). ``as_of(t)`` returns only versions with receipt_time <= t, so
training/replay never sees revisions that were not yet known. ``bars()`` = latest confirmed version per bar from the
chosen provider."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Sequence

from .core import INTERVALS, FeedBar, FeedObservation

SCHEMA = """
CREATE TABLE IF NOT EXISTS bar_revisions (
  provider TEXT NOT NULL, instrument TEXT NOT NULL, interval TEXT NOT NULL, event_time INTEGER NOT NULL,
  receipt_time INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL,
  confirmed INTEGER NOT NULL, provider_symbol TEXT,
  PRIMARY KEY (provider, instrument, interval, event_time, receipt_time));
CREATE INDEX IF NOT EXISTS ix_rev_lookup ON bar_revisions(instrument, interval, provider, event_time);
CREATE TABLE IF NOT EXISTS observations (
  provider TEXT, series TEXT, date TEXT, realtime_start TEXT, value REAL, receipt_time INTEGER,
  PRIMARY KEY (provider, series, date, realtime_start));
CREATE TABLE IF NOT EXISTS last_quotes (
  instrument TEXT NOT NULL, provider TEXT NOT NULL, price REAL NOT NULL, event_time REAL NOT NULL, receipt_time REAL NOT NULL,
  prev_close REAL, kind TEXT, provider_symbol TEXT, PRIMARY KEY (instrument, provider));
CREATE TABLE IF NOT EXISTS ingest_log (
  ts INTEGER, provider TEXT, instrument TEXT, interval TEXT, received INTEGER, inserted INTEGER, revised INTEGER, note TEXT);
"""


# Indexes added after the first release. Applied by ``migrate()`` on open; ``CREATE INDEX IF NOT EXISTS`` is idempotent
# and safe on a live store (it takes the write lock once; concurrent writers wait on busy_timeout, WAL readers continue).
# ix_rev_latest lets latest_bar()/bars() read "newest bar for instrument+interval" by an index seek instead of sorting
# every revision of the series in a temp B-tree (the cause of the ~41 s /api/feeds/health on a 1.7M-revision store).
MIGRATIONS = (
    ("ix_rev_latest", "CREATE INDEX IF NOT EXISTS ix_rev_latest ON bar_revisions(instrument, interval, event_time, receipt_time)"),
)
REQUIRED_INDEXES = ("ix_rev_lookup",) + tuple(n for n, _ in MIGRATIONS)


class FeedStore:
    def __init__(self, path: str | Path = "var/feeds/atlas_feed.sqlite"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        if self.path != ":memory:":
            # The live-ingest process writes while the API process reads: WAL + busy timeout, no reader blocking.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=30000")
            self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()  # also serialises reads: one sqlite connection is shared by the API threadpool
        self.migrate()

    def migrate(self) -> list[str]:
        """Create any missing post-release indexes. Never raises on a busy store (retried on next open)."""
        have = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        done = []
        for name, sql in MIGRATIONS:
            if name in have:
                continue
            try:
                with self._lock, self._db:
                    self._db.execute(sql)
                done.append(name)
            except sqlite3.OperationalError:  # locked past busy_timeout: leave it for the next start
                pass
        return done

    def indexes(self) -> set[str]:
        return {r[0] for r in self._fetchall("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bar_revisions'")}

    # ---- ingest ----
    def _fetchall(self, sql: str, params=()):
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params=()):
        with self._lock:
            return self._db.execute(sql, params).fetchone()

    def ingest(self, bars: Iterable[FeedBar], note: str = "") -> dict:
        """Idempotent. A version is inserted only if OHLCV/confirmed differs from the latest stored version."""
        batch = list(bars)
        if not batch:
            return {"received": 0, "inserted": 0, "revised": 0}
        rec = ins = rev = 0
        last = batch[-1]
        with self._lock, self._db:
            groups: dict[tuple[str, str, str], list[int]] = {}
            for b in batch:
                k = (b.provider, b.instrument, b.interval)
                ts = groups.get(k)
                if ts is None:
                    groups[k] = [b.event_time, b.event_time]
                else:
                    if b.event_time < ts[0]:
                        ts[0] = b.event_time
                    if b.event_time > ts[1]:
                        ts[1] = b.event_time
            latest: dict[tuple[str, str, str, int], tuple[int, float, float, float, float, float, int]] = {}
            for (prov, inst, iv), (t0, t1) in groups.items():
                for et, rt, o, h, l_, c, v, conf in self._db.execute(
                    "SELECT event_time,receipt_time,open,high,low,close,volume,confirmed FROM bar_revisions "
                    "WHERE provider=? AND instrument=? AND interval=? AND event_time>=? AND event_time<=? "
                    "ORDER BY event_time ASC, receipt_time ASC",
                    (prov, inst, iv, t0, t1),
                ):
                    latest[(prov, inst, iv, et)] = (rt, o, h, l_, c, v, conf)
            to_insert = []
            for b in batch:
                rec += 1
                key = (b.provider, b.instrument, b.interval, b.event_time)
                cur_entry = latest.get(key)
                new = (b.open, b.high, b.low, b.close, b.volume, int(b.confirmed))
                if cur_entry is not None:
                    cur = cur_entry[1:]
                    if cur == new or (cur[5] == 1 and not b.confirmed and cur[:5] == new[:5]):
                        continue
                    if cur[5] == 1 and not b.confirmed:
                        continue  # never downgrade a confirmed bar with a provisional version
                    rev += 1
                else:
                    ins += 1
                to_insert.append((b.provider, b.instrument, b.interval, b.event_time, b.receipt_time, *new, b.provider_symbol))
                if cur_entry is None or b.receipt_time >= cur_entry[0]:
                    latest[key] = (b.receipt_time, *new)
            if to_insert:
                self._db.executemany("INSERT OR IGNORE INTO bar_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", to_insert)
            self._db.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?,?,?,?)",
                             (last.receipt_time, last.provider, last.instrument, last.interval, rec, ins, rev, note))
        return {"received": rec, "inserted": ins, "revised": rev}

    def upsert_quotes(self, rows: Iterable[dict]) -> int:
        """Latest print per (instrument, provider) from a live stream/poll. Idempotent: an older or identical print never
        replaces a newer one. ``kind`` = trade | ticker | kline | spark | bar_close."""
        n = 0
        with self._lock, self._db:
            for r in rows:
                if not (r.get("price") and r["price"] > 0):
                    continue
                cur = self._fetchone("SELECT event_time, price FROM last_quotes WHERE instrument=? AND provider=?",
                                       (r["instrument"], r["provider"]))
                if cur is not None and (cur[0] > r["event_time"] or (cur[0] == r["event_time"] and cur[1] == r["price"])):
                    continue
                self._db.execute("INSERT OR REPLACE INTO last_quotes VALUES (?,?,?,?,?,?,?,?)",
                                 (r["instrument"], r["provider"], float(r["price"]), float(r["event_time"]), float(r["receipt_time"]),
                                  r.get("prev_close"), r.get("kind", ""), r.get("provider_symbol", "")))
                n += 1
        return n

    def last_quotes(self, instrument: str | None = None) -> list[dict]:
        q = "SELECT instrument,provider,price,event_time,receipt_time,prev_close,kind,provider_symbol FROM last_quotes"
        rows = self._fetchall(q + (" WHERE instrument=?" if instrument else ""), (instrument,) if instrument else ())
        keys = ("instrument", "provider", "price", "event_time", "receipt_time", "prev_close", "kind", "provider_symbol")
        return [dict(zip(keys, r)) for r in rows]

    def latest_bar(self, instrument: str, intervals: Sequence[str] = ("1m", "5m", "15m", "1h", "1d")) -> FeedBar | None:
        """Most recent bar (confirmed or forming) across providers, ranked by when its last price was known
        (min(bar_end, receipt_time)); the finest interval wins ties."""
        best = None
        for iv in intervals:
            r = self._fetchone(
                "SELECT provider,instrument,interval,event_time,open,high,low,close,volume,receipt_time,confirmed,provider_symbol "
                "FROM bar_revisions WHERE instrument=? AND interval=? ORDER BY event_time DESC, receipt_time DESC LIMIT 1",
                (instrument, iv))
            if r:
                b = FeedBar(r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[0], r[9], bool(r[10]), r[11] or "")
                if best is None or min(b.bar_end, b.receipt_time) > min(best.bar_end, best.receipt_time):
                    best = b
        return best

    def daily_closes(self, instrument: str, limit: int = 3) -> list[tuple[int, float]]:
        rows = self._fetchall(
            "SELECT event_time, close FROM bar_revisions WHERE instrument=? AND interval='1d' "
            "ORDER BY event_time DESC, receipt_time DESC LIMIT ?",
            (instrument, max(limit * 8, 16)),
        )
        out: list[tuple[int, float]] = []
        seen: set[int] = set()
        for t, c in rows:
            ti = int(t)
            if ti not in seen:
                seen.add(ti)
                out.append((ti, float(c)))
                if len(out) >= limit:
                    break
        return out

    def ingest_observations(self, obs: Iterable[FeedObservation]) -> int:
        with self._lock, self._db:
            n0 = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                                 [(o.provider, o.series, o.date, o.realtime_start, o.value, o.receipt_time) for o in obs])
            return self._db.total_changes - n0

    # ---- read ----
    def bars(self, instrument: str, interval: str, start: int | None = None, end: int | None = None,
             provider: str | None = None, as_of: int | None = None, confirmed_only: bool = True) -> list[FeedBar]:
        """Latest version per bar (as known at ``as_of`` if given). If provider is None the best provider per bar is used
        (the one with most rows for this series = primary), never mixing within a single event_time."""
        q = ["instrument=? AND interval=?"]
        a: list = [instrument, interval]
        if provider:
            q.append("provider=?"); a.append(provider)
        if start is not None:
            q.append("event_time>=?"); a.append(int(start))
        if end is not None:
            q.append("event_time<?"); a.append(int(end))
        if as_of is not None:
            q.append("receipt_time<=?"); a.append(int(as_of))
        where = " AND ".join(q)
        rows = self._fetchall(
            f"SELECT provider,instrument,interval,event_time,open,high,low,close,volume,receipt_time,confirmed,provider_symbol "
            f"FROM bar_revisions WHERE {where} ORDER BY event_time ASC, receipt_time ASC", a)
        latest_rev: dict[tuple[str, int], tuple] = {}
        for r in rows:
            latest_rev[(r[0], r[3])] = r
        if len({r[0] for r in latest_rev}) <= 1:
            return [
                FeedBar(r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[0], r[9], bool(r[10]), r[11] or "")
                for r in latest_rev.values()
                if not confirmed_only or r[10]
            ]
        prio = self.provider_rank(instrument, interval) if not provider else [provider]
        best: dict[int, tuple] = {}
        for r in latest_rev.values():
            if confirmed_only and not r[10]:
                continue
            cur = best.get(r[3])
            if cur is None or prio.index(r[0]) < prio.index(cur[0]):
                best[r[3]] = r
        return [FeedBar(r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[0], r[9], bool(r[10]), r[11] or "") for _, r in sorted(best.items())]

    def provider_rank(self, instrument, interval) -> list[str]:
        rows = self._fetchall("SELECT provider, COUNT(*) c FROM bar_revisions WHERE instrument=? AND interval=? GROUP BY provider ORDER BY c DESC",
                                (instrument, interval))
        return [r[0] for r in rows]

    def set_priority(self, instrument, interval, order: Sequence[str]):
        pass  # priority is supplied by AtlasFeed at read time; kept for API symmetry

    def revisions(self, instrument, interval, event_time, provider=None):
        q = "SELECT provider,receipt_time,open,high,low,close,volume,confirmed FROM bar_revisions WHERE instrument=? AND interval=? AND event_time=?"
        a = [instrument, interval, int(event_time)]
        if provider:
            q += " AND provider=?"; a.append(provider)
        return self._fetchall(q + " ORDER BY receipt_time", a)

    def summary(self) -> list[dict]:
        rows = self._fetchall("SELECT provider,instrument,interval,COUNT(DISTINCT event_time),MIN(event_time),MAX(event_time),MAX(receipt_time),"
                                "SUM(confirmed) FROM bar_revisions GROUP BY provider,instrument,interval ORDER BY instrument,interval,provider")
        return [dict(zip(("provider", "instrument", "interval", "bars", "first", "last", "last_receipt", "confirmed_rows"), r)) for r in rows]

    def observations(self, series, as_of_date: str | None = None):
        q, a = "SELECT date,value,realtime_start FROM observations WHERE series=?", [series]
        if as_of_date:
            q += " AND realtime_start<=?"; a.append(as_of_date)
        rows = self._fetchall(q + " ORDER BY date, realtime_start", a)
        latest = {}
        for d, v, rs in rows:
            latest[d] = (v, rs)
        return [(d, v, rs) for d, (v, rs) in sorted(latest.items())]
