"""Subsystem T: Telemetry, Observability & Pipeline Heartbeats (`src/atlas/telemetry/`).

Provides tick-to-trade latency evaluation, pipeline heartbeat checks, and stale-drop alerts
(`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record, Text


class TelemetryHeartbeatReport(Record):
    """Pipeline latency and heartbeat health report."""

    pipeline_id: Text
    tick_to_signal_ms: FiniteFloat = Field(ge=0)
    heartbeat_age_sec: FiniteFloat = Field(ge=0)
    drop_alert_active: bool
    health_status: Literal["healthy", "degraded", "halted_stale"]
    execution_permission: Literal["none"] = "none"


def evaluate_pipeline_telemetry(
    pipeline_id: str,
    *,
    tick_to_signal_ms: float = 1.4,
    heartbeat_age_sec: float = 2.0,
    max_heartbeat_age_sec: float = 30.0,
) -> TelemetryHeartbeatReport:
    """Evaluate pipeline tick-to-signal latency and heartbeat freshness."""
    drop = heartbeat_age_sec > max_heartbeat_age_sec
    status: Literal["healthy", "degraded", "halted_stale"] = (
        "halted_stale" if drop else ("degraded" if tick_to_signal_ms > 25.0 else "healthy")
    )
    return TelemetryHeartbeatReport(
        pipeline_id=pipeline_id,
        tick_to_signal_ms=round(float(tick_to_signal_ms), 4),
        heartbeat_age_sec=round(float(heartbeat_age_sec), 4),
        drop_alert_active=drop,
        health_status=status,
    )


__all__ = ["TelemetryHeartbeatReport", "evaluate_pipeline_telemetry"]

