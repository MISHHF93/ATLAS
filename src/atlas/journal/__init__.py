"""Subsystem J: Journaling & Immutable Audit Trails (`src/atlas/journal/`).

Re-exports the SQLite immutable model/approval registry and SHA-256 hash-chained
audit event verification (`execution_permission = "none"`).
"""
from __future__ import annotations

import hashlib
from typing import Literal

from atlas.models.model_store import SQLiteModelRegistry
from atlas.models.schemas import Record, Text


class AuditJournalEntry(Record):
    """Tamper-evident SHA-256 hash-chained audit journal entry."""

    sequence_id: int
    event_type: Text
    payload: Text
    prev_sha256: Text
    entry_sha256: Text
    execution_permission: Literal["none"] = "none"


def append_chained_audit_entry(
    sequence_id: int,
    event_type: str,
    payload: str,
    *,
    prev_sha256: str = "0" * 64,
) -> AuditJournalEntry:
    """Create a SHA-256 hash-chained audit entry linking to `prev_sha256`."""
    digest = hashlib.sha256(f"{sequence_id}|{event_type}|{payload}|{prev_sha256}".encode("utf-8")).hexdigest()
    return AuditJournalEntry(
        sequence_id=sequence_id,
        event_type=event_type,
        payload=payload,
        prev_sha256=prev_sha256,
        entry_sha256=digest,
    )


__all__ = ["AuditJournalEntry", "SQLiteModelRegistry", "append_chained_audit_entry"]

