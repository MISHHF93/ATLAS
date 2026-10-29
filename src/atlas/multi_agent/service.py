"""Service facade used by HTTP and scripts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .agents import LLMCallable, analyst_specs
from .audit import AuditLog
from .config import MultiAgentConfig
from .contracts import EvolutionReport, ReflectionRecord, ResearchRunState, RunRequest, RunSummary
from .evolution import build_evolution
from .evidence import EvidenceDependencies
from .llm import build_llm
from .orchestrator import ResearchOrchestrator
from .reflection import build_reflection
from .store import ResearchStore


class MultiAgentService:
    def __init__(
        self,
        config: MultiAgentConfig | None = None,
        *,
        dependencies: EvidenceDependencies | None = None,
        llm: LLMCallable | None = None,
        control_engine: object | None = None,
        clock=None,
    ) -> None:
        self.config = config or MultiAgentConfig.from_env()
        self.config.ensure_dirs()
        if llm is None:
            llm = build_llm(self.config)
        self.store = ResearchStore(self.config.db_path)
        self.audit = AuditLog(self.config.audit_dir)
        self.orchestrator = ResearchOrchestrator(
            self.config,
            store=self.store,
            audit=self.audit,
            dependencies=dependencies,
            llm=llm,
            control_engine=control_engine,
            clock=clock,
        )

    def start(self, request: RunRequest, *, force: bool = False) -> ResearchRunState:
        return self.orchestrator.start(request, force=force)

    def get(self, run_id: str) -> ResearchRunState | None:
        return self.store.load_run(run_id)

    def resume(self, run_id: str) -> ResearchRunState | None:
        return self.orchestrator.resume(run_id)

    def cancel(self, run_id: str) -> bool:
        return self.orchestrator.cancel(run_id)

    def list_runs(self, *, limit: int = 50, status: str | None = None) -> list[RunSummary]:
        return self.store.list_runs(limit=limit, status=status)

    def audit_log(self, run_id: str) -> list[dict]:
        return self.audit.read(run_id)

    def audit_verify(self, run_id: str) -> dict:
        return self.audit.verify(run_id)

    def agents(self) -> list[dict]:
        return [spec.model_dump(mode="json") for spec in analyst_specs(self.orchestrator.llm, self.config.prompt_version)]

    def status(self) -> dict:
        return {
            "status": "ok",
            "store": self.store.stats(),
            "config": self.config.as_dict(),
            "llm_provider_injected": self.orchestrator.llm is not None,
            "llm_enabled": self.config.enable_llm,
            "dependencies_injected": self.orchestrator.dependencies is not None,
            "database": str(self.config.db_path),
            "audit_dir": str(self.config.audit_dir),
            "execution_permission": "none",
            "authority": "atlas.control.ActionableControlPlaneEngine.preview_order",
            "note": "Research runs are advisory; no order submission endpoint exists here.",
        }

    def reflect(
        self,
        run_id: str,
        *,
        outcome_price: float,
        outcome_as_of: datetime | None = None,
        benchmark_return: float | None = None,
    ) -> ReflectionRecord:
        state = self.store.load_run(run_id)
        if state is None:
            raise KeyError(run_id)
        record = build_reflection(
            state,
            outcome_price=outcome_price,
            outcome_as_of=outcome_as_of,
            benchmark_return=benchmark_return,
        )
        self.store.save_reflection(record)
        self._append_reflection_jsonl(record)
        self.audit.append(run_id, "reflection_created", {
            "reflection_id": record.reflection_id,
            "predicted_direction": record.predicted_direction,
            "directional_correct": record.directional_correct,
            "abstention_quality": record.abstention_quality,
            "original_decision_hash": record.original_decision_hash,
            "execution_permission": "none",
        })
        return record

    def reflections(self, *, run_id: str | None = None, limit: int = 100) -> list[ReflectionRecord]:
        return self.store.list_reflections(run_id=run_id, limit=limit)

    def evolution(self) -> EvolutionReport:
        return build_evolution(self.store)

    def _append_reflection_jsonl(self, record: ReflectionRecord) -> None:
        path: Path = self.config.reflections_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(record.model_dump_json() + "\n")


__all__ = ["MultiAgentService"]
