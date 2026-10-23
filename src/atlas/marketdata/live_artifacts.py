"""Durable, inspectable artifacts for received public-feed data and research."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


class LiveArtifactStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS artifacts(kind TEXT, symbol TEXT, key TEXT, received_at TEXT, sha256 TEXT, payload TEXT, PRIMARY KEY(kind,symbol,key))")
            conn.execute("CREATE TABLE IF NOT EXISTS checkpoints(symbol TEXT PRIMARY KEY, payload TEXT)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def record(self, rows: list[tuple[str, str, str, dict[str, Any]]]) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        values = []
        for kind, symbol, key, payload in rows:
            data = json.dumps(payload, sort_keys=True, allow_nan=False)
            values.append((kind, symbol, key, stamp, hashlib.sha256(data.encode()).hexdigest(), data))
        with self.lock, self.connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?,?)", values)

    def checkpoint(self, symbol: str, state: dict[str, Any]) -> None:
        with self.lock, self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?)", (symbol, json.dumps(state, allow_nan=False)))

    def commit_observation(self, symbol: str, state: dict[str, Any], rows: list[tuple[str, str, str, dict[str, Any]]]) -> None:
        """Commit prediction evidence and the matching learned state atomically."""
        stamp = datetime.now(timezone.utc).isoformat()
        values = []
        for kind, row_symbol, key, payload in rows:
            data = json.dumps(payload, sort_keys=True, allow_nan=False)
            values.append((kind, row_symbol, key, stamp, hashlib.sha256(data.encode()).hexdigest(), data))
        checkpoint = json.dumps(state, allow_nan=False)
        with self.lock, self.connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?,?)", values)
            conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?)", (symbol, checkpoint))

    def restore(self, symbol: str) -> dict[str, Any] | None:
        with self.lock, self.connect() as conn:
            row = conn.execute("SELECT payload FROM checkpoints WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row[0]) if row else None

    def recent_bars(self, symbol: str) -> list[dict[str, Any]]:
        with self.lock, self.connect() as conn:
            rows = conn.execute("SELECT payload FROM artifacts WHERE kind='bar' AND symbol=? ORDER BY key DESC LIMIT 90", (symbol,)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def manifest(self) -> dict[str, Any]:
        with self.lock, self.connect() as conn:
            counts = dict(conn.execute("SELECT kind,COUNT(*) FROM artifacts GROUP BY kind"))
            bounds = conn.execute("SELECT MIN(received_at),MAX(received_at) FROM artifacts").fetchone()
            checkpoints = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        return {"counts": counts, "checkpoints": checkpoints, "first_received_at": bounds[0],
                "last_received_at": bounds[1], "storage": str(self.path), "execution_permission": "none",
                "coverage": "Received subscribed trade/heartbeat events, derived bars, prediction inputs, outcomes and observer checkpoints. Not every market or order-book event. Gap events identify known discontinuities."}

    def export(self) -> bytes:
        with self.lock, self.connect() as source:
            with tempfile.TemporaryDirectory(prefix="atlas-capture-export-") as directory:
                target = Path(directory) / "capture.sqlite"
                copy = sqlite3.connect(target)
                try:
                    source.backup(copy)
                    copy.execute("PRAGMA journal_mode=DELETE")
                finally:
                    copy.close()
                data = target.read_bytes()
            manifest = self.manifest()
        manifest["database_sha256"] = hashlib.sha256(data).hexdigest()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("live_capture.sqlite", data)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        return output.getvalue()


_STORES: dict[str, LiveArtifactStore] = {}
_LOCK = threading.Lock()


def artifact_store() -> LiveArtifactStore | None:
    configured = os.environ.get("ATLAS_LIVE_ARTIFACT_DB")
    if os.environ.get("PYTEST_CURRENT_TEST") and not configured:
        return None
    path = Path(configured) if configured else Path(__file__).resolve().parents[3] / ".atlas" / "live_capture.sqlite"
    with _LOCK:
        return _STORES.setdefault(str(path), LiveArtifactStore(path)) if str(path) not in _STORES else _STORES[str(path)]
