"""ATLAS AI node: the single facade every AI/ML/LLM consumer goes through.

One registry, one status vocabulary, one audit trail and ONE place where
``execution_permission == "none"`` is enforced. AI output is advisory only;
the deterministic control plane (``atlas.control``) is the sole authorizer.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Status = Literal["ok", "degraded", "unavailable", "refused"]
EXECUTION_PERMISSION = "none"

# Legacy HTTP namespaces served by the AI node. ``/api/ai/<ns>/...`` aliases
# ``/api/<ns>/...``; both are guarded by the same boundary.
AI_NAMESPACES: tuple[str, ...] = ("ml", "research", "intel", "advanced-ml", "agent", "multi-agent")
# AI endpoints living outside those namespaces: guarded (not aliased).
AI_GUARDED_PREFIXES: tuple[str, ...] = ("/api/ext/dossier", "/api/ext/personas", "/api/ext/pipeline", "/api/pump", "/api/investment-intelligence")


@dataclass(frozen=True)
class AIComponent:
    name: str
    kind: Literal["llm", "ml", "evolution", "selector", "serving", "drift", "retrieval", "intel", "calibration", "rl"]
    modules: tuple[str, ...]
    api: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    ui: tuple[str, ...] = ()
    notes: str = ""


REGISTRY: tuple[AIComponent, ...] = (
    AIComponent("llm_research", "llm", ("atlas.ai.provider", "atlas.ai.gemini_provider", "atlas.ai.policy", "atlas.ai.schemas"),
                scripts=("atlas-research",), notes="LLM output screened by atlas.ai.policy"),
    AIComponent("research_assistant", "retrieval", ("atlas.ai.assistant", "atlas.ai.ml.retrieval", "atlas.ai.intel.assistant"),
                api=("/api/intel", "/api/agent"), ui=("IntelViews",), notes="BM25 retrieval, guarded tools"),
    AIComponent("ml_pipeline", "ml", ("atlas.ai.ml.dataset", "atlas.ai.ml.features", "atlas.ai.ml.cv", "atlas.ai.ml.costs", "atlas.ai.ml.metrics",
                                      "atlas.ai.ml.train", "atlas.ai.ml.registry", "atlas.ai.ml.refresh", "atlas.ai.ml.context", "atlas.ai.ml.vwap_features"),
                api=("/api/ml",), scripts=("scripts/ml_refresh.py", "scripts/ml_diagnose.py", "scripts/ml_model_card.py"), ui=("MlModels",)),
    AIComponent("evolution", "evolution", ("atlas.ai.ml.evolution", "atlas.ai.ml.market_islands", "atlas.ai.ml.niche_archive", "atlas.ai.ml.live_intelligence", "atlas.ai.ml.chart_prediction"),
                notes="islands/niche archive/research hand are research-only; execution_permission=none", scripts=("scripts/evolve_models.py",)),
    AIComponent("selector_regime", "selector", ("atlas.ai.ml.selector", "atlas.ai.models.strategy_classifier", "atlas.ai.models.technique_selector",
                                                "atlas.ai.models.regimes", "atlas.ai.intel.regime", "atlas.regime.hawkes_detector"),
                api=("/api/ml", "/api/research"), scripts=("scripts/run_selector_evidence.py",), ui=("ModelFlowPanel",)),
    AIComponent("serving", "serving", ("atlas.ai.models.serving", "atlas.ai.models.predict", "atlas.ai.models.orchestrator", "atlas.ai.models.bot_orchestrator",
                                       "atlas.ai.models.runtime", "atlas.ai.models.providers", "atlas.ai.models.registry", "atlas.ai.models.model_store"),
                api=("/api/research/live-predict", "/api/advanced-ml"), ui=("LiveModelLockPanel",)),
    AIComponent("challengers", "ml", ("atlas.ai.models.challengers", "atlas.ai.models.transformer_challenger", "atlas.ai.models.transformer_forecaster",
                                      "atlas.ai.models.microstructure_gbdt", "atlas.ai.models.whale_policy", "atlas.ai.models.whale_factor_ml",
                                      "atlas.ai.models.perfect_trader_whale"),
                api=("/api/ml/whale-policy", "/api/ml/perfect-trader"), ui=("WhaleOnChart",)),
    AIComponent("continuous_learning", "ml", ("atlas.ai.models.continuous", "atlas.ai.models.live_training", "atlas.ai.models.live_observer",
                                              "atlas.ai.models.observer_service", "atlas.ai.models.shadow", "atlas.ai.models.self_training", "atlas.ai.models.outcome_ledger"),
                api=("/api/ml/live-train", "/api/ml/live-observer", "/api/research/continuous-tick"), ui=("ObserverHealthPanel",)),
    AIComponent("chart_reader", "ml", ("atlas.ai.models.chart_reader", "atlas.ai.models.chart_policy"), api=("/api/ml/chart-read",), ui=()),
    AIComponent("drift", "drift", ("atlas.ai.ml.drift", "atlas.ai.models.drift_detection"), api=("/ws/drift-alerts",)),
    AIComponent("calibration", "calibration", ("atlas.ai.ml.calibration", "atlas.ai.models.uncertainty_calibration")),
    AIComponent("intel_lab", "intel", ("atlas.ai.intel.lab", "atlas.ai.intel.fourbox", "atlas.ai.intel.markers", "atlas.ai.intel.portfolio",
                                       "atlas.ai.intel.microstructure"), api=("/api/intel",), ui=("IntelViews",)),
    AIComponent("conviction_debate", "intel", ("atlas.ext.dossier", "atlas.ext.personas", "atlas.ext.agents"),
                api=("/api/ext/dossier", "/api/ext/personas", "/api/ext/pipeline"),
                notes="deterministic conviction score, persona scorers, bull/bear debate; risk step is control-plane preview_order"),
    AIComponent("rl_agents", "rl", ("atlas.strategies.rl_agent", "atlas.execution.rl_agent")),
    AIComponent("quant_models", "ml", ("atlas.ai.models.quant.model", "atlas.ai.models.quant.meta", "atlas.ai.models.quant.evaluate",
                                       "atlas.ai.models.quant.sleeves", "atlas.ai.models.quant.retrain", "atlas.ai.models.quant.cv",
                                       "atlas.ai.models.quant.features"),
                scripts=("atlas-ml",), notes="quant retrain/evaluate/sleeves stack"),
    AIComponent("vertical_slice", "ml", ("atlas.research.vertical_slice",), api=("/api/research/vertical-slice",),
                notes="research model selection: frequency baseline, softmax, optional XGBoost"),
    AIComponent("pump_intelligence", "ml", ("atlas.pump", "atlas.pump.features", "atlas.pump.models", "atlas.pump.strategies"),
                api=("/api/pump",), ui=("PumpIntelligenceView",),
                notes="Solana Pump.fun/PumpSwap discovery, safety, EV ranking; execution_permission=none on ML output; paper-only control plane"),
    AIComponent("unified_intelligence_loop", "intel", ("atlas.ai.intel.unified_loop", "atlas.features.price_action.extended_strategies", "atlas.integrations.protocol_manifest"),
                api=("/api/ai/intelligence-loop", "/api/ai/protocol-manifest"), ui=("PumpIntelligenceView", "IntelViews"),
                notes="14-Stage ATLAS Intelligence Loop across multi-asset bars and Solana Pump.fun/PumpSwap tokens; execution_permission=none"),
    AIComponent("daily_investment_brief", "intel", ("atlas.ai.daily_brief", "atlas.investment_intelligence", "atlas.ext.dossier", "atlas.ext.personas", "atlas.ext.agents"),
                api=("/api/ai/daily-brief", "/api/assets/daily-brief", "/api/investment-intelligence"), ui=("Module02ListingsView", "AiDailyInvestmentBriefPanel"),
                notes="AI Daily Investment Intelligence System (10 Vertical Features: Ledger, Yesterday Brief, Today Brief, Market Data, Multifactor Ratings v2.1, ML Forecasting v2.4, TWR/MWR Analytics, 11 Governed MCP Tools, 10-View Workspace, Canadian NI 31-103 Governance); execution_permission=none"),
    AIComponent("multi_agent_research", "intel", ("atlas.multi_agent", "atlas.multi_agent.orchestrator", "atlas.multi_agent.agents",
                                                  "atlas.multi_agent.evidence", "atlas.multi_agent.reflection", "atlas.multi_agent.evolution"),
                api=("/api/multi-agent",), ui=("MultiAgentView",),
                notes="TradingAgents/LangGraph-compatible role graph: parallel analysts, bounded bull/bear debate, research manager, trader candidate, multi-perspective risk, portfolio review; final authority is ActionableControlPlaneEngine.preview_order; execution_permission=none"),
)


def component(name: str) -> AIComponent:
    for c in REGISTRY:
        if c.name == name:
            return c
    raise KeyError(name)


def component_status(c: AIComponent) -> dict[str, Any]:
    missing: list[str] = []
    for m in c.modules:
        try:
            importlib.import_module(m)
        except Exception as exc:  # noqa: BLE001 - status probe
            missing.append(f"{m}: {type(exc).__name__}")
    status: Status = "ok" if not missing else ("unavailable" if len(missing) == len(c.modules) else "degraded")
    from atlas.ai.helpers_registry import helpers_for

    return {**asdict(c), "helpers": helpers_for(c.name), "status": status, "missing": missing,
            "execution_permission": EXECUTION_PERMISSION}


class AdvisoryViolation(RuntimeError):
    """An AI payload tried to carry a non-``none`` execution permission."""


def enforce_advisory(payload: Any, *, source: str = "ai") -> tuple[Any, int]:
    """Force ``execution_permission`` to ``"none"`` everywhere in ``payload``.

    Returns the sanitized payload and the number of overridden fields. This is
    the single boundary; it never grants, only strips.
    """
    count = 0

    def walk(x: Any) -> Any:
        nonlocal count
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k == "execution_permission" and v != EXECUTION_PERMISSION:
                    count += 1
                    out[k] = EXECUTION_PERMISSION
                else:
                    out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    clean = walk(payload)
    if count:
        audit("enforce_advisory", {"source": source, "overridden": count})
    return clean, count


_AUDIT_LOCK = threading.Lock()


def audit_path() -> Path:
    return Path(os.environ.get("ATLAS_AI_AUDIT", "var/ai/audit.jsonl"))


def audit(event: str, detail: dict[str, Any] | None = None) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "detail": detail or {}}
    p = audit_path()
    try:
        with _AUDIT_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass


def read_audit(limit: int = 100) -> list[dict[str, Any]]:
    p = audit_path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(x) for x in lines if x.strip()]


@dataclass
class AINode:
    """Facade: list components, report status, and guard every output."""

    registry: tuple[AIComponent, ...] = field(default=REGISTRY)

    def components(self) -> list[dict[str, Any]]:
        from atlas.ai.helpers_registry import helpers_for

        return [asdict(c) | {"helpers": helpers_for(c.name), "execution_permission": EXECUTION_PERMISSION} for c in self.registry]

    def status(self) -> dict[str, Any]:
        rows = [component_status(c) for c in self.registry]
        worst = "ok" if all(r["status"] == "ok" for r in rows) else "degraded"
        return {"node": "atlas.ai", "status": worst, "execution_permission": EXECUTION_PERMISSION,
                "authorizer": "atlas.control (deterministic control plane)", "components": rows,
                "namespaces": [f"/api/ai/{n}" for n in AI_NAMESPACES]}

    def guard(self, payload: Any, *, source: str = "ai") -> Any:
        return enforce_advisory(payload, source=source)[0]


NODE = AINode()
