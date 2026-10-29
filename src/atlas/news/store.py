"""SQLite store for news items (public, shared), annotations (per scope), reviews (per scope) and watchlists (per scope).

Scope is ``owner`` (no identity / owner) or ``user:<id>``: the same rule ``integrations.verify`` uses. Items are public source records and
are shared; annotations and reviews are produced with a scope's own key, so they are stored per scope and never shown to another user."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT NOT NULL, ticker TEXT NOT NULL, source TEXT NOT NULL, tier INTEGER NOT NULL, kind TEXT NOT NULL,
  published_at REAL NOT NULL, first_seen_at REAL NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
  form TEXT, codes TEXT, tone REAL, domain TEXT, content_hash TEXT NOT NULL,
  PRIMARY KEY(id, ticker));
CREATE INDEX IF NOT EXISTS items_t ON items(ticker, published_at);
CREATE TABLE IF NOT EXISTS coverage(ticker TEXT NOT NULL, source TEXT NOT NULL, start_ts REAL NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY(ticker, source));
CREATE TABLE IF NOT EXISTS annotations(
  item_id TEXT NOT NULL, ticker TEXT NOT NULL, scope TEXT NOT NULL, analyzer TEXT NOT NULL, model TEXT, prompt_hash TEXT,
  analyzed_at REAL NOT NULL, event_type TEXT, sentiment REAL, materiality REAL, grounded INTEGER NOT NULL DEFAULT 0,
  hype_flags TEXT NOT NULL DEFAULT '[]', rationale TEXT, evidence_quote TEXT,
  PRIMARY KEY(item_id, ticker, scope, analyzer));
CREATE TABLE IF NOT EXISTS reviews(
  review_id TEXT PRIMARY KEY, ts REAL NOT NULL, scope TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
  symbol TEXT NOT NULL, interval TEXT, side TEXT NOT NULL, marker_id TEXT, probability REAL,
  verdict TEXT NOT NULL, confidence_multiplier REAL, applied INTEGER NOT NULL DEFAULT 0, reason TEXT,
  recommendation TEXT, citations TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]',
  prompt_hash TEXT, model TEXT, provider TEXT, raw_output TEXT, proposal TEXT NOT NULL,
  outcome TEXT, outcome_r REAL, outcome_ts REAL);
CREATE INDEX IF NOT EXISTS reviews_s ON reviews(scope, ts);
CREATE INDEX IF NOT EXISTS reviews_m ON reviews(marker_id);
CREATE TABLE IF NOT EXISTS watchlist(scope TEXT NOT NULL, ticker TEXT NOT NULL, PRIMARY KEY(scope, ticker));
"""


def db_path() -> Path:
    return Path(os.environ.get("ATLAS_NEWS_DB", "var/news/news.db"))


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        c = sqlite3.connect(str(p), timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.executescript(SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()


def current_scope() -> str:
    from atlas.integrations.verify import _scope   # the same owner / user:<id> rule integration verification uses
    return _scope()


def item_id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16]


def content_hash(title: str, url: str) -> str:
    return hashlib.sha256(f"{title}\n{url}".encode()).hexdigest()[:16]


def upsert_items(rows: Iterable[dict[str, Any]], now: float) -> int:
    """Insert new items. ``first_seen_at`` is never rewritten, and neither is ``published_at`` (point-in-time)."""
    n = 0
    with conn() as c:
        for r in rows:
            cur = c.execute(
                "INSERT OR IGNORE INTO items(id,ticker,source,tier,kind,published_at,first_seen_at,url,title,form,codes,tone,domain,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["ticker"], r["source"], r["tier"], r["kind"], float(r["published_at"]), now, r["url"], r["title"], r.get("form"), r.get("codes"),
                 r.get("tone"), r.get("domain"), r["content_hash"]))
            n += cur.rowcount
    return n


def set_coverage(ticker: str, source: str, start_ts: float, now: float) -> None:
    with conn() as c:
        c.execute("INSERT INTO coverage(ticker,source,start_ts,fetched_at) VALUES(?,?,?,?) ON CONFLICT(ticker,source) DO UPDATE SET "
                  "start_ts=CASE WHEN excluded.start_ts > fetched_at THEN excluded.start_ts ELSE MIN(start_ts, excluded.start_ts) END, fetched_at=excluded.fetched_at", (ticker, source, start_ts, now))


def coverage_start(ticker: str, source_prefix: str) -> float | None:
    with conn() as c:
        r = c.execute("SELECT MIN(start_ts) m FROM coverage WHERE ticker=? AND source LIKE ?", (ticker, source_prefix + "%")).fetchone()
    return None if r is None or r["m"] is None else float(r["m"])


def items_for(tickers: Iterable[str], since: float | None = None, until: float | None = None, limit: int = 200) -> list[dict[str, Any]]:
    ts = list(dict.fromkeys(tickers))
    if not ts:
        return []
    q = "SELECT * FROM items WHERE ticker IN (%s)" % ",".join("?" * len(ts))
    a: list[Any] = list(ts)
    if since is not None:
        q += " AND published_at>=?"; a.append(since)
    if until is not None:
        q += " AND published_at<=?"; a.append(until)
    q += " ORDER BY published_at DESC LIMIT ?"; a.append(int(limit))
    with conn() as c:
        return [dict(r) for r in c.execute(q, a)]


def save_annotation(a: dict[str, Any]) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO annotations(item_id,ticker,scope,analyzer,model,prompt_hash,analyzed_at,event_type,sentiment,materiality,grounded,hype_flags,rationale,evidence_quote) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (a["item_id"], a["ticker"], a["scope"], a["analyzer"], a.get("model"), a.get("prompt_hash"), a["analyzed_at"], a.get("event_type"), a.get("sentiment"),
                   a.get("materiality"), 1 if a.get("grounded") else 0, json.dumps(a.get("hype_flags") or []), a.get("rationale"), a.get("evidence_quote")))


def annotations_for(item_keys: Iterable[tuple[str, str]], scope: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    keys = list(item_keys)
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if not keys:
        return out
    with conn() as c:
        ids = list({k[0] for k in keys})
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            for r in c.execute("SELECT * FROM annotations WHERE scope=? AND item_id IN (%s)" % ",".join("?" * len(chunk)), [scope, *chunk]):
                d = dict(r)
                d["hype_flags"] = json.loads(d["hype_flags"] or "[]")
                d["grounded"] = bool(d["grounded"])
                out.setdefault((d["item_id"], d["ticker"]), []).append(d)
    return out


def get_watchlist(scope: str) -> list[str]:
    with conn() as c:
        return [r["ticker"] for r in c.execute("SELECT ticker FROM watchlist WHERE scope=? ORDER BY ticker", (scope,))]


def set_watchlist(scope: str, tickers: Iterable[str]) -> list[str]:
    ts = sorted(set(tickers))
    with conn() as c:
        c.execute("DELETE FROM watchlist WHERE scope=?", (scope,))
        c.executemany("INSERT INTO watchlist(scope,ticker) VALUES(?,?)", [(scope, t) for t in ts])
    return ts


def counts() -> dict[str, int]:
    with conn() as c:
        return {t: int(c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]) for t in ("items", "annotations", "reviews")}
