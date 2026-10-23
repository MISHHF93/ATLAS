"""Integration of advanced ML components with the deterministic control plane.

The enhanced engine is a thin coordinator. It may scale a proposed notional or
add an intake violation, but it never bypasses
:class:`ActionableControlPlaneEngine`. If uncertainty gating rejects a proposal,
the base engine receives the rejection as an intake violation and therefore
does not open a position.

All outputs retain ``execution_permission: none``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import AwareDatetime

from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableOrderDecision,
    ActionableOrderRequest,
)
from atlas.control.uncertainty_gating import (
    UncertaintyAwareGating,
    UncertaintyGateDecision,
    UncertaintyGatingConfig,
    create_uncertainty_gating,
)
from atlas.models.drift_detection import (
    DriftDetectionManager,
    DriftMonitor,
    PerformanceMonitor,
    create_drift_monitor,
    create_performance_monitor,
)
from atlas.models.schemas import Record, Text
from atlas.models.transformer_forecaster import FittedTransformerModel
from atlas.models.uncertainty_calibration import UncertaintyAwareCalibration


class EnhancedControlPlaneEngine:
    """ML-aware coordinator around the deterministic control plane."""

    def __init__(
        self,
        *,
        engine_id: str,
        base_engine: ActionableControlPlaneEngine,
        uncertainty_gating: UncertaintyAwareGating,
        drift_manager: DriftDetectionManager,
        calibration: UncertaintyAwareCalibration | None = None,
        active_model: FittedTransformerModel | None = None,
    ) -> None:
        self.engine_id = engine_id
        self.base_engine = base_engine
        self.uncertainty_gating = uncertainty_gating
        self.drift_manager = drift_manager
        self.calibration = calibration
        self.active_model = active_model

    def evaluate_order_with_uncertainty(
        self,
        request: ActionableOrderRequest,
        prediction: float,
        lower: float | None = None,
        upper: float | None = None,
        confidence: float = 0.5,
        *,
        current_price: float | None = None,
        model_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[ActionableOrderDecision, UncertaintyGateDecision]:
        """Gate and, only if authorized, submit an order.

        The uncertainty gate runs before the base control plane. Rejected
        proposals are passed as intake violations, which guarantees that the
        base engine records a rejection rather than executing and then
        pretending it did not.
        """
        price = current_price if current_price is not None else prediction
        if price <= 0:
            raise ValueError("current_price must be positive")

        gate = self.uncertainty_gating.evaluate_trade(
            model_id=(
                model_id
                or (self.active_model.model_id if self.active_model else "unknown")
            ),
            instrument_id=request.instrument_id,
            prediction=prediction,
            lower=lower,
            upper=upper,
            confidence=confidence,
            current_price=price,
            proposed_position=float(request.notional_usd),
        )

        if not gate.trade_allowed:
            violations = (
                "uncertainty_gating: "
                + (gate.rejection_reason or "trade not allowed"),
            )
            decision = self.base_engine.submit_order(
                request,
                now=now,
                intake_violations=violations,
            )
            return decision, gate

        scaled_notional = (
            request.notional_usd * Decimal(str(gate.position_scale))
        ).quantize(Decimal("0.01"))
        if scaled_notional <= 0:
            decision = self.base_engine.submit_order(
                request,
                now=now,
                intake_violations=("uncertainty_gating: zero sized position",),
            )
            return decision, gate

        scaled_request = request.model_copy(
            update={"notional_usd": scaled_notional}
        )
        decision = self.base_engine.submit_order(scaled_request, now=now)
        return decision, gate

    def check_drift_and_trigger_retraining(
        self,
        current_features: dict[str, np.ndarray],
        current_metrics: dict[str, float],
    ) -> bool:
        """Evaluate drift and report whether a retraining review is needed."""
        if not self.active_model:
            return False
        if not self.drift_manager.drift_monitor.baseline_features:
            return False

        trigger = self.drift_manager.evaluate_drift(
            current_features=current_features,
            current_metrics=current_metrics,
            model_id=self.active_model.model_id,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc),
        )
        return trigger.should_trigger_retraining()

    def update_baseline_for_drift(
        self,
        new_features: dict[str, np.ndarray],
        new_metrics: dict[str, float],
        new_timestamps: list[datetime],
    ) -> None:
        """Replace the drift baselines with a new observed period."""
        if not new_features:
            raise ValueError("new_features must not be empty")
        if not new_timestamps:
            raise ValueError("new_timestamps must not be empty")
        if len(new_timestamps) != 1 and len(new_timestamps) != max(
            len(values) for values in new_features.values()
        ):
            raise ValueError(
                "new_timestamps must contain one timestamp or one per observation"
            )

        self.drift_manager.drift_monitor = DriftMonitor(
            monitor_id=self.drift_manager.drift_monitor.monitor_id,
            thresholds=self.drift_manager.drift_monitor.thresholds,
            baseline_features=new_features,
            baseline_timestamps=tuple(new_timestamps),
        )
        self.drift_manager.performance_monitor = PerformanceMonitor(
            monitor_id=self.drift_manager.performance_monitor.monitor_id,
            thresholds=self.drift_manager.performance_monitor.thresholds,
            baseline_metrics=new_metrics,
        )

    def set_active_model(
        self,
        model: FittedTransformerModel,
        calibration: UncertaintyAwareCalibration | None = None,
    ) -> None:
        self.active_model = model
        self.calibration = calibration

    def calibrate_forecast(
        self,
        probability_up: float | None,
        lower: float | None,
        upper: float | None,
        prediction: float,
    ) -> tuple[float | None, float | None, float | None]:
        """Apply the registered calibrator, if one exists."""
        if self.calibration is None:
            return probability_up, lower, upper
        return self.calibration.calibrate_forecast(
            probability_up, lower, upper, prediction
        )


def create_enhanced_control_plane(
    engine_id: str,
    base_engine: ActionableControlPlaneEngine,
    uncertainty_config: UncertaintyGatingConfig | None = None,
) -> EnhancedControlPlaneEngine:
    """Create an enhanced coordinator with a deterministic base engine."""
    uncertainty_gating = create_uncertainty_gating(
        gate_id=f"{engine_id}_uncertainty",
        config=uncertainty_config,
    )
    drift_monitor = create_drift_monitor(
        monitor_id=f"{engine_id}_drift",
        baseline_features={},
        baseline_timestamps=[],
    )
    performance_monitor = create_performance_monitor(
        monitor_id=f"{engine_id}_perf",
        baseline_metrics={},
    )
    drift_manager = DriftDetectionManager(
        manager_id=f"{engine_id}_drift_manager",
        drift_monitor=drift_monitor,
        performance_monitor=performance_monitor,
    )
    return EnhancedControlPlaneEngine(
        engine_id=engine_id,
        base_engine=base_engine,
        uncertainty_gating=uncertainty_gating,
        drift_manager=drift_manager,
    )


class MLModelIntegrationRecord(Record):
    """Record of ML model integration with the control plane."""

    integration_id: Text
    model_id: Text
    integrated_at: AwareDatetime
    calibration_id: Text | None
    drift_monitor_id: Text
    uncertainty_gate_id: Text
    execution_permission: Literal["none"] = "none"


def register_model_integration(
    engine: EnhancedControlPlaneEngine,
    model: FittedTransformerModel,
    calibration: UncertaintyAwareCalibration | None = None,
) -> MLModelIntegrationRecord:
    """Register a model with an enhanced control-plane coordinator."""
    engine.set_active_model(model, calibration)
    return MLModelIntegrationRecord(
        integration_id=(
            f"integration_{model.model_id}_"
            f"{datetime.now(timezone.utc).isoformat()}"
        ),
        model_id=model.model_id,
        integrated_at=datetime.now(timezone.utc),
        calibration_id=calibration.calibration_id if calibration else None,
        drift_monitor_id=engine.drift_manager.manager_id,
        uncertainty_gate_id=engine.uncertainty_gating.gate_id,
    )
