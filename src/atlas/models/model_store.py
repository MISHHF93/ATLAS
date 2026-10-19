"""Durable local model metadata and research-alias rollback.

This stores metadata only, does not load untrusted weights, and never deploys.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from atlas.models.schemas import Capability, ModelRecord, ModelRef, ProviderInfo


class SQLiteModelRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS models (provider TEXT, model TEXT, revision TEXT, record TEXT NOT NULL, PRIMARY KEY(provider, model, revision))")
            connection.execute("CREATE TABLE IF NOT EXISTS research_aliases (alias TEXT PRIMARY KEY, current TEXT NOT NULL, history TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS alias_events (sequence INTEGER PRIMARY KEY, alias TEXT NOT NULL, action TEXT NOT NULL, model_ref TEXT NOT NULL, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def describe(self) -> ProviderInfo:
        return ProviderInfo(provider_id="sqlite-registry", capabilities={Capability.REGISTRY}, location="local")

    def register(self, record: ModelRecord) -> None:
        try:
            with self._connect() as connection:
                connection.execute("INSERT INTO models VALUES (?, ?, ?, ?)", (*record.model.key, record.model_dump_json()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("Model revision is immutable") from exc

    def get(self, model: ModelRef) -> ModelRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT record FROM models WHERE provider=? AND model=? AND revision=?", model.key).fetchone()
        if row is None:
            raise KeyError(model.key)
        return ModelRecord.model_validate_json(row[0])

    def list_models(self) -> tuple[ModelRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT record FROM models ORDER BY provider, model, revision").fetchall()
        return tuple(ModelRecord.model_validate_json(row[0]) for row in rows)

    def set_research_alias(self, alias: str, model: ModelRef) -> None:
        if not alias.strip():
            raise ValueError("Alias is empty")
        self.get(model)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT current, history FROM research_aliases WHERE alias=?", (alias,)).fetchone()
            history = json.loads(row[1]) + [json.loads(row[0])] if row else []
            connection.execute("INSERT INTO research_aliases VALUES (?, ?, ?) ON CONFLICT(alias) DO UPDATE SET current=excluded.current, history=excluded.history",
                (alias, model.model_dump_json(), json.dumps(history)))
            connection.execute("INSERT INTO alias_events (alias, action, model_ref) VALUES (?, ?, ?)", (alias, "set", model.model_dump_json()))

    def resolve(self, alias: str) -> ModelRef:
        with self._connect() as connection:
            row = connection.execute("SELECT current FROM research_aliases WHERE alias=?", (alias,)).fetchone()
        if row is None:
            raise KeyError(alias)
        return ModelRef.model_validate_json(row[0])

    def rollback_research_alias(self, alias: str) -> ModelRef:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT history FROM research_aliases WHERE alias=?", (alias,)).fetchone()
            history = json.loads(row[0]) if row else []
            if not history:
                raise ValueError("No previous research revision")
            model = ModelRef.model_validate(history.pop())
            connection.execute("UPDATE research_aliases SET current=?, history=? WHERE alias=?", (model.model_dump_json(), json.dumps(history), alias))
            connection.execute("INSERT INTO alias_events (alias, action, model_ref) VALUES (?, ?, ?)", (alias, "rollback", model.model_dump_json()))
        return model

    def alias_history(self, alias: str) -> tuple[tuple[str, ModelRef], ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT action, model_ref FROM alias_events WHERE alias=? ORDER BY sequence", (alias,)).fetchall()
        return tuple((action, ModelRef.model_validate_json(model)) for action, model in rows)
