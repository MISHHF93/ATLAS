"""Glue for the API: pick an adapter, fetch, add features. Read-only."""
from __future__ import annotations

from typing import Any, Mapping

from atlas.broker_state.adapters import REGISTRY, verification_state
from atlas.broker_state.features import context_text, sizing_feasibility, snapshot_features
from atlas.broker_state.snapshot import unavailable

SIM_EQUITY_BOUNDS = (0.5, 10_000_000.0)


def brokers(env: Mapping[str, str]) -> list[dict[str, Any]]:
    out = [{"broker": "paper_sim", "environment": "simulated", "state": "keyless", "detail": "ATLAS's own paper book; no keys, no network."}]
    for sid, env_name in (("alpaca", "paper"), ("oanda", "practice")):
        st = verification_state(sid, env)
        out.append({"broker": sid, "environment": env_name, "state": st.get("state"), "detail": st.get("detail", "")})
    return out


def get_snapshot(broker: str, env: Mapping[str, str], sim_equity: float | None = None, risk_fraction: float = 0.005,
                 stop_distance_frac: float = 0.02, adapter: Any | None = None) -> dict[str, Any]:
    broker = (broker or "paper_sim").lower()
    if adapter is None:
        if broker not in REGISTRY:
            snap = unavailable(broker, "simulated", "not_configured", f"No adapter for {broker!r} yet (phase 2: IBKR paper, Questrade). Available: {sorted(REGISTRY)}")
            return {"snapshot": snap.to_dict(), "features": snapshot_features(snap), "context": context_text(snap), "sizing": sizing_feasibility(snap),
                    "brokers": brokers(env), "execution_permission": "none"}
        if broker == "paper_sim":
            lo, hi = SIM_EQUITY_BOUNDS
            adapter = REGISTRY[broker](start_equity=min(max(sim_equity, lo), hi) if sim_equity is not None else None)
        else:
            adapter = REGISTRY[broker]()
    snap = adapter.fetch(env)
    return {"snapshot": snap.to_dict(), "features": snapshot_features(snap, risk_fraction, stop_distance_frac), "context": context_text(snap),
            "sizing": sizing_feasibility(snap, risk_fraction, stop_distance_frac), "brokers": brokers(env), "execution_permission": "none"}
