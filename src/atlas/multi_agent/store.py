"""SQLite persistence for multi-agent research runs.

The store is deliberately boring: durable state, checkpoints, cancellation
flags and reflections.  It uses WAL mode and a fresh connection per operation
so the research path can be called from FastAPI's thread pool safely.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .contracts import ReflectionRecord, ResearchRunState, RunSummary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL,
    current_node TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_json TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    recommendation TEXT,
    deterministic_outcome TEXT,
    data_snapshot_id TEXT,
    original_decision_hash TEXT,
    outcome_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_updated ON runs(updated_at DESC);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    node TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS controls (
    run_id TEXT PRIMARY KEY,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reflections (
    reflection_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reflections_run ON reflections(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_run(self, state: ResearchRunState) -> None:
        payload = state.model_dump(mode="json")
        rec = state.research_decision.outcome if state.research_decision else None
        det = state.deterministic_decision.outcome if state.deterministic_decision else None
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, instrument_id, timeframe, as_of, status, current_node,
                                  created_at, updated_at, state_json, config_json, recommendation,
                                  deterministic_outcome, data_snapshot_id, original_decision_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    instrument_id=excluded.instrument_id,
                    timeframe=excluded.timeframe,
                    as_of=excluded.as_of,
                    status=excluded.status,
                    current_node=excluded.current_node,
                    updated_at=excluded.updated_at,
                    state_json=excluded.state_json,
                    config_json=excluded.config_json,
                    recommendation=excluded.recommendation,
                    deterministic_outcome=excluded.deterministic_outcome,
                    data_snapshot_id=excluded.data_snapshot_id,
                    original_decision_hash=COALESCE(runs.original_decision_hash, excluded.original_decision_hash)
                """,
                (
                    state.run_id,
                    state.instrument_id,
                    state.timeframe,
                    state.as_of.isoformat(),
                    state.status,
                    state.current_node,
                    state.created_at.isoformat(),
                    state.updated_at.isoformat(),
                    json.dumps(payload, default=str),
                    json.dumps(state.config, default=str),
                    rec,
                    det,
                    state.data_snapshot_id,
                    state.original_decision_hash,
                ),
            )

    def load_run(self, run_id: str) -> ResearchRunState | None:
        with self._conn() as conn:
            row = conn.execute("SELECT state_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        return ResearchRunState.model_validate(json.loads(row[0]))

    def run_exists(self, run_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is not None

    def list_runs(self, *, limit: int = 50, status: str | None = None) -> list[RunSummary]:
        sql = "SELECT run_id, instrument_id, timeframe, as_of, status, current_node, created_at, updated_at, recommendation, deterministic_outcome, data_snapshot_id, state_json FROM runs"
        args: list[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        out: list[RunSummary] = []
        for r in rows:
            try:
                state = json.loads(r[11])
                count = len(state.get("analyst_reports") or [])
            except ValueError:
                count = 0
            out.append(
                RunSummary(
                    run_id=r[0],
                    instrument_id=r[1],
                    timeframe=r[2],
                    as_of=r[3],
                    status=r[4],
                    current_node=r[5],
                    created_at=r[6],
                    updated_at=r[7],
                    recommendation=r[8],
                    deterministic_outcome=r[9],
                    data_snapshot_id=r[10],
                    analyst_count=count,
                )
            )
        return out

    def append_checkpoint(self, run_id: str, node: str, state: ResearchRunState) -> int:
        payload = json.dumps(state.model_dump(mode="json"), default=str)
        with self._conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(seq),0) FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
            seq = int(row[0]) + 1
            conn.execute(
                "INSERT INTO checkpoints (run_id, seq, node, state_json, created_at) VALUES (?,?,?,?,?)",
                (run_id, seq, node, payload, _now()),
            )
        return seq

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT seq, node, state_json, created_at FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {"seq": row[0], "node": row[1], "state": ResearchRunState.model_validate(json.loads(row[2])), "created_at": row[3]}

    def checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT seq, node, created_at FROM checkpoints WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()
        return [{"seq": r[0], "node": r[1], "created_at": r[2]} for r in rows]

    def request_cancel(self, run_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO controls (run_id, cancel_requested, updated_at) VALUES (?,1,?) "
                "ON CONFLICT(run_id) DO UPDATE SET cancel_requested=1, updated_at=excluded.updated_at",
                (run_id, _now()),
            )

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT cancel_requested FROM controls WHERE run_id=?", (run_id,)).fetchone()
        return bool(row and row[0])

    def clear_cancel(self, run_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO controls (run_id, cancel_requested, updated_at) VALUES (?,0,?) "
                "ON CONFLICT(run_id) DO UPDATE SET cancel_requested=0, updated_at=excluded.updated_at",
                (run_id, _now()),
            )

    def save_reflection(self, record: ReflectionRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reflections (reflection_id, run_id, instrument_id, created_at, payload_json) "
                "VALUES (?,?,?,?,?)",
                (
                    record.reflection_id,
                    record.run_id,
                    record.instrument_id,
                    record.created_at.isoformat(),
                    json.dumps(record.model_dump(mode="json"), default=str),
                ),
            )

    def list_reflections(self, *, run_id: str | None = None, limit: int = 100) -> list[ReflectionRecord]:
        sql = "SELECT payload_json FROM reflections"
        args: list[Any] = []
        if run_id:
            sql += " WHERE run_id=?"
            args.append(run_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [ReflectionRecord.model_validate(json.loads(r[0])) for r in rows]

    def reflection_for_run(self, run_id: str) -> ReflectionRecord | None:
        rows = self.list_reflections(run_id=run_id, limit=1)
        return rows[0] if rows else None

    def count_runs(self, status: str | None = None) -> int:
        with self._conn() as conn:
            if status:
                row = conn.execute("SELECT COUNT(*) FROM runs WHERE status=?", (status,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
        return int(row[0]) if row else 0

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM runs WHERE status='completed'").fetchone()[0]
            reflections = conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
            checkpoints = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        return {
            "runs": int(total),
            "completed_runs": int(completed),
            "reflections": int(reflections),
            "checkpoints": int(checkpoints),
            "execution_permission": "none",
        }
