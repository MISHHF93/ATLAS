"""Append-only, hash-chained audit log for multi-agent research runs.

Each run gets its own JSONL file.  Every record contains the hash of the
previous record and a hash over its own canonical content plus that previous
hash.  Rewriting or removing any record breaks verification.

The log stores observable outputs, evidence references, tool results and
decision summaries.  It never stores hidden model reasoning.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_run_id(run_id: str) -> str:
    cleaned = _SAFE.sub("_", run_id)[:160]
    return cleaned or "run"


class AuditLog:
    def __init__(self, directory: str | Path, *, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self._lock = threading.Lock()

    def path_for(self, run_id: str) -> Path:
        return self.directory / f"{safe_run_id(run_id)}.jsonl"

    def _last_hash(self, path: Path) -> str:
        if not path.exists():
            return "GENESIS"
        last = "GENESIS"
        with path.open("rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    last = json.loads(raw.decode("utf-8")).get("hash", last)
                except (ValueError, UnicodeDecodeError):
                    # A corrupt tail is itself evidence; verification reports it.
                    break
        return last

    def append(self, run_id: str, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {}
        body = dict(payload or {})
        body["execution_permission"] = "none"
        ts = datetime.now(timezone.utc)
        with self._lock:
            path = self.path_for(run_id)
            prev = self._last_hash(path)
            seq = self._count(path) + 1
            record = {
                "seq": seq,
                "run_id": run_id,
                "event": event,
                "timestamp": ts.isoformat(),
                "payload": body,
                "prev_hash": prev,
                "execution_permission": "none",
            }
            record["hash"] = digest({**record, "prev_hash": prev})
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(canonical_json(record) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return record

    @staticmethod
    def _count(path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("rb") as fh:
            return sum(1 for line in fh if line.strip())

    def read(self, run_id: str) -> list[dict[str, Any]]:
        path = self.path_for(run_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"event": "corrupt_record", "raw": line[:500]})
        return out

    def verify(self, run_id: str) -> dict[str, Any]:
        rows = self.read(run_id)
        prev = "GENESIS"
        for i, row in enumerate(rows):
            if "hash" not in row:
                return {"valid": False, "records": len(rows), "broken_at": i + 1, "reason": "missing_hash"}
            if row.get("prev_hash") != prev:
                return {"valid": False, "records": len(rows), "broken_at": i + 1, "reason": "prev_hash_mismatch"}
            check = {k: v for k, v in row.items() if k != "hash"}
            if digest(check) != row["hash"]:
                return {"valid": False, "records": len(rows), "broken_at": i + 1, "reason": "hash_mismatch"}
            if row.get("seq") != i + 1:
                return {"valid": False, "records": len(rows), "broken_at": i + 1, "reason": "sequence_mismatch"}
            prev = row["hash"]
        return {"valid": True, "records": len(rows), "head_hash": prev}

    def run_ids(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.jsonl"))


def decision_hash(value: Any) -> str:
    return digest(value)


def envelope(run_id: str, state: Any, *, event: str) -> dict[str, Any]:
    """A stable, observable summary for the audit trail (no hidden reasoning)."""
    return {
        "run_id": run_id,
        "event": event,
        "state_hash": decision_hash(state),
        "execution_permission": "none",
    }
