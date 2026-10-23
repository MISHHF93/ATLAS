from __future__ import annotations

import numpy as np

from atlas.marketdata.frozen import build_frozen_benchmark_dataset
from atlas.models.transformer_challenger import (
    FEATURE_NAMES,
    TransformerChallengerProvider,
    build_sequences,
    run_transformer_vs_baseline_study,
)


def test_sequences_come_from_verified_observations() -> None:
    dataset = build_frozen_benchmark_dataset(track="competition")
    sequences = build_sequences(dataset)

    assert sequences.samples > 0
    assert sequences.features.shape[2] == len(FEATURE_NAMES)
    assert sequences.features.shape[1] == sequences.effective_config.sequence_length
    assert sequences.targets.shape[1] == sequences.effective_config.forecast_horizon
    assert len(sequences.decision_times) == sequences.samples
    assert all(
        sequences.decision_times[index] < sequences.target_times[index][-1]
        for index in range(sequences.samples)
    )
    assert np.all(np.isfinite(sequences.features))


def test_walk_forward_is_purged_and_has_a_naive_baseline() -> None:
    dataset = build_frozen_benchmark_dataset(track="open_market")
    report = run_transformer_vs_baseline_study(dataset)

    assert report["status"] == "scored"
    assert report["folds"]
    assert all(fold["no_label_overlap"] for fold in report["folds"])
    assert report["transformer"]
    assert report["naive_baseline"]
    assert report["execution_permission"] == "none"
    for split, evaluation in report["transformer"].items():
        assert evaluation.samples >= 4
        assert split in report["naive_baseline"]


def test_transformer_training_is_seeded_and_measured() -> None:
    dataset = build_frozen_benchmark_dataset(track="competition")
    provider = TransformerChallengerProvider()

    first = provider.train_transformer(dataset, seed=7, epochs=30)
    second = provider.train_transformer(dataset, seed=7, epochs=30)

    assert first.model_id == second.model_id
    assert first.training_mae == second.training_mae
    assert first.validation_mae == second.validation_mae
    assert np.isfinite(first.training_mae)
    assert np.isfinite(first.validation_mae)
