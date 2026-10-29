"""Postgres migration path for the accounts schema.

The runtime store is still SQLite (``db.py``). This module makes the SCHEMA portable so a Postgres move is a data-access swap, not a
redesign: every migration is plain portable DDL except the ``payouts_ledger`` immutability triggers (M0005), which are SQLite
syntax. ``migrations_for("postgresql")`` replaces them with an equivalent plpgsql guard generated from the same column list.

* ``LEDGER_IMMUTABLE_COLUMNS`` is the single source of truth: every ledger column except ``flooos_batch``. A test fails if a new
  ledger column is added without being listed, so the guard can never silently stop covering a column.
* The Postgres guard also blocks ``TRUNCATE`` (SQLite has no such statement).
* ``apply_postgres`` applies the migrations through psycopg (imported lazily; psycopg is not a runtime dependency yet).
"""
from __future__ import annotations

import os
import time
from typing import Any

from .migrations import M0005_BILLING_V2_BASE, MIGRATIONS

LEDGER_IMMUTABLE_COLUMNS: tuple[str, ...] = (
    "id", "seq", "ts", "kind", "direction", "amount_cents", "currency", "fx_rate_micros", "counterparty", "stripe_payout_id",
    "invoice_id", "broker_referral_id", "tax_record_id", "bank_ref", "dedupe_key", "memo", "prev_hash", "hash",
)
LEDGER_APPEND_ONLY_MSG = "payouts_ledger is append-only"
LEDGER_UPDATE_MSG = "payouts_ledger is append-only (only flooos_batch may be set, once)"


def postgres_ledger_triggers() -> str:
    cols_new = ", ".join(f"NEW.{c}" for c in LEDGER_IMMUTABLE_COLUMNS)
    cols_old = ", ".join(f"OLD.{c}" for c in LEDGER_IMMUTABLE_COLUMNS)
    return f"""CREATE FUNCTION payouts_ledger_guard() RETURNS trigger AS $atlas$
BEGIN
  IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION '{LEDGER_APPEND_ONLY_MSG}' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF OLD.flooos_batch IS NOT NULL OR ROW({cols_new}) IS DISTINCT FROM ROW({cols_old}) THEN
    RAISE EXCEPTION '{LEDGER_UPDATE_MSG}' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END;
$atlas$ LANGUAGE plpgsql;
CREATE TRIGGER payouts_ledger_no_update BEFORE UPDATE OR DELETE ON payouts_ledger
  FOR EACH ROW EXECUTE FUNCTION payouts_ledger_guard();
CREATE TRIGGER payouts_ledger_no_truncate BEFORE TRUNCATE ON payouts_ledger
  FOR EACH STATEMENT EXECUTE FUNCTION payouts_ledger_guard();
"""


def migrations_for(dialect: str = "sqlite") -> tuple[tuple[int, str, str], ...]:
    """The ordered migrations rendered for ``sqlite`` (exactly the shipped text) or ``postgresql``."""
    d = dialect.lower()
    if d in ("sqlite", "sqlite3"):
        return MIGRATIONS
    if d in ("postgresql", "postgres", "pg"):
        return tuple((v, n, (M0005_BILLING_V2_BASE + postgres_ledger_triggers()) if v == 5 else sql) for v, n, sql in MIGRATIONS)
    raise ValueError(f"unknown dialect {dialect!r}")


def render_schema(dialect: str = "postgresql") -> str:
    return "\n".join(f"-- migration {v}: {n}\n{sql.strip()}\n" for v, n, sql in migrations_for(dialect))


def apply_postgres(conn: Any, now: float | None = None) -> list[int]:
    """Apply pending migrations on a psycopg 3 connection (one transaction each, serialised with an advisory lock). Returns versions applied."""
    now = int(time.time() if now is None else now)
    applied: list[int] = []
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at BIGINT NOT NULL)")
    conn.commit()
    for version, name, sql in migrations_for("postgresql"):
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(7413001)")
            if conn.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (version,)).fetchone():
                continue
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s)", (version, name, now))
            applied.append(version)
    return applied


def database_url(env: dict[str, str] | None = None) -> str:
    return (env if env is not None else os.environ).get("ATLAS_DATABASE_URL", "").strip()
