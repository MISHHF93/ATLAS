"""LangGraph-compatible research orchestrator.

ATLAS does not depend on ``langgraph`` at runtime.  The orchestration below is
the compatible mechanism: a typed graph state, explicit nodes, conditional
bounded debate, checks at every edge and a persistent checkpoint after every
node.  A run can be resumed from the last successful checkpoint.

The graph is intentionally linear apart from the debate's conditional stop.
Every node is deterministic unless an optional LLM synthesis provider is
injected.  No node can submit an order.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .agents import LLMCallable, analyze_parallel
from .audit import AuditLog, decision_hash, envelope
from .config import MultiAgentConfig
from .contracts import (
    DeterministicDecision,
    NodeEvent,
    ResearchRunState,
    RunRequest,
    RunSummary,
)
from .debate import run_debate
from .deterministic import gate
from .evidence import EvidenceDependencies, build_evidence_snapshot
from .portfolio import review as portfolio_review
from .reconciliation import reconcile
from .research import decide
from .risk import review as risk_review
from .store import ResearchStore
from .trader import propose

NODE_ORDER: tuple[str, ...] = (
    "validate",
    "snapshot",
    "analysts",
    "reconcile",
    "debate",
    "research_decision",
    "trader",
    "risk_reviews",
    "portfolio_review",
    "deterministic",
    "complete",
)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ResearchOrchestrator:
    def __init__(
        self,
        config: MultiAgentConfig,
        *,
        store: ResearchStore | None = None,
        audit: AuditLog | None = None,
        dependencies: EvidenceDependencies | None = None,
        llm: LLMCallable | None = None,
        control_engine: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.store = store or ResearchStore(config.db_path)
        self.audit = audit or AuditLog(config.audit_dir)
        self.dependencies = dependencies
        self.llm = llm
        self.control_engine = control_engine
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ public
    def start(self, request: RunRequest, *, force: bool = False) -> ResearchRunState:
        now = _utc(self.clock())
        as_of = _utc(request.as_of) if request.as_of else now
        request = request.model_copy(update={"as_of": as_of, "timeframe": request.timeframe})
        run_id = request.run_id or f"ma-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        if self.store.run_exists(run_id) and not force:
            existing = self.store.load_run(run_id)
            if existing and existing.status == "completed":
                return existing
            raise ValueError(f"run_id_already_exists:{run_id}")
        state = ResearchRunState(
            run_id=run_id,
            instrument_id=request.instrument_id.upper(),
            timeframe=request.timeframe,
            as_of=as_of,
            created_at=now,
            updated_at=now,
            status="pending",
            config={**self.config.as_dict(), "request": request.model_dump(mode="json")},
            portfolio=request.portfolio,
            data_snapshot_id=None,
        )
        self.store.save_run(state)
        self.audit.append(run_id, "run_created", {
            "instrument_id": state.instrument_id,
            "timeframe": state.timeframe,
            "as_of": state.as_of.isoformat(),
            "requested_llm": request.enable_llm,
            "execution_permission": "none",
        })
        return self._execute(state, start_index=0, resumed=False)

    def resume(self, run_id: str) -> ResearchRunState | None:
        state = self.store.load_run(run_id)
        if state is None:
            return None
        if state.status == "completed":
            return state
        self.store.clear_cancel(run_id)
        state.status = "resumed"
        state.updated_at = _utc(self.clock())
        self.store.save_run(state)
        self.audit.append(run_id, "run_resumed", {"from_node": state.current_node})
        succeeded = {e.node for e in state.node_history if e.status == "succeeded"}
        start = next((i for i, name in enumerate(NODE_ORDER) if name not in succeeded), len(NODE_ORDER) - 1)
        return self._execute(state, start_index=start, resumed=True)

    def cancel(self, run_id: str) -> bool:
        if not self.store.run_exists(run_id):
            return False
        self.store.request_cancel(run_id)
        self.audit.append(run_id, "cancel_requested", {"execution_permission": "none"})
        return True

    def audit_log(self, run_id: str) -> list[dict[str, Any]]:
        return self.audit.read(run_id)

    def audit_verify(self, run_id: str) -> dict[str, Any]:
        return self.audit.verify(run_id)

    def list_runs(self, *, limit: int = 50, status: str | None = None) -> list[RunSummary]:
        return self.store.list_runs(limit=limit, status=status)

    # ------------------------------------------------------------------- nodes
    def _request(self, state: ResearchRunState) -> RunRequest:
        payload = state.config.get("request")
        if not payload:
            return RunRequest(instrument_id=state.instrument_id, timeframe=state.timeframe, as_of=state.as_of)
        return RunRequest.model_validate(payload)

    def _execute(self, state: ResearchRunState, *, start_index: int, resumed: bool) -> ResearchRunState:
        state.status = "running"
        state.updated_at = _utc(self.clock())
        self.store.save_run(state)
        self.audit.append(state.run_id, "run_started", {
            "start_index": start_index,
            "resumed": resumed,
            "execution_permission": "none",
        })

        for name in NODE_ORDER[start_index:]:
            if self.store.is_cancel_requested(state.run_id):
                state.status = "cancelled"
                state.current_node = name
                state.updated_at = _utc(self.clock())
                self.store.save_run(state)
                self.audit.append(state.run_id, "run_cancelled", {"before_node": name})
                return state
            node = getattr(self, f"_node_{name}")
            started = _utc(self.clock())
            perf = time.perf_counter()
            attempt = 0
            while True:
                try:
                    state.current_node = name
                    node(state)
                    break
                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    if attempt > self.config.max_retries:
                        finished = _utc(self.clock())
                        state.node_history.append(NodeEvent(
                            node=name,
                            status="failed",
                            started_at=started,
                            finished_at=finished,
                            duration_ms=int((time.perf_counter() - perf) * 1000),
                            state_hash=decision_hash(state.model_dump(mode="json")),
                            error=f"{type(exc).__name__}: {exc}"[:800],
                        ))
                        state.errors.append(f"{name}: {type(exc).__name__}: {exc}"[:800])
                        state.status = "failed"
                        state.updated_at = finished
                        self.store.save_run(state)
                        self.store.append_checkpoint(state.run_id, f"{name}:failed", state)
                        self.audit.append(state.run_id, "node_failed", {
                            "node": name, "error": f"{type(exc).__name__}: {exc}"[:800],
                        })
                        return state
                    time.sleep(0)
            finished = _utc(self.clock())
            event = NodeEvent(
                node=name,
                status="succeeded",
                started_at=started,
                finished_at=finished,
                duration_ms=int((time.perf_counter() - perf) * 1000),
                state_hash=decision_hash(state.model_dump(mode="json")),
                detail={"attempts": attempt + 1},
            )
            state.node_history.append(event)
            state.updated_at = finished
            state.status = "completed" if name == "complete" else "running"
            self.store.save_run(state)
            self.store.append_checkpoint(state.run_id, name, state)
            self.audit.append(state.run_id, "node_succeeded", {
                "node": name,
                "duration_ms": event.duration_ms,
                "state_hash": event.state_hash,
                "execution_permission": "none",
            })
            if name == "complete":
                break
        return state

    def _node_validate(self, state: ResearchRunState) -> None:
        request = self._request(state)
        if not request.instrument_id.strip():
            raise ValueError("instrument_id_required")
        now = _utc(self.clock())
        if state.as_of > now:
            raise ValueError("as_of_is_in_the_future")
        if request.timeframe not in {"1m", "5m", "15m", "1h", "1d"}:
            raise ValueError("unsupported_timeframe")
        if request.portfolio is not None and request.portfolio.cash < 0:
            raise ValueError("portfolio_cash_cannot_be_negative")
        state.config["validated_as_of"] = state.as_of.isoformat()

    def _node_snapshot(self, state: ResearchRunState) -> None:
        request = self._request(state)
        snapshot = build_evidence_snapshot(
            request, self.config, dependencies=self.dependencies, portfolio=state.portfolio
        )
        state.snapshot = snapshot
        state.data_snapshot_id = snapshot.snapshot_id
        state.config["data_snapshot_id"] = snapshot.snapshot_id
        self.audit.append(state.run_id, "evidence_snapshot", {
            "snapshot_id": snapshot.snapshot_id,
            "instrument_id": snapshot.instrument_id,
            "bars_count": snapshot.bars_count,
            "bars_hash": snapshot.bars_hash,
            "last_bar_at": snapshot.last_bar_at.isoformat() if snapshot.last_bar_at else None,
            "missing_data": snapshot.missing_data,
            "prompt_injection_flags": snapshot.prompt_injection_flags,
            "execution_permission": "none",
        })

    def _node_analysts(self, state: ResearchRunState) -> None:
        if state.snapshot is None:
            raise RuntimeError("snapshot_missing")
        request = self._request(state)
        use_llm = bool(self.llm) and (request.enable_llm or self.config.enable_llm)
        reports, errors = analyze_parallel(
            state.snapshot, state.run_id, self.config,
            llm=self.llm if use_llm else None,
            cancel_check=lambda: self.store.is_cancel_requested(state.run_id),
        )
        state.analyst_reports = reports
        state.errors.extend(errors)
        if request.enable_llm and self.llm is None:
            state.errors.append("llm_enabled_but_no_provider_injected")
        state.agent_versions = {r.analyst_type: r.agent_version for r in reports}
        state.prompt_template_versions = {r.analyst_type: r.prompt_template_version for r in reports}
        self.audit.append(state.run_id, "analyst_reports", {
            "reports": [
                {
                    "analyst_type": r.analyst_type,
                    "status": r.status,
                    "stance": r.stance,
                    "confidence": r.confidence_label,
                    "thesis_hash": decision_hash(r.thesis),
                    "supporting": [e.source_id for e in r.supporting_evidence],
                    "contradicting": [e.source_id for e in r.contradicting_evidence],
                    "missing_data": r.missing_data,
                }
                for r in reports
            ],
            "errors": errors,
            "execution_permission": "none",
        })

    def _node_reconcile(self, state: ResearchRunState) -> None:
        if state.snapshot is None:
            raise RuntimeError("snapshot_missing")
        state.reconciliation = reconcile(state.analyst_reports, state.snapshot)
        self.audit.append(state.run_id, "reconciliation", {
            "report": state.reconciliation.model_dump(mode="json"),
        })

    def _node_debate(self, state: ResearchRunState) -> None:
        if state.snapshot is None or state.reconciliation is None:
            raise RuntimeError("reconciliation_missing")
        request = self._request(state)
        rounds = request.debate_rounds if request.debate_rounds is not None else self.config.debate_rounds
        state.debate = run_debate(
            state.analyst_reports, state.reconciliation, state.snapshot, rounds_max=rounds
        )
        self.audit.append(state.run_id, "debate", {
            "rounds_completed": state.debate.rounds_completed,
            "rounds_max": state.debate.rounds_max,
            "bull_score": state.debate.bull_score,
            "bear_score": state.debate.bear_score,
            "net_score": state.debate.net_score,
            "stopped_reason": state.debate.stopped_reason,
            "unresolved": state.debate.unresolved,
            "execution_permission": "none",
        })

    def _node_research_decision(self, state: ResearchRunState) -> None:
        if state.snapshot is None or state.reconciliation is None or state.debate is None:
            raise RuntimeError("debate_missing")
        state.research_decision = decide(
            state.analyst_reports, state.reconciliation, state.debate, state.snapshot,
            directional_threshold=self.config.directional_threshold,
        )
        self.audit.append(state.run_id, "research_decision", {
            "decision": state.research_decision.model_dump(mode="json"),
        })

    def _node_trader(self, state: ResearchRunState) -> None:
        if state.snapshot is None or state.research_decision is None:
            raise RuntimeError("research_decision_missing")
        request = self._request(state)
        state.trade_proposal = propose(
            state.research_decision, state.snapshot,
            run_id=state.run_id,
            notional_usd=float(request.notional_usd or self.config.default_notional_usd),
            strategy_id=request.strategy_id,
        )
        self.audit.append(state.run_id, "trade_proposal", {
            "proposal": state.trade_proposal.model_dump(mode="json"),
        })

    def _node_risk_reviews(self, state: ResearchRunState) -> None:
        if state.snapshot is None or state.research_decision is None or state.reconciliation is None or state.trade_proposal is None:
            raise RuntimeError("proposal_missing")
        state.risk_reviews = risk_review(
            state.trade_proposal, state.research_decision,
            state.reconciliation, state.snapshot, state.portfolio,
        )
        self.audit.append(state.run_id, "risk_reviews", {
            "reviews": [r.model_dump(mode="json") for r in state.risk_reviews],
        })

    def _node_portfolio_review(self, state: ResearchRunState) -> None:
        if state.trade_proposal is None:
            raise RuntimeError("proposal_missing")
        state.portfolio_review = portfolio_review(
            state.trade_proposal, state.portfolio, risk_reviews=state.risk_reviews
        )
        self.audit.append(state.run_id, "portfolio_review", {
            "review": state.portfolio_review.model_dump(mode="json"),
        })

    def _node_deterministic(self, state: ResearchRunState) -> None:
        if state.trade_proposal is None or state.research_decision is None or state.portfolio_review is None:
            raise RuntimeError("portfolio_review_missing")
        request = self._request(state)
        age_ms = 0.0
        if state.snapshot is not None:
            age_ms = max(0.0, (state.as_of - state.snapshot.retrieved_at).total_seconds() * 1000.0)
        state.deterministic_decision = gate(
            state.trade_proposal, state.research_decision, state.portfolio_review,
            track=request.track, evaluation_time=state.as_of,
            control_engine=self.control_engine, data_age_ms=age_ms,
        )
        self.audit.append(state.run_id, "deterministic_decision", {
            "decision": state.deterministic_decision.model_dump(mode="json"),
            "authority": "atlas.control.ActionableControlPlaneEngine.preview_order",
        })

    def _node_complete(self, state: ResearchRunState) -> None:
        state.original_decision_hash = decision_hash({
            "snapshot_id": state.data_snapshot_id,
            "research": state.research_decision.model_dump(mode="json") if state.research_decision else None,
            "proposal": state.trade_proposal.model_dump(mode="json") if state.trade_proposal else None,
            "portfolio": state.portfolio_review.model_dump(mode="json") if state.portfolio_review else None,
            "deterministic": state.deterministic_decision.model_dump(mode="json") if state.deterministic_decision else None,
        })
        state.status = "completed"
        state.current_node = "complete"
        state.updated_at = _utc(self.clock())
        self.audit.append(state.run_id, "run_completed", {
            **envelope(state.run_id, state.model_dump(mode="json"), event="run_completed"),
            "recommendation": state.research_decision.outcome if state.research_decision else None,
            "proposal_action": state.trade_proposal.action if state.trade_proposal else None,
            "deterministic_outcome": state.deterministic_decision.outcome if state.deterministic_decision else None,
            "original_decision_hash": state.original_decision_hash,
        })


__all__ = ["ResearchOrchestrator", "NODE_ORDER"]
