"""Own SQLite database (never shared with the trading bot)."""
from __future__ import annotations
import sqlite3, time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, actor TEXT, action TEXT, data TEXT, prev TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS accounts(code TEXT PRIMARY KEY, kind TEXT, currency TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, ts REAL, memo TEXT, ref TEXT, fx_rate TEXT);
CREATE TABLE IF NOT EXISTS postings(id INTEGER PRIMARY KEY, journal_id INTEGER, account TEXT, currency TEXT, amount TEXT, amount_cad TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS payees(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, rail TEXT, currency TEXT, destination TEXT,
  status TEXT, requested_at REAL, approved_at REAL, active_from REAL);
CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY, idem_key TEXT UNIQUE, payee_id INTEGER, amount TEXT, currency TEXT,
  amount_cad TEXT, rail TEXT, source TEXT, purpose TEXT, status TEXT, created_at REAL, executed_at REAL, provider_ref TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY, subject TEXT, subject_id INTEGER, approver TEXT, ts REAL,
  UNIQUE(subject, subject_id, approver));
CREATE TABLE IF NOT EXISTS investors(id INTEGER PRIMARY KEY, name TEXT, accredited INTEGER, kyc_status TEXT, units TEXT,
  hwm TEXT, committed TEXT, called TEXT);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, investor_id INTEGER, kind TEXT, amount TEXT, units TEXT, status TEXT,
  created_at REAL, nav TEXT, dealt_at REAL);
CREATE TABLE IF NOT EXISTS compliance_flags(id INTEGER PRIMARY KEY, investor_id INTEGER, kind TEXT, detail TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS capital_calls(id INTEGER PRIMARY KEY, investor_id INTEGER, amount TEXT, due TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS fees(id INTEGER PRIMARY KEY, investor_id INTEGER, kind TEXT, period TEXT, amount TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS vendors(id INTEGER PRIMARY KEY, name TEXT UNIQUE, category TEXT, currency TEXT);
CREATE TABLE IF NOT EXISTS budgets(category TEXT, month TEXT, amount_cad TEXT, PRIMARY KEY(category, month));
CREATE TABLE IF NOT EXISTS bills(id INTEGER PRIMARY KEY, vendor_id INTEGER, amount TEXT, currency TEXT, amount_cad TEXT,
  month TEXT, status TEXT, invoice_path TEXT, invoice_sha256 TEXT, recurring_id INTEGER);
CREATE TABLE IF NOT EXISTS recurring(id INTEGER PRIMARY KEY, vendor_id INTEGER, amount TEXT, currency TEXT, every_months INTEGER,
  next_month TEXT, active INTEGER);
CREATE TABLE IF NOT EXISTS manual_instructions(transfer_id INTEGER PRIMARY KEY, reference TEXT UNIQUE, value_date TEXT,
  created_at REAL, expires_at REAL, batch TEXT, confirmation TEXT, marked_by TEXT, marked_at REAL, settled_at REAL,
  statement_ref TEXT, flag TEXT);
"""

def connect(path: str = ":memory:") -> sqlite3.Connection:
    c = sqlite3.connect(path, isolation_level=None)
    if path != ":memory:":
        import os
        try:
            os.chmod(path, 0o600)  # treasury DB: owner-only
        except OSError:
            pass
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c

@contextmanager
def tx(c: sqlite3.Connection):
    """Re-entrant write transaction. BEGIN IMMEDIATE takes the write lock up front, so a status check
    followed by an update is atomic even when two CLI processes act on the same DB."""
    if c.in_transaction:
        yield
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        yield
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise

def now() -> float:
    return time.time()
