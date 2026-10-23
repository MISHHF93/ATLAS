"""SQLite-backed persistent key/value state (kill switch, session anchors,
heartbeats). Shared between the core process and the watchdog process."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Callable


def restrict_sqlite_files(path: str) -> None:
    """chmod 0600 the DB and its WAL/SHM side files (they hold the same data and follow the umask)."""
    for p in (path, path + "-wal", path + "-shm", path + "-journal"):
        try:
            if os.path.exists(p):
                os.chmod(p, 0o600)
        except OSError:
            pass


class StateStore:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
        if path != ":memory:":
            try:  # least privilege: approvals / kill switch state readable by the owner account only
                os.chmod(path, 0o600)
            except OSError:
                pass
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        if path != ":memory:":
            restrict_sqlite_files(path)
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:  # one sqlite connection is shared by threads: serialise every use
            row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def update(self, key: str, fn: Callable[[Any], Any], default: Any = None) -> Any:
        """Atomic read-modify-write across threads AND processes (BEGIN IMMEDIATE takes the SQLite
        write lock before the read). `fn(old)` returns the new value; returning the old value
        unchanged still commits nothing harmful. Exceptions roll back and propagate."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
                new = fn(json.loads(row[0]) if row else default)
                self._db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                 (key, json.dumps(new, default=str)))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return new

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (key, json.dumps(value, default=str)))

    def items(self, prefix: str) -> dict[str, Any]:
        with self._lock:
            rows = self._db.execute("SELECT k, v FROM kv WHERE k LIKE ? ESCAPE '\\' ORDER BY k",
                                    (prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
            if row:
                self._db.execute("DELETE FROM kv WHERE k=?", (key,))
        return json.loads(row[0]) if row else default

    def delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE k=?", (key,))
