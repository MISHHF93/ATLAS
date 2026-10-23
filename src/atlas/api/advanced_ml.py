"""Advanced ML API endpoints for sequence forecasting, drift, and features.

Endpoints only return research outputs with ``execution_permission: "none"``.
Forecasts require a model trained by this process; the API never substitutes a
mock prediction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import numpy as np
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from atlas.api.rbac import verify_role_action
from atlas.control.uncertainty_gating import (
    create_uncertainty_gating,
)
from atlas.features.feature_store import (
    FeatureLineage,
    FeatureMetadata,
    create_feature_store,
)
from atlas.models.drift_detection import (
    DriftDetectionManager,
    DriftThresholds,
    create_drift_monitor,
    create_performance_monitor,
)
from atlas.models.transformer_forecaster import (
    FittedTransformerModel,
    TransformerConfig,
    train_transformer_forecaster,
)

router = APIRouter(prefix="/api/advanced-ml", tags=["advanced-ml"])


class TransformerTrainRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    features: list[list[list[float]]]
    targets: list[list[float]]
    d_model: int = 32
    n_heads: int = 2
    n_layers: int = 1
    d_ff: int = 64
    dropout: float = 0.1
    sequence_length: int = 60
    forecast_horizon: int = 5
    seed: int = 42
    epochs: int = 60
    learning_rate: float = 0.01
    batch_size: int = 16
    validation_split: float = 0.2


class TransformerTrainResponse(BaseModel):
    model_id: str
    dataset_id: str
    training_mae: float
    validation_mae: float
    training_samples: int
    validation_samples: int
    seed: int
    execution_permission: Literal["none"] = "none"


class TransformerForecastRequest(BaseModel):
    model_id: str
    features: list[list[float]]
    mc_samples: int = Field(default=100, ge=1, le=2000)
    enable_dropout: bool = True


class TransformerForecastResponse(BaseModel):
    model_id: str
    predictions: list[float]
    lower_bounds: list[float]
    upper_bounds: list[float]
    confidence: float
    attention_weights: list[list[float]] = Field(default_factory=list)
    execution_permission: Literal["none"] = "none"


class DriftCheckRequest(BaseModel):
    monitor_id: str
    feature_name: str
    current_values: list[float]
    method: Literal["ks", "psi", "both"] = "both"


class DriftResult(BaseModel):
    drift_type: Literal["ks", "psi"]
    drift_detected: bool
    statistic: float
    threshold: float
    severity: Literal["low", "medium", "high", "critical"]


class DriftCheckResponse(BaseModel):
    monitor_id: str
    feature_name: str
    drift_detected: bool
    statistic: float
    threshold: float
    severity: Literal["low", "medium", "high", "critical"]
    reports: list[DriftResult] = Field(default_factory=list)
    execution_permission: Literal["none"] = "none"


class FeatureStoreRequest(BaseModel):
    feature_name: str
    data: list[dict]
    metadata: dict
    version: int | None = None


class FeatureStoreResponse(BaseModel):
    feature_name: str
    version: int
    row_count: int
    artifact_path: str
    execution_permission: Literal["none"] = "none"


class UncertaintyGatingRequest(BaseModel):
    model_id: str
    instrument_id: str
    prediction: float
    lower: float | None = None
    upper: float | None = None
    confidence: float
    current_price: float
    proposed_position: float


class UncertaintyGatingResponse(BaseModel):
    trade_allowed: bool
    position_scale: float
    uncertainty_level: Literal["low", "medium", "high", "extreme"]
    rejection_reason: str | None
    execution_permission: Literal["none"] = "none"


class DriftMonitorCreateRequest(BaseModel):
    monitor_id: str
    feature_names: list[str]
    baseline_values: list[list[float]]
    baseline_metrics: dict[str, float] = Field(default_factory=dict)


class DriftEvaluateRequest(BaseModel):
    current_features: dict[str, list[float]]
    current_metrics: dict[str, float] = Field(default_factory=dict)


_feature_store = None
_drift_managers: dict[str, DriftDetectionManager] = {}
_uncertainty_gating = None
_models: dict[str, FittedTransformerModel] = {}


def _get_feature_store():
    global _feature_store
    if _feature_store is None:
        _feature_store = create_feature_store(
            store_id="main",
            db_path="data/feature_store.db",
            parquet_dir="data/parquet_features",
        )
    return _feature_store


def _reject_forbidden_role(role_id: str | None, action: str) -> None:
    if role_id is None or not role_id.strip():
        return
    try:
        verdict = verify_role_action(role_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not verdict["authorized"]:
        raise HTTPException(status_code=403, detail=str(verdict["reason"]))


@router.get("/status")
async def advanced_ml_status() -> dict:
    """Identify this router as experimental and point to the audited slice."""
    return {
        "status": "experimental",
        "audited_path": "/api/research/vertical-slice",
        "notice": (
            "The advanced-ML router is an opt-in experimental toolkit for caller-supplied "
            "sequence, drift, feature, and gating experiments. It is not the audited "
            "vertical-slice pipeline and it cannot authorize an order."
        ),
        "models_loaded": len(_models),
        "drift_monitors": len(_drift_managers),
        "execution_permission": "none",
    }


@router.post("/train", response_model=TransformerTrainResponse)
async def train_transformer(
    request: TransformerTrainRequest,
    x_role_id: str | None = Header(None),
):
    """Train a seeded sequence forecaster on caller-supplied research data."""
    _reject_forbidden_role(x_role_id, "transformer_train")

    features = np.asarray(request.features, dtype=np.float64)
    targets = np.asarray(request.targets, dtype=np.float64)
    config = TransformerConfig(
        d_model=request.d_model,
        n_heads=request.n_heads,
        n_layers=request.n_layers,
        d_ff=request.d_ff,
        dropout=request.dropout,
        sequence_length=request.sequence_length,
        forecast_horizon=request.forecast_horizon,
    )
    try:
        model = train_transformer_forecaster(
            dataset_id=request.dataset_id,
            features=features,
            targets=targets,
            config=config,
            seed=request.seed,
            epochs=request.epochs,
            learning_rate=request.learning_rate,
            batch_size=request.batch_size,
            validation_split=request.validation_split,
        )
    except (ValueError, FloatingPointError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _models[model.model_id] = model
    n_samples = len(features)
    n_val = max(1, int(round(n_samples * request.validation_split)))
    return TransformerTrainResponse(
        model_id=model.model_id,
        dataset_id=model.dataset_id,
        training_mae=model.training_mae,
        validation_mae=model.validation_mae,
        training_samples=n_samples - n_val,
        validation_samples=n_val,
        seed=model.seed,
    )


@router.get("/models")
async def list_models(
    x_role_id: str | None = Header(None),
):
    """List models trained by this process."""
    _reject_forbidden_role(x_role_id, "transformer_forecast")
    return {
        "models": [
            {
                "model_id": model.model_id,
                "dataset_id": model.dataset_id,
                "trained_through": model.trained_through.isoformat(),
                "training_mae": model.training_mae,
                "validation_mae": model.validation_mae,
            }
            for model in _models.values()
        ],
        "count": len(_models),
        "execution_permission": "none",
    }


@router.post("/forecast", response_model=TransformerForecastResponse)
async def transformer_forecast(
    request: TransformerForecastRequest,
    x_role_id: str | None = Header(None),
):
    """Generate a forecast from a model trained in this process."""
    _reject_forbidden_role(x_role_id, "transformer_forecast")

    model = _models.get(request.model_id)
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Model {request.model_id} is not loaded. Train it with "
                "POST /api/advanced-ml/train first."
            ),
        )

    features = np.asarray(request.features, dtype=np.float64)
    if features.ndim == 2:
        features = features[None, :, :]
    try:
        mean, (lower, upper) = model.forecaster.predict(
            features,
            mc_samples=request.mc_samples,
            training=request.enable_dropout,
        )
        attention = model.forecaster.attention_summary(features)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return TransformerForecastResponse(
        model_id=model.model_id,
        predictions=[float(v) for v in mean[0]],
        lower_bounds=[float(v) for v in lower[0]],
        upper_bounds=[float(v) for v in upper[0]],
        confidence=model.config.confidence_level,
        attention_weights=attention,
    )


@router.post("/drift/check", response_model=DriftCheckResponse)
async def check_drift(
    request: DriftCheckRequest,
    x_role_id: str | None = Header(None),
):
    """Check an existing monitor against current feature values."""
    _reject_forbidden_role(x_role_id, "drift_check")

    manager = _drift_managers.get(request.monitor_id)
    if manager is None:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor {request.monitor_id} not found",
        )

    monitor = manager.drift_monitor
    if request.feature_name not in monitor.baseline_features:
        raise HTTPException(
            status_code=404,
            detail=f"Feature {request.feature_name} not found in monitor",
        )

    try:
        reports = monitor.check_feature_drift(
            request.feature_name,
            np.asarray(request.current_values, dtype=np.float64),
            method=request.method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    primary = next(
        (report for report in reports if report.is_drift_detected),
        reports[0],
    )
    return DriftCheckResponse(
        monitor_id=request.monitor_id,
        feature_name=request.feature_name,
        drift_detected=primary.is_drift_detected,
        statistic=primary.statistic,
        threshold=primary.threshold,
        severity=primary.severity,
        reports=[
            DriftResult(
                drift_type=report.drift_type,
                drift_detected=report.is_drift_detected,
                statistic=report.statistic,
                threshold=report.threshold,
                severity=report.severity,
            )
            for report in reports
        ],
    )


@router.post("/features/store", response_model=FeatureStoreResponse)
async def store_feature(
    request: FeatureStoreRequest,
    x_role_id: str | None = Header(None),
):
    """Store a versioned feature artifact."""
    _reject_forbidden_role(x_role_id, "feature_store")

    import pandas as pd

    df = pd.DataFrame(request.data)
    metadata = FeatureMetadata(
        feature_name=request.feature_name,
        feature_type=request.metadata.get("feature_type", "numeric"),
        description=request.metadata.get("description", ""),
        source=request.metadata.get("source", "api"),
        lineage_ref=request.metadata.get("lineage_ref", "api_lineage"),
        license_ref=request.metadata.get("license_ref", "unknown"),
        created_at=datetime.now(timezone.utc),
        version=request.version or 1,
    )
    store = _get_feature_store()
    version_record = store.store_feature(
        feature_name=request.feature_name,
        data=df,
        metadata=metadata,
    )
    return FeatureStoreResponse(
        feature_name=version_record.feature_name,
        version=version_record.version,
        row_count=version_record.row_count,
        artifact_path=version_record.artifact_path,
    )


@router.get("/features/{feature_name}")
async def get_feature(
    feature_name: str,
    version: int | None = None,
    x_role_id: str | None = Header(None),
):
    """Read a stored feature artifact."""
    _reject_forbidden_role(x_role_id, "feature_store_read")

    store = _get_feature_store()
    try:
        df = store.get_feature(feature_name, version=version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resolved_version = version
    if resolved_version is None:
        versions = store.get_feature_versions(feature_name)
        resolved_version = versions[0].version if versions else None
    return {
        "feature_name": feature_name,
        "version": resolved_version,
        "row_count": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records")[:100],
        "execution_permission": "none",
    }


@router.get("/features")
async def list_features(
    x_role_id: str | None = Header(None),
):
    """List all stored features."""
    _reject_forbidden_role(x_role_id, "feature_store_read")
    store = _get_feature_store()
    features = store.list_features()
    return {
        "features": features,
        "count": len(features),
        "execution_permission": "none",
    }


@router.post("/uncertainty/gate", response_model=UncertaintyGatingResponse)
async def uncertainty_gate(
    request: UncertaintyGatingRequest,
    x_role_id: str | None = Header(None),
):
    """Evaluate a proposed trade with the uncertainty gate."""
    _reject_forbidden_role(x_role_id, "uncertainty_gating")

    global _uncertainty_gating
    if _uncertainty_gating is None:
        _uncertainty_gating = create_uncertainty_gating("main_gate")

    try:
        decision = _uncertainty_gating.evaluate_trade(
            model_id=request.model_id,
            instrument_id=request.instrument_id,
            prediction=request.prediction,
            lower=request.lower,
            upper=request.upper,
            confidence=request.confidence,
            current_price=request.current_price,
            proposed_position=request.proposed_position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return UncertaintyGatingResponse(
        trade_allowed=decision.trade_allowed,
        position_scale=decision.position_scale,
        uncertainty_level=decision.uncertainty_level,
        rejection_reason=decision.rejection_reason,
    )


@router.get("/drift/monitors")
async def list_drift_monitors(
    x_role_id: str | None = Header(None),
):
    """List active drift monitors."""
    _reject_forbidden_role(x_role_id, "drift_monitor_read")
    return {
        "monitors": list(_drift_managers.keys()),
        "count": len(_drift_managers),
        "execution_permission": "none",
    }


@router.post("/drift/monitor/create")
async def create_drift_monitor_endpoint(
    request: DriftMonitorCreateRequest,
    x_role_id: str | None = Header(None),
):
    """Create a drift monitor from an observed baseline."""
    _reject_forbidden_role(x_role_id, "drift_monitor_create")

    if len(request.feature_names) != len(request.baseline_values):
        raise HTTPException(
            status_code=422,
            detail="feature_names and baseline_values must have equal length",
        )
    if not request.feature_names:
        raise HTTPException(status_code=422, detail="At least one feature is required")

    baseline_features = {
        name: np.asarray(values, dtype=np.float64)
        for name, values in zip(request.feature_names, request.baseline_values)
    }
    if any(values.size == 0 for values in baseline_features.values()):
        raise HTTPException(status_code=422, detail="Baseline values cannot be empty")
    if any(
        not np.all(np.isfinite(values))
        for values in baseline_features.values()
    ):
        raise HTTPException(status_code=422, detail="Baseline values must be finite")

    thresholds = DriftThresholds()
    monitor = create_drift_monitor(
        monitor_id=request.monitor_id,
        baseline_features=baseline_features,
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    perf_monitor = create_performance_monitor(
        monitor_id=f"{request.monitor_id}_perf",
        baseline_metrics=request.baseline_metrics,
        thresholds=thresholds,
    )
    manager = DriftDetectionManager(
        manager_id=f"{request.monitor_id}_manager",
        drift_monitor=monitor,
        performance_monitor=perf_monitor,
    )
    _drift_managers[request.monitor_id] = manager
    return {
        "monitor_id": request.monitor_id,
        "status": "created",
        "features": request.feature_names,
        "execution_permission": "none",
    }


@router.get("/drift/dashboard/summary")
async def drift_dashboard_summary(
    x_role_id: str | None = Header(None),
):
    """Summarize active drift monitors."""
    _reject_forbidden_role(x_role_id, "drift_dashboard_read")

    summary = {
        "monitors": [],
        "total_monitors": len(_drift_managers),
        "active_alerts": 0,
        "execution_permission": "none",
    }
    for monitor_id, manager in _drift_managers.items():
        monitor_summary = {
            "monitor_id": monitor_id,
            "features": list(manager.drift_monitor.baseline_features.keys()),
            "trigger_count": len(manager.trigger_history),
            "last_trigger": None,
            "status": "active",
        }
        if manager.trigger_history:
            last_trigger = manager.trigger_history[-1]
            monitor_summary["last_trigger"] = {
                "triggered_at": last_trigger.triggered_at.isoformat(),
                "priority": last_trigger.priority,
                "should_retrain": last_trigger.should_retrain,
            }
            if last_trigger.should_retrain:
                summary["active_alerts"] += 1
        summary["monitors"].append(monitor_summary)
    return summary


@router.get("/drift/dashboard/{monitor_id}/history")
async def drift_monitor_history(
    monitor_id: str,
    limit: int = 50,
    x_role_id: str | None = Header(None),
):
    """Return trigger history for one monitor."""
    _reject_forbidden_role(x_role_id, "drift_dashboard_read")
    manager = _drift_managers.get(monitor_id)
    if manager is None:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor {monitor_id} not found",
        )

    history = manager.trigger_history[-max(1, limit):]
    return {
        "monitor_id": monitor_id,
        "triggers": [
            {
                "trigger_id": trigger.trigger_id,
                "triggered_at": trigger.triggered_at.isoformat(),
                "priority": trigger.priority,
                "should_retrain": trigger.should_retrain,
                "reason": trigger.trigger_reason,
                "drift_reports_count": len(trigger.drift_reports),
                "performance_reports_count": len(trigger.performance_reports),
            }
            for trigger in history
        ],
        "total_triggers": len(manager.trigger_history),
        "execution_permission": "none",
    }


@router.post("/drift/dashboard/{monitor_id}/evaluate")
async def evaluate_drift_dashboard(
    monitor_id: str,
    request: DriftEvaluateRequest,
    x_role_id: str | None = Header(None),
):
    """Evaluate drift for a monitor from supplied observations."""
    _reject_forbidden_role(x_role_id, "drift_evaluate")
    manager = _drift_managers.get(monitor_id)
    if manager is None:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor {monitor_id} not found",
        )
    if not manager.drift_monitor.baseline_features:
        raise HTTPException(
            status_code=409,
            detail="Monitor has no baseline; recreate it with observed data",
        )

    current_features = {
        name: np.asarray(values, dtype=np.float64)
        for name, values in request.current_features.items()
    }
    trigger = manager.evaluate_drift(
        current_features=current_features,
        current_metrics=request.current_metrics,
        model_id=monitor_id,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc),
    )
    return {
        "trigger_id": trigger.trigger_id,
        "triggered_at": trigger.triggered_at.isoformat(),
        "should_retrain": trigger.should_retrain,
        "priority": trigger.priority,
        "reason": trigger.trigger_reason,
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
        "execution_permission": "none",
    }
