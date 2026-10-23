"""Routes risk-approved intents to a paper adapter. The RiskEngine is evaluated
HERE, so an adapter can't be reached without a fresh approval."""
from __future__ import annotations

from typing import Any

from atlas.governance.audit import AuditLog
from atlas.risk.engine import RiskEngine
from atlas.risk.models import OrderIntent, PortfolioState


class ExecutionRouter:
    def __init__(self, engine: RiskEngine, adapters: dict[str, Any], audit: AuditLog, fallback: Any | None = None):
        self.engine, self.adapters, self.audit, self.fallback = engine, adapters, audit, fallback
        for a in list(adapters.values()) + ([fallback] if fallback else []):
            engine.ks.add_on_engage(a.cancel_all)
            if hasattr(a, "flatten_all"):
                engine.ks.add_on_flatten(a.flatten_all)

    def adapter_for(self, broker: str):
        a = self.adapters.get(broker)
        if a is not None and getattr(a, "enabled", True):
            return a
        return self.fallback  # internal simulator when the real paper adapter is off

    def execute(self, intent: OrderIntent, state: PortfolioState) -> dict:
        d = self.engine.evaluate(intent, state)
        out = d.model_dump() | {"executes": False}
        if not d.approved:
            return out
        a = self.adapter_for(intent.broker)
        if a is None:
            self.audit.append("route.no_adapter", {"broker": intent.broker})
            return out | {"reasons": [f"no adapter for {intent.broker}"]}
        try:
            oid = a.submit(intent, d)
        except Exception as e:
            self.engine.anomaly.on_broker_reject(self.engine._clock())
            self.audit.append("route.broker_error", {"broker": intent.broker, "error": repr(e)})
            return out | {"reasons": [f"broker error: {e!r}"]}
        self.audit.append("route.submitted", {"broker": getattr(a, "name", "paper_sim"), "order_id": oid})
        return out | {"executes": True, "order_id": oid, "venue": getattr(a, "name", "paper_sim")}
