"""Adversarial checks for train-only frequency priors in walk-forward selection."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np

from atlas.research import vertical_slice as slice_module
from atlas.research.vertical_slice import FEATURE_NAMES, FeatureRow, SliceConfig, purged_walk_forward


def _rows(count: int = 60) -> list[FeatureRow]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        FeatureRow(
            features=tuple((index % 7) / 10.0 for _ in FEATURE_NAMES),
            decision_time=start + timedelta(days=index),
            target_time=start + timedelta(days=index + 1),
            reference_price=100.0,
            target_price=100.1,
            forward_return=0.001,
            label=index % 3,
        )
        for index in range(count)
    ]


def test_frequency_baseline_is_unchanged_when_only_heldout_outcomes_change(monkeypatch):
    monkeypatch.setattr(slice_module, "_xgboost_module", lambda: None)
    config = SliceConfig(min_train_rows=10, walk_forward_splits=2, epochs=2)
    original = _rows()
    # Only fold 1 has enough purged training rows: train 0..32, test 35..59.
    up = [replace(row, label=2) if index >= 35 else row for index, row in enumerate(original)]
    down = [replace(row, label=0) if index >= 35 else row for index, row in enumerate(original)]
    up_report = purged_walk_forward(up, "TEST", cost_bps=4, config=config, collect_rows=True)
    down_report = purged_walk_forward(down, "TEST", cost_bps=4, config=config, collect_rows=True)

    assert up_report["folds"] == down_report["folds"]
    assert len(up_report["prediction_rows"]) == 25
    expected = (np.bincount([row.label for row in original[:33]], minlength=3) + 0.5) / 34.5
    for up_row, down_row in zip(up_report["prediction_rows"], down_report["prediction_rows"]):
        assert up_row["label"] != down_row["label"]
        np.testing.assert_allclose(up_row["frequency_baseline_probabilities"], expected)
        np.testing.assert_allclose(down_row["frequency_baseline_probabilities"], expected)
    assert up_report["selection"]["independent_validation"] is False
    assert up_report["selection"]["evaluation_scope"] == "pooled_walk_forward_model_selection"


def test_frequency_metrics_use_each_folds_training_prior(monkeypatch):
    monkeypatch.setattr(slice_module, "_xgboost_module", lambda: None)
    rows = _rows(100)
    rows = [replace(row, label=2) if index >= 35 else row for index, row in enumerate(rows)]
    config = SliceConfig(min_train_rows=10, walk_forward_splits=4, epochs=2)
    report = purged_walk_forward(rows, "TEST", cost_bps=4, config=config, collect_rows=True)
    expected_probabilities = []
    for fold in report["folds"]:
        training_labels = [row.label for row in rows[:fold["train_rows"]]]
        counts = np.bincount(training_labels, minlength=3) + 0.5
        prior = counts / counts.sum()
        np.testing.assert_allclose(fold["frequency_baseline_probabilities"], prior)
        expected_probabilities.extend([prior] * fold["test_rows"])

    assert len({tuple(fold["frequency_baseline_probabilities"]) for fold in report["folds"]}) > 1
    scored = report["prediction_rows"]
    outcomes = np.eye(3)[[row["label"] for row in scored]]
    expected_brier = np.sum((np.asarray(expected_probabilities) - outcomes) ** 2, axis=1).mean()
    assert report["frequency_baseline"]["brier_score"] == round(float(expected_brier), 8)
