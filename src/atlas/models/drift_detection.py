"""Statistical and performance-based drift detection for model monitoring.

Implements:
- Kolmogorov-Smirnov (KS) test for feature distribution drift
- Population Stability Index (PSI) for feature drift
- Performance-based drift monitoring (MAE, directional accuracy)
- Automated retraining triggers based on drift thresholds
- Drift alerting and reporting

All outputs retain execution_permission: none.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, Field

from atlas.models.schemas import Record, Text, Probability


@dataclass(frozen=True)
class DriftThresholds:
    """Thresholds for drift detection alerts."""
    
    ks_critical: float = 0.1  # KS statistic threshold
    psi_critical: float = 0.25  # PSI threshold
    mae_degradation: float = 0.2  # 20% MAE degradation triggers alert
    accuracy_degradation: float = 0.1  # 10% accuracy degradation triggers alert


class DriftReport(Record):
    """Report on detected drift for a feature or metric."""
    
    feature_name: Text
    drift_type: Literal["ks", "psi", "performance"]
    statistic: float
    threshold: float
    is_drift_detected: bool
    severity: Literal["low", "medium", "high", "critical"]
    timestamp: AwareDatetime
    baseline_period_start: AwareDatetime
    baseline_period_end: AwareDatetime
    current_period_start: AwareDatetime
    current_period_end: AwareDatetime
    execution_permission: Literal["none"] = "none"


class PerformanceDriftReport(Record):
    """Report on performance-based drift."""
    
    metric_name: Text
    baseline_value: float
    current_value: float
    degradation_pct: float
    threshold_pct: float
    is_drift_detected: bool
    severity: Literal["low", "medium", "high", "critical"]
    timestamp: AwareDatetime
    execution_permission: Literal["none"] = "none"


@dataclass
class DriftMonitor:
    """Monitor for statistical and performance-based drift."""

    monitor_id: str
    thresholds: DriftThresholds
    baseline_features: dict[str, np.ndarray]
    baseline_timestamps: tuple[AwareDatetime, ...]

    def compute_ks_statistic(
        self,
        feature_name: str,
        current_values: np.ndarray,
    ) -> tuple[float, bool, Literal["low", "medium", "high", "critical"]]:
        """Compute Kolmogorov-Smirnov statistic for feature drift.
        
        Args:
            feature_name: Name of the feature to check
            current_values: Current feature values
        
        Returns:
            (ks_statistic, is_drift_detected, severity)
        """
        if feature_name not in self.baseline_features:
            raise ValueError(f"Feature {feature_name} not in baseline")
        
        baseline_values = self.baseline_features[feature_name]
        
        # Compute empirical CDFs
        baseline_sorted = np.sort(baseline_values)
        current_sorted = np.sort(current_values)
        
        n_baseline = len(baseline_sorted)
        n_current = len(current_sorted)
        
        # Combine and compute KS statistic
        all_values = np.concatenate([baseline_sorted, current_sorted])
        baseline_cdf = np.searchsorted(baseline_sorted, all_values, side='right') / n_baseline
        current_cdf = np.searchsorted(current_sorted, all_values, side='right') / n_current
        
        ks_statistic = np.max(np.abs(baseline_cdf - current_cdf))
        
        # Determine severity
        is_drift = bool(ks_statistic > self.thresholds.ks_critical)
        if ks_statistic > 0.2:
            severity = "critical"
        elif ks_statistic > 0.15:
            severity = "high"
        elif ks_statistic > self.thresholds.ks_critical:
            severity = "medium"
        else:
            severity = "low"
        
        return float(ks_statistic), is_drift, severity
    
    def compute_psi(
        self,
        feature_name: str,
        current_values: np.ndarray,
        n_bins: int = 10,
    ) -> tuple[float, bool, Literal["low", "medium", "high", "critical"]]:
        """Compute Population Stability Index (PSI) for feature drift.
        
        Args:
            feature_name: Name of the feature to check
            current_values: Current feature values
            n_bins: Number of bins for PSI calculation
        
        Returns:
            (psi_value, is_drift_detected, severity)
        """
        if feature_name not in self.baseline_features:
            raise ValueError(f"Feature {feature_name} not in baseline")
        
        baseline_values = self.baseline_features[feature_name]
        
        # Determine bin edges from baseline
        percentiles = np.linspace(0, 100, n_bins + 1)
        bin_edges = np.percentile(baseline_values, percentiles)
        
        # Ensure unique edges
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < 2:
            bin_edges = np.array([np.min(baseline_values), np.max(baseline_values)])
        
        # Compute bin counts
        baseline_counts, _ = np.histogram(baseline_values, bins=bin_edges)
        current_counts, _ = np.histogram(current_values, bins=bin_edges)
        
        # Avoid division by zero
        baseline_counts = np.maximum(baseline_counts, 1)
        current_counts = np.maximum(current_counts, 1)
        
        # Normalize to percentages
        baseline_pct = baseline_counts / np.sum(baseline_counts)
        current_pct = current_counts / np.sum(current_counts)
        
        # Compute PSI
        psi = np.sum((baseline_pct - current_pct) * np.log(baseline_pct / current_pct))
        
        # Determine severity
        is_drift = bool(psi > self.thresholds.psi_critical)
        if psi > 0.5:
            severity = "critical"
        elif psi > 0.35:
            severity = "high"
        elif psi > self.thresholds.psi_critical:
            severity = "medium"
        else:
            severity = "low"
        
        return float(psi), is_drift, severity
    
    def check_feature_drift(
        self,
        feature_name: str,
        current_values: np.ndarray,
        method: Literal["ks", "psi", "both"] = "both",
        current_period_start: AwareDatetime | None = None,
        current_period_end: AwareDatetime | None = None,
    ) -> list[DriftReport]:
        """Check for drift in a feature using specified methods.
        
        Args:
            feature_name: Name of the feature
            current_values: Current feature values
            method: Drift detection method(s) to use
            current_period_start: Start of current period
            current_period_end: End of current period
        
        Returns:
            List of drift reports
        """
        reports = []
        
        if current_period_start is None:
            current_period_start = datetime.now(timezone.utc)
        if current_period_end is None:
            current_period_end = datetime.now(timezone.utc)
        
        baseline_start = self.baseline_timestamps[0]
        baseline_end = self.baseline_timestamps[-1]
        
        if method in ("ks", "both"):
            ks_stat, is_drift, severity = self.compute_ks_statistic(
                feature_name, current_values
            )
            reports.append(
                DriftReport(
                    feature_name=feature_name,
                    drift_type="ks",
                    statistic=ks_stat,
                    threshold=self.thresholds.ks_critical,
                    is_drift_detected=is_drift,
                    severity=severity,
                    timestamp=datetime.now(timezone.utc),
                    baseline_period_start=baseline_start,
                    baseline_period_end=baseline_end,
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                )
            )
        
        if method in ("psi", "both"):
            psi, is_drift, severity = self.compute_psi(feature_name, current_values)
            reports.append(
                DriftReport(
                    feature_name=feature_name,
                    drift_type="psi",
                    statistic=psi,
                    threshold=self.thresholds.psi_critical,
                    is_drift_detected=is_drift,
                    severity=severity,
                    timestamp=datetime.now(timezone.utc),
                    baseline_period_start=baseline_start,
                    baseline_period_end=baseline_end,
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                )
            )
        
        return reports
    
    def check_all_features_drift(
        self,
        current_features: dict[str, np.ndarray],
        method: Literal["ks", "psi", "both"] = "both",
        current_period_start: AwareDatetime | None = None,
        current_period_end: AwareDatetime | None = None,
    ) -> dict[str, list[DriftReport]]:
        """Check drift for all features.
        
        Args:
            current_features: Dictionary of current feature values
            method: Drift detection method(s)
            current_period_start: Start of current period
            current_period_end: End of current period
        
        Returns:
            Dictionary mapping feature names to drift reports
        """
        all_reports = {}
        
        for feature_name in self.baseline_features.keys():
            if feature_name in current_features:
                reports = self.check_feature_drift(
                    feature_name,
                    current_features[feature_name],
                    method,
                    current_period_start,
                    current_period_end,
                )
                all_reports[feature_name] = reports
        
        return all_reports


@dataclass
class PerformanceMonitor:
    """Monitor for performance-based drift detection."""

    monitor_id: str
    thresholds: DriftThresholds
    baseline_metrics: dict[str, float]

    def check_performance_drift(
        self,
        metric_name: str,
        current_value: float,
    ) -> PerformanceDriftReport:
        """Check for performance degradation.
        
        Args:
            metric_name: Name of the metric (e.g., "mae", "directional_accuracy")
            current_value: Current metric value
        
        Returns:
            Performance drift report
        """
        if metric_name not in self.baseline_metrics:
            raise ValueError(f"Metric {metric_name} not in baseline")
        
        baseline_value = self.baseline_metrics[metric_name]
        
        # Compute degradation
        if metric_name in ("mae", "rmse"):
            # For error metrics, increase is degradation
            degradation_pct = (current_value - baseline_value) / max(1e-6, baseline_value)
            threshold = self.thresholds.mae_degradation
        else:
            # For accuracy metrics, decrease is degradation
            degradation_pct = (baseline_value - current_value) / max(1e-6, baseline_value)
            threshold = self.thresholds.accuracy_degradation
        
        is_drift = bool(degradation_pct > threshold)
        
        # Determine severity
        if degradation_pct > 0.5:
            severity = "critical"
        elif degradation_pct > 0.35:
            severity = "high"
        elif degradation_pct > threshold:
            severity = "medium"
        else:
            severity = "low"
        
        return PerformanceDriftReport(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            degradation_pct=degradation_pct,
            threshold_pct=threshold,
            is_drift_detected=is_drift,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
        )


class RetrainingTrigger(Record):
    """Automated retraining trigger based on drift detection."""
    
    trigger_id: Text
    model_id: Text
    trigger_reason: Text
    drift_reports: tuple[DriftReport, ...]
    performance_reports: tuple[PerformanceDriftReport, ...]
    triggered_at: AwareDatetime
    should_retrain: bool
    priority: Literal["low", "medium", "high", "critical"]
    execution_permission: Literal["none"] = "none"
    
    def should_trigger_retraining(self) -> bool:
        """Determine if retraining should be triggered."""
        # Trigger if any critical or high severity drift detected
        for report in self.drift_reports:
            if report.severity in ("critical", "high"):
                return True
        
        for report in self.performance_reports:
            if report.severity in ("critical", "high"):
                return True
        
        return self.should_retrain


@dataclass
class DriftDetectionManager:
    """Manager for drift detection and retraining triggers."""

    manager_id: str
    drift_monitor: DriftMonitor
    performance_monitor: PerformanceMonitor
    trigger_history: list[RetrainingTrigger] = field(default_factory=list)

    def evaluate_drift(
        self,
        current_features: dict[str, np.ndarray],
        current_metrics: dict[str, float],
        model_id: str,
        current_period_start: AwareDatetime | None = None,
        current_period_end: AwareDatetime | None = None,
    ) -> RetrainingTrigger:
        """Evaluate drift and determine if retraining is needed.
        
        Args:
            current_features: Current feature values
            current_metrics: Current performance metrics
            model_id: Model identifier
            current_period_start: Start of current period
            current_period_end: End of current period
        
        Returns:
            Retraining trigger with decision
        """
        # Check feature drift
        feature_drift_reports = []
        for feature_name, values in current_features.items():
            if feature_name in self.drift_monitor.baseline_features:
                reports = self.drift_monitor.check_feature_drift(
                    feature_name,
                    values,
                    method="both",
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                )
                feature_drift_reports.extend(reports)
        
        # Check performance drift
        performance_reports = []
        for metric_name, value in current_metrics.items():
            if metric_name in self.performance_monitor.baseline_metrics:
                report = self.performance_monitor.check_performance_drift(
                    metric_name, value
                )
                performance_reports.append(report)
        
        # Determine priority
        all_severities = [r.severity for r in feature_drift_reports] + [
            r.severity for r in performance_reports
        ]
        if "critical" in all_severities:
            priority = "critical"
        elif "high" in all_severities:
            priority = "high"
        elif "medium" in all_severities:
            priority = "medium"
        else:
            priority = "low"
        
        # Build trigger
        trigger = RetrainingTrigger(
            trigger_id=f"trigger_{model_id}_{datetime.now(timezone.utc).isoformat()}",
            model_id=model_id,
            trigger_reason="Drift detected in features or performance",
            drift_reports=tuple(feature_drift_reports),
            performance_reports=tuple(performance_reports),
            triggered_at=datetime.now(timezone.utc),
            should_retrain=priority in ("high", "critical"),
            priority=priority,
        )
        
        # Add to history
        self.trigger_history.append(trigger)
        
        return trigger


def create_drift_monitor(
    monitor_id: str,
    baseline_features: dict[str, np.ndarray],
    baseline_timestamps: list[AwareDatetime],
    thresholds: DriftThresholds | None = None,
) -> DriftMonitor:
    """Create a drift monitor with baseline data.
    
    Args:
        monitor_id: Monitor identifier
        baseline_features: Baseline feature values
        baseline_timestamps: Baseline timestamps
        thresholds: Drift detection thresholds
    
    Returns:
        Configured drift monitor
    """
    if thresholds is None:
        thresholds = DriftThresholds()
    
    return DriftMonitor(
        monitor_id=monitor_id,
        thresholds=thresholds,
        baseline_features=baseline_features,
        baseline_timestamps=tuple(baseline_timestamps),
    )


def create_performance_monitor(
    monitor_id: str,
    baseline_metrics: dict[str, float],
    thresholds: DriftThresholds | None = None,
) -> PerformanceMonitor:
    """Create a performance monitor with baseline metrics.
    
    Args:
        monitor_id: Monitor identifier
        baseline_metrics: Baseline metric values
        thresholds: Drift detection thresholds
    
    Returns:
        Configured performance monitor
    """
    if thresholds is None:
        thresholds = DriftThresholds()
    
    return PerformanceMonitor(
        monitor_id=monitor_id,
        thresholds=thresholds,
        baseline_metrics=baseline_metrics,
    )
