"""Durable local model metadata, research-alias rollback, scoped approvals, and calibrators.

This stores metadata only, does not load untrusted weights, and never deploys.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from atlas.ai.models.evaluation import ProbabilityCalibrator
from atlas.schemas import Capability, Eligibility, ModelRecord, ModelRef, ProviderInfo


class SQLiteModelRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS models (provider TEXT, model TEXT, revision TEXT, record TEXT NOT NULL, PRIMARY KEY(provider, model, revision))")
            connection.execute("CREATE TABLE IF NOT EXISTS research_aliases (alias TEXT PRIMARY KEY, current TEXT NOT NULL, history TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS alias_events (sequence INTEGER PRIMARY KEY, alias TEXT NOT NULL, action TEXT NOT NULL, model_ref TEXT NOT NULL, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS scoped_approvals ("
                "approval_key TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS approval_events ("
                "sequence INTEGER PRIMARY KEY, approval_key TEXT NOT NULL, action TEXT NOT NULL, approver TEXT NOT NULL, record TEXT NOT NULL, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS calibrators ("
                "calibration_id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, record TEXT NOT NULL)"
            )

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

    @staticmethod
    def _approval_key(approval: Eligibility) -> str:
        return "|".join((
            *approval.model.key,
            approval.instrument_id,
            approval.horizon_id,
            approval.target,
            approval.unit,
            approval.strategy_family,
        ))

    def register_approval(self, approval: Eligibility) -> str:
        """Persist a human-reviewed scoped research approval with append-only audit trail."""
        self.get(approval.model)
        key = self._approval_key(approval)
        payload = approval.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO scoped_approvals VALUES (?, ?) "
                "ON CONFLICT(approval_key) DO UPDATE SET record=excluded.record",
                (key, payload),
            )
            connection.execute(
                "INSERT INTO approval_events (approval_key, action, approver, record) VALUES (?, ?, ?, ?)",
                (key, "approve" if approval.research_approved else "deny", approval.approver, payload),
            )
        return key

    def revoke_approval(self, approval_key: str, *, reviewer: str) -> Eligibility:
        if not reviewer.strip():
            raise ValueError("Reviewer identity is required for revocation")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record FROM scoped_approvals WHERE approval_key=?", (approval_key,)
            ).fetchone()
            if row is None:
                raise KeyError(approval_key)
            current = Eligibility.model_validate_json(row[0])
            revoked = current.model_copy(update={"research_approved": False, "approver": reviewer})
            payload = revoked.model_dump_json()
            connection.execute(
                "UPDATE scoped_approvals SET record=? WHERE approval_key=?", (payload, approval_key)
            )
            connection.execute(
                "INSERT INTO approval_events (approval_key, action, approver, record) VALUES (?, ?, ?, ?)",
                (approval_key, "revoke", reviewer, payload),
            )
        return revoked

    def list_approvals(self) -> tuple[Eligibility, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record FROM scoped_approvals ORDER BY approval_key"
            ).fetchall()
        return tuple(Eligibility.model_validate_json(row[0]) for row in rows)

    def approval_history(self, approval_key: str) -> tuple[tuple[str, str, Eligibility], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT action, approver, record FROM approval_events WHERE approval_key=? ORDER BY sequence",
                (approval_key,),
            ).fetchall()
        return tuple((action, approver, Eligibility.model_validate_json(rec)) for action, approver, rec in rows)

    def register_calibrator(self, provider_id: str, model_id: str, calibrator: ProbabilityCalibrator) -> str:
        scope_key = "|".join((
            provider_id,
            model_id,
            calibrator.model_revision,
            calibrator.instrument_id,
            calibrator.horizon_id,
            calibrator.target,
            calibrator.unit,
        ))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO calibrators VALUES (?, ?, ?)",
                (calibrator.calibration_id, scope_key, calibrator.model_dump_json()),
            )
        return scope_key

    def list_calibrators(self) -> dict[tuple[str, ...], ProbabilityCalibrator]:
        with self._connect() as connection:
            rows = connection.execute("SELECT scope_key, record FROM calibrators").fetchall()
        return {
            tuple(scope_key.split("|")): ProbabilityCalibrator.model_validate_json(rec)
            for scope_key, rec in rows
        }
