"""Integration of drift detection with live market data streams.

Connects the drift detection system with ``LiveMarketDataGateway`` to monitor
feature drift from observed ticks. Performance drift is only evaluated when
the caller supplies measured metrics; no metric is fabricated.

All outputs retain ``execution_permission: none``.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from atlas.marketdata.live_stream import LiveMarketDataGateway, LiveTickFrame
from atlas.models.drift_detection import (
    DriftDetectionManager,
    DriftThresholds,
    create_drift_monitor,
    create_performance_monitor,
)


@dataclass(frozen=True)
class DriftIntegrationConfig:
    """Configuration for drift integration with live streams."""

    window_size: int = 1000
    evaluation_interval_seconds: int = 60
    min_samples: int = 100
    enable_auto_retraining: bool = False
    alert_on_drift: bool = True


class LiveDriftMonitor:
    """Real-time drift monitor connected to observed live market data."""

    def __init__(
        self,
        *,
        monitor_id: str,
        config: DriftIntegrationConfig,
        drift_manager: DriftDetectionManager,
    ) -> None:
        self.monitor_id = monitor_id
        self.config = config
        self.drift_manager = drift_manager
        self.feature_windows: dict[str, deque[float]] = {
            "returns": deque(maxlen=config.window_size),
            "volume": deque(maxlen=config.window_size),
            "vpin": deque(maxlen=config.window_size),
            "ofi": deque(maxlen=config.window_size),
        }
        self.last_evaluation_time = datetime.now(timezone.utc)
        self.evaluation_count = 0
        self.trigger_count = 0
        self._last_price: float | None = None
        self._observed_metrics: dict[str, float] = {}

    def process_tick(self, tick: LiveTickFrame) -> None:
        """Update feature windows from a single observed tick."""
        price = float(tick.price)
        if self._last_price is not None and self._last_price > 0:
            self.feature_windows["returns"].append(price / self._last_price - 1.0)
        self._last_price = price
        self.feature_windows["volume"].append(float(tick.size))
        self.feature_windows["vpin"].append(float(tick.vpin))
        self.feature_windows["ofi"].append(float(tick.ofi))

    def record_metrics(self, metrics: dict[str, float]) -> None:
        """Record externally measured model metrics for performance drift checks."""
        self._observed_metrics = {
            name: float(value) for name, value in metrics.items()
        }

    def should_evaluate(self) -> bool:
        elapsed = (
            datetime.now(timezone.utc) - self.last_evaluation_time
        ).total_seconds()
        return elapsed >= self.config.evaluation_interval_seconds

    def evaluate_drift(self) -> dict[str, Any]:
        """Evaluate feature and (when measured) performance drift."""
        current_features = {
            name: np.asarray(list(window), dtype=float)
            for name, window in self.feature_windows.items()
            if len(window) >= self.config.min_samples
            and name in self.drift_manager.drift_monitor.baseline_features
        }
        if not current_features:
            return {
                "status": "insufficient_data",
                "required_samples": self.config.min_samples,
                "execution_permission": "none",
            }

        trigger = self.drift_manager.evaluate_drift(
            current_features=current_features,
            current_metrics=self._observed_metrics,
            model_id=self.monitor_id,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc),
        )
        self.last_evaluation_time = datetime.now(timezone.utc)
        self.evaluation_count += 1
        if trigger.should_retrain:
            self.trigger_count += 1

        return {
            "status": "evaluated",
            "trigger_id": trigger.trigger_id,
            "should_retrain": trigger.should_retrain,
            "priority": trigger.priority,
            "drift_reports": [
                {
                    "feature_name": report.feature_name,
                    "drift_type": report.drift_type,
                    "statistic": report.statistic,
                    "threshold": report.threshold,
                    "is_drift_detected": report.is_drift_detected,
                    "severity": report.severity,
                }
                for report in trigger.drift_reports
            ],
            "performance_reports": [
                {
                    "metric_name": report.metric_name,
                    "baseline_value": report.baseline_value,
                    "current_value": report.current_value,
                    "degradation_pct": report.degradation_pct,
                    "is_drift_detected": report.is_drift_detected,
                    "severity": report.severity,
                }
                for report in trigger.performance_reports
            ],
            "evaluation_count": self.evaluation_count,
            "trigger_count": self.trigger_count,
            "execution_permission": "none",
        }


class DriftStreamIntegration:
    """Manager for integrating drift detection with live market streams."""

    def __init__(
        self,
        gateway: LiveMarketDataGateway,
        config: DriftIntegrationConfig | None = None,
    ) -> None:
        self.gateway = gateway
        self.config = config or DriftIntegrationConfig()
        self.monitors: dict[str, LiveDriftMonitor] = {}
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._listener_added = False

    def create_monitor(
        self,
        monitor_id: str,
        baseline_features: dict[str, np.ndarray],
        baseline_metrics: dict[str, float] | None = None,
    ) -> LiveDriftMonitor:
        """Create a live monitor with an explicit, observed baseline."""
        if not baseline_features:
            raise ValueError("A drift monitor requires at least one baseline feature")
        thresholds = DriftThresholds()
        drift_monitor = create_drift_monitor(
            monitor_id=monitor_id,
            baseline_features=baseline_features,
            baseline_timestamps=[datetime.now(timezone.utc)],
            thresholds=thresholds,
        )
        perf_monitor = create_performance_monitor(
            monitor_id=f"{monitor_id}_perf",
            baseline_metrics=baseline_metrics or {},
            thresholds=thresholds,
        )
        drift_manager = DriftDetectionManager(
            manager_id=f"{monitor_id}_manager",
            drift_monitor=drift_monitor,
            performance_monitor=perf_monitor,
        )
        live_monitor = LiveDriftMonitor(
            monitor_id=monitor_id,
            config=self.config,
            drift_manager=drift_manager,
        )
        self.monitors[monitor_id] = live_monitor
        if not self._listener_added:
            self.gateway.add_listener(self._on_tick)
            self._listener_added = True
        return live_monitor

    def _on_tick(self, tick: LiveTickFrame) -> None:
        for monitor in list(self.monitors.values()):
            monitor.process_tick(tick)

    async def start_evaluation_loop(self) -> None:
        """Start the periodic drift evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())

    async def stop_evaluation_loop(self) -> None:
        """Stop the periodic drift evaluation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _evaluation_loop(self) -> None:
        while self._running:
            for monitor in list(self.monitors.values()):
                if monitor.should_evaluate():
                    monitor.evaluate_drift()
            await asyncio.sleep(self.config.evaluation_interval_seconds)

    def get_monitor_status(self, monitor_id: str) -> dict[str, Any]:
        monitor = self.monitors.get(monitor_id)
        if monitor is None:
            return {"error": "Monitor not found"}
        return {
            "monitor_id": monitor_id,
            "window_sizes": {
                name: len(window)
                for name, window in monitor.feature_windows.items()
            },
            "last_evaluation": monitor.last_evaluation_time.isoformat(),
            "evaluation_count": monitor.evaluation_count,
            "trigger_count": monitor.trigger_count,
            "execution_permission": "none",
        }

    def list_monitors(self) -> list[str]:
        return list(self.monitors.keys())


def create_drift_integration(
    gateway: LiveMarketDataGateway,
    config: DriftIntegrationConfig | None = None,
) -> DriftStreamIntegration:
    return DriftStreamIntegration(gateway=gateway, config=config)
