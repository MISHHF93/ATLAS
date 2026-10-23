"""SHA-256 hash chain used by both append-only audit logs (each keeps its own row format)."""
from __future__ import annotations

import hashlib

GENESIS = "0" * 64


def link(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode()).hexdigest()
