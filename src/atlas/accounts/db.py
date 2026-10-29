"""SQLite access for accounts (WAL, foreign keys on, one connection per call, migrations applied on first use)."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .migrations import MIGRATIONS

_LOCK = threading.Lock()
_MIGRATED: set[str] = set()


def db_path() -> str:
    p = os.environ.get("ATLAS_ACCOUNTS_DB")
    if p:
        return p
    if "PYTEST_CURRENT_TEST" in os.environ:  # never touch the real store from a test that forgot to set the path
        import tempfile
        return str(Path(tempfile.gettempdir()) / f"atlas_accounts_pytest_{os.getpid()}.sqlite")
    return "var/accounts/atlas_accounts.sqlite"


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at BIGINT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[int] = []
    import time
    for version, name, sql in MIGRATIONS:
        if version in done:
            continue
        try:
            conn.executescript("BEGIN;\n" + sql + f"\nINSERT INTO schema_migrations VALUES ({int(version)}, '{name}', {int(time.time())});\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _open(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    path = path or db_path()
    conn = _open(path)
    try:
        if path not in _MIGRATED:
            with _LOCK:
                if path not in _MIGRATED:
                    migrate(conn)
                    from .billing import seed_plans
                    seed_plans(conn)
                    _MIGRATED.add(path)
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Write transaction (BEGIN IMMEDIATE so concurrent writers queue instead of deadlocking)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def reset_for_tests() -> None:
    _MIGRATED.clear()
