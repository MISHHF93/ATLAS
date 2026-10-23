"""Unit tests for drift detection."""

import pytest
import numpy as np
from datetime import datetime, timezone

from atlas.models.drift_detection import (
    DriftMonitor,
    DriftThresholds,
    PerformanceMonitor,
    DriftDetectionManager,
    create_drift_monitor,
    create_performance_monitor,
)


def test_drift_thresholds():
    """Test drift threshold configuration."""
    thresholds = DriftThresholds(
        ks_critical=0.15,
        psi_critical=0.3,
        mae_degradation=0.25,
        accuracy_degradation=0.15,
    )
    
    assert thresholds.ks_critical == 0.15
    assert thresholds.psi_critical == 0.3


def test_ks_statistic():
    """Test Kolmogorov-Smirnov statistic computation."""
    thresholds = DriftThresholds()
    
    # Create baseline and current data
    baseline = np.random.randn(1000)
    current = baseline + np.random.randn(1000) * 0.5  # Slight drift
    
    monitor = create_drift_monitor(
        monitor_id="test",
        baseline_features={"feature1": baseline},
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    
    ks_stat, is_drift, severity = monitor.compute_ks_statistic("feature1", current)
    
    assert 0 <= ks_stat <= 1
    assert isinstance(is_drift, bool)
    assert severity in ("low", "medium", "high", "critical")


def test_psi_computation():
    """Test Population Stability Index computation."""
    thresholds = DriftThresholds()
    
    # Create baseline and current data
    baseline = np.random.randn(1000)
    current = baseline + np.random.randn(1000) * 0.8  # Moderate drift
    
    monitor = create_drift_monitor(
        monitor_id="test",
        baseline_features={"feature1": baseline},
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    
    psi, is_drift, severity = monitor.compute_psi("feature1", current)
    
    assert psi >= 0
    assert isinstance(is_drift, bool)
    assert severity in ("low", "medium", "high", "critical")


def test_performance_drift():
    """Test performance-based drift detection."""
    thresholds = DriftThresholds()
    
    monitor = create_performance_monitor(
        monitor_id="test",
        baseline_metrics={"mae": 0.05, "directional_accuracy": 0.60},
        thresholds=thresholds,
    )
    
    # Test degradation
    report = monitor.check_performance_drift("mae", 0.07)  # 40% degradation
    
    assert report.metric_name == "mae"
    assert report.baseline_value == 0.05
    assert report.current_value == 0.07
    assert report.degradation_pct > 0
    
    # Test improvement (should not trigger drift)
    report2 = monitor.check_performance_drift("mae", 0.04)
    assert report2.degradation_pct < 0


def test_drift_detection_manager():
    """Test drift detection manager."""
    thresholds = DriftThresholds()
    
    drift_monitor = create_drift_monitor(
        monitor_id="test_drift",
        baseline_features={"feature1": np.random.randn(100)},
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    
    perf_monitor = create_performance_monitor(
        monitor_id="test_perf",
        baseline_metrics={"mae": 0.05},
        thresholds=thresholds,
    )
    
    manager = DriftDetectionManager(
        manager_id="test_manager",
        drift_monitor=drift_monitor,
        performance_monitor=perf_monitor,
    )
    
    # Evaluate drift
    current_features = {"feature1": np.random.randn(50)}
    current_metrics = {"mae": 0.08}
    
    trigger = manager.evaluate_drift(
        current_features=current_features,
        current_metrics=current_metrics,
        model_id="test_model",
    )
    
    assert trigger.model_id == "test_model"
    assert trigger.trigger_id is not None
    assert isinstance(trigger.should_retrain, bool)
    assert trigger.priority in ("low", "medium", "high", "critical")


def test_feature_drift_check():
    """Test checking drift for a specific feature."""
    thresholds = DriftThresholds()
    
    baseline = np.random.randn(1000)
    current = np.random.randn(500)
    
    monitor = create_drift_monitor(
        monitor_id="test",
        baseline_features={"test_feature": baseline},
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    
    reports = monitor.check_feature_drift(
        "test_feature",
        current,
        method="both",
    )
    
    assert len(reports) == 2  # KS and PSI
    assert any(r.drift_type == "ks" for r in reports)
    assert any(r.drift_type == "psi" for r in reports)


def test_all_features_drift():
    """Test checking drift for all features."""
    thresholds = DriftThresholds()
    
    baseline_features = {
        "feature1": np.random.randn(1000),
        "feature2": np.random.randn(1000),
        "feature3": np.random.randn(1000),
    }
    
    monitor = create_drift_monitor(
        monitor_id="test",
        baseline_features=baseline_features,
        baseline_timestamps=[datetime.now(timezone.utc)],
        thresholds=thresholds,
    )
    
    current_features = {
        "feature1": np.random.randn(500),
        "feature2": np.random.randn(500),
        "feature3": np.random.randn(500),
    }
    
    all_reports = monitor.check_all_features_drift(current_features, method="ks")
    
    assert len(all_reports) == 3
    assert "feature1" in all_reports
    assert "feature2" in all_reports
    assert "feature3" in all_reports
