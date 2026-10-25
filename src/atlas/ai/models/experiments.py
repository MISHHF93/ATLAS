"""Append-only local experiment records, using the Python standard library."""
import hashlib
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path

from atlas.schemas import TrainingJob, TrainingRequest


class ExperimentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, request_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS job_events (sequence INTEGER PRIMARY KEY, experiment_id TEXT NOT NULL, job_json TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, request: TrainingRequest) -> str:
        canonical = json.dumps(request.dataset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        with self._connect() as connection:
            connection.execute("INSERT INTO experiments VALUES (?, ?, ?)", (request.experiment_id, fingerprint, request.model_dump_json()))
        return fingerprint

    def record_job(self, job: TrainingJob) -> None:
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM experiments WHERE id=?", (job.experiment_id,)).fetchone() is None:
                raise ValueError("Unknown experiment")
            connection.execute("INSERT INTO job_events (experiment_id, job_json) VALUES (?, ?)", (job.experiment_id, job.model_dump_json()))

    def get(self, experiment_id: str) -> TrainingRequest:
        with self._connect() as connection:
            row = connection.execute("SELECT request_json FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return TrainingRequest.model_validate_json(row[0])

    def history(self, experiment_id: str) -> tuple[TrainingJob, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT job_json FROM job_events WHERE experiment_id=? ORDER BY sequence", (experiment_id,)).fetchall()
        return tuple(TrainingJob.model_validate_json(row[0]) for row in rows)
