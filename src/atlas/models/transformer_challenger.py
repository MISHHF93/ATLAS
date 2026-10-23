"""Transformer challenger built from real frozen observations.

The previous version trained on ``np.random`` placeholders and evaluated random
test matrices. This rewrite uses only the prices in a verified
:class:`FrozenDatasetBundle`, builds causal sequences, purges overlapping labels
between folds, and reports the measured evaluation. It does not invent a
baseline or a regime when the data needed to compute one is absent.

The encoder is the compact NumPy implementation in
:mod:`atlas.models.transformer_forecaster`; only its forecast head is trained.
Every output keeps ``execution_permission: "none"``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

import numpy as np

from atlas.marketdata.frozen import FrozenDatasetBundle
from atlas.models.evaluation import EvaluationReport, EvaluationRow, evaluate
from atlas.models.experiments import ExperimentStore
from atlas.models.schemas import (
    Capability,
    ModelRecord,
    ProviderInfo,
    Record,
    Text,
)
from atlas.models.transformer_forecaster import (
    FittedTransformerModel,
    TransformerConfig,
    train_transformer_forecaster,
)

FEATURE_NAMES: tuple[str, ...] = (
    "log_return_1",
    "log_return_2",
    "log_return_5",
    "realized_vol_5",
    "price_z_5",
    "drawdown_5",
)


@dataclass(frozen=True)
class SequenceDataset:
    features: np.ndarray
    targets: np.ndarray
    decision_times: tuple[datetime, ...]
    target_times: tuple[tuple[datetime, ...], ...]
    naive_values: tuple[float, ...]
    source_observations: int
    effective_config: TransformerConfig

    @property
    def samples(self) -> int:
        return int(self.features.shape[0])


def _causal_step(prices: Sequence[float], index: int) -> tuple[float, ...]:
    def log_return(periods: int) -> float:
        if index - periods < 0 or prices[index - periods] <= 0:
            return 0.0
        return math.log(prices[index] / prices[index - periods])

    recent = [
        log_return(1),
        log_return(2),
        log_return(5),
    ]
    window = [math.log(prices[pos] / prices[pos - 1]) for pos in range(max(1, index - 4), index + 1)]
    mean = sum(window) / len(window) if window else 0.0
    variance = sum((value - mean) ** 2 for value in window) / len(window) if window else 0.0
    recent.append(math.sqrt(variance))
    price_window = prices[max(0, index - 4) : index + 1]
    average = sum(price_window) / len(price_window)
    scale = math.sqrt(sum((value - average) ** 2 for value in price_window) / len(price_window))
    recent.append(0.0 if scale == 0 else (prices[index] - average) / scale)
    peak = max(price_window) if price_window else prices[index]
    recent.append(0.0 if peak <= 0 else prices[index] / peak - 1.0)
    return tuple(float(np.clip(value, -10.0, 10.0)) for value in recent)


def _effective_config(dataset: FrozenDatasetBundle, config: TransformerConfig | None) -> TransformerConfig:
    base = config or TransformerConfig(
        d_model=32,
        n_heads=2,
        n_layers=1,
        d_ff=64,
        sequence_length=12,
        forecast_horizon=3,
        mc_dropout_samples=40,
    )
    count = len(dataset.observations)
    max_sequence = max(4, count // 3)
    sequence_length = min(base.sequence_length, max_sequence)
    max_horizon = max(1, (count - sequence_length - 1) // 4)
    horizon = min(base.forecast_horizon, max_horizon)
    return TransformerConfig(
        d_model=base.d_model,
        n_heads=base.n_heads,
        n_layers=base.n_layers,
        d_ff=base.d_ff,
        dropout=base.dropout,
        sequence_length=sequence_length,
        forecast_horizon=horizon,
        mc_dropout_samples=base.mc_dropout_samples,
        confidence_level=base.confidence_level,
        ridge_alpha=base.ridge_alpha,
    )


def build_sequences(
    dataset: FrozenDatasetBundle,
    config: TransformerConfig | None = None,
) -> SequenceDataset:
    """Build price sequences and future-price targets from verified observations."""
    dataset.manifest.verify_content(dataset.serialized_bytes)
    observations = tuple(sorted(dataset.observations, key=lambda row: row.event_time))
    if len(observations) < 8:
        raise ValueError("The frozen dataset needs at least 8 observations")
    effective = _effective_config(dataset, config)
    prices = [float(row.value) for row in observations]
    if any(price <= 0 for price in prices):
        raise ValueError("Transformer sequences require strictly positive prices")
    features: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    decision_times: list[datetime] = []
    target_times: list[tuple[datetime, ...]] = []
    naive_values: list[float] = []
    sequence_length = effective.sequence_length
    horizon = effective.forecast_horizon
    for end in range(sequence_length - 1, len(prices) - horizon):
        rows = [
            _causal_step(prices, index)
            for index in range(end - sequence_length + 1, end + 1)
        ]
        future_prices = prices[end + 1 : end + horizon + 1]
        if len(future_prices) != horizon:
            continue
        features.append(np.asarray(rows, dtype=np.float64))
        targets.append(np.asarray(future_prices, dtype=np.float64))
        decision_times.append(observations[end].available_at)
        target_times.append(tuple(observations[end + 1 : end + horizon + 1][pos].available_at for pos in range(horizon)))
        naive_values.append(prices[end])
    if not features:
        raise ValueError("The frozen dataset did not produce any complete sequences")
    return SequenceDataset(
        features=np.stack(features),
        targets=np.stack(targets),
        decision_times=tuple(decision_times),
        target_times=tuple(target_times),
        naive_values=tuple(naive_values),
        source_observations=len(observations),
        effective_config=effective,
    )


class TransformerChallengerProvider(Record):
    """Provider for the compact Transformer challenger."""

    provider_id: Text = "local_transformer"
    capabilities: frozenset[Capability] = frozenset(
        {Capability.FORECAST, Capability.TRAIN, Capability.PREDICT}
    )
    location: Literal["local"] = "local"
    models: tuple[str, ...] = ("transformer_v1",)

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self.provider_id,
            capabilities=self.capabilities,
            location=self.location,
            models=self.models,
        )

    def train_transformer(
        self,
        dataset: FrozenDatasetBundle,
        config: TransformerConfig | None = None,
        seed: int = 42,
        *,
        epochs: int = 100,
        learning_rate: float = 0.01,
        batch_size: int = 16,
        validation_split: float = 0.2,
    ) -> FittedTransformerModel:
        """Train the forecast head on causal sequences from the frozen dataset."""
        sequences = build_sequences(dataset, config)
        return train_transformer_forecaster(
            dataset_id=dataset.manifest.dataset_id,
            features=sequences.features,
            targets=sequences.targets,
            config=sequences.effective_config,
            seed=seed,
            epochs=epochs,
            learning_rate=learning_rate,
            batch_size=batch_size,
            validation_split=validation_split,
            feature_names=FEATURE_NAMES,
        )

    def evaluate_transformer(
        self,
        model: FittedTransformerModel,
        test_features: np.ndarray,
        test_targets: np.ndarray,
        test_timestamps: Sequence[datetime],
        instrument_id: str,
        horizon_id: str,
        *,
        naive_values: Sequence[float] | None = None,
        transaction_cost: float = 0.001,
        mc_samples: int | None = None,
    ) -> EvaluationReport:
        """Score predictions against realized prices and a naive last-value baseline."""
        if naive_values is None:
            raise ValueError(
                "naive_values are required; the previous zero placeholder is not accepted"
            )
        features = np.asarray(test_features, dtype=np.float64)
        targets = np.asarray(test_targets, dtype=np.float64)
        if len(test_timestamps) != len(features) or len(naive_values) != len(features):
            raise ValueError("test features, timestamps, and naive values must align")
        if len(features) < 4:
            raise ValueError("evaluate() needs at least four test rows")
        predictions, _ = model.forecaster.predict(
            features,
            mc_samples=mc_samples or model.config.mc_dropout_samples,
            training=True,
        )
        rows: list[EvaluationRow] = []
        for index, timestamp in enumerate(test_timestamps):
            actual = float(targets[index, 0])
            predicted = float(predictions[index, 0])
            naive = float(naive_values[index])
            if naive <= 0:
                raise ValueError("naive price must be positive")
            actual_return = actual / naive - 1.0
            predicted_return = predicted / naive - 1.0
            rows.append(
                EvaluationRow(
                    timestamp=timestamp,
                    actual=actual,
                    predicted=predicted,
                    naive=naive,
                    actual_return=max(actual_return, -0.999999),
                    predicted_return=predicted_return,
                    proposed_position=0.0,
                    transaction_cost=transaction_cost,
                    probability_up=1.0 if predicted > naive else 0.0,
                    regime="unclassified_no_observation_window",
                    instrument_id=instrument_id,
                    horizon_id=horizon_id,
                )
            )
        return evaluate(rows)

    def run_purged_walk_forward_study(
        self,
        dataset: FrozenDatasetBundle,
        n_splits: int = 5,
        config: TransformerConfig | None = None,
        seed: int = 42,
        *,
        epochs: int = 80,
        transaction_cost: float = 0.001,
    ) -> dict[str, Any]:
        """Expanding-window study with purged overlapping targets.

        The training set stops before the first test decision whose feature
        window would include a training target timestamp. This is stricter than
        only subtracting the horizon because sequence windows overlap.
        """
        if n_splits < 2:
            raise ValueError("n_splits must be at least 2")
        sequences = build_sequences(dataset, config)
        total = sequences.samples
        test_size = max(4, total // (n_splits + 1))
        fold_reports: dict[str, EvaluationReport] = {}
        baseline_reports: dict[str, EvaluationReport] = {}
        folds: list[dict[str, Any]] = []
        for fold in range(n_splits):
            test_start = total - (n_splits - fold) * test_size
            test_end = min(total, test_start + test_size)
            if test_start < 4 or test_end - test_start < 4:
                continue
            train_end = 0
            for candidate in range(test_start, 0, -1):
                last_target = sequences.target_times[candidate - 1][-1]
                if last_target < sequences.decision_times[test_start]:
                    train_end = candidate
                    break
            if train_end < 4:
                continue
            model = train_transformer_forecaster(
                dataset_id=f"{dataset.manifest.dataset_id}:fold{fold}",
                features=sequences.features[:train_end],
                targets=sequences.targets[:train_end],
                config=sequences.effective_config,
                seed=seed + fold,
                epochs=epochs,
                batch_size=8,
                validation_split=0.2,
                feature_names=FEATURE_NAMES,
            )
            test_indices = range(test_start, test_end)
            timestamps = [sequences.decision_times[index] for index in test_indices]
            report = self.evaluate_transformer(
                model,
                sequences.features[test_start:test_end],
                sequences.targets[test_start:test_end],
                timestamps,
                instrument_id=dataset.instrument.instrument_id,
                horizon_id=f"h{sequences.effective_config.forecast_horizon}",
                naive_values=[sequences.naive_values[index] for index in test_indices],
                transaction_cost=transaction_cost,
            )
            fold_reports[f"split_{fold}"] = report
            baseline_rows = []
            for index in test_indices:
                naive = sequences.naive_values[index]
                actual = float(sequences.targets[index, 0])
                baseline_rows.append(
                    EvaluationRow(
                        timestamp=sequences.decision_times[index],
                        actual=actual,
                        predicted=naive,
                        naive=naive,
                        actual_return=max(actual / naive - 1.0, -0.999999),
                        predicted_return=0.0,
                        proposed_position=0.0,
                        transaction_cost=transaction_cost,
                        probability_up=0.5,
                        regime="unclassified_no_observation_window",
                        instrument_id=dataset.instrument.instrument_id,
                        horizon_id=f"h{sequences.effective_config.forecast_horizon}",
                    )
                )
            baseline_reports[f"split_{fold}"] = evaluate(baseline_rows)
            folds.append(
                {
                    "fold": fold,
                    "train_samples": train_end,
                    "test_samples": test_end - test_start,
                    "train_last_target": sequences.target_times[train_end - 1][-1].isoformat(),
                    "test_first_decision": sequences.decision_times[test_start].isoformat(),
                    "no_label_overlap": sequences.target_times[train_end - 1][-1] < sequences.decision_times[test_start],
                }
            )
        if not fold_reports:
            return {
                "status": "insufficient_history",
                "samples": total,
                "notice": "No fold had enough training rows after purging.",
                "execution_permission": "none",
            }
        return {
            "status": "scored",
            "dataset_id": dataset.manifest.dataset_id,
            "instrument_id": dataset.instrument.instrument_id,
            "sequence_config": {
                "sequence_length": sequences.effective_config.sequence_length,
                "forecast_horizon": sequences.effective_config.forecast_horizon,
                "feature_names": list(FEATURE_NAMES),
            },
            "source_observations": sequences.source_observations,
            "folds": folds,
            "transformer": fold_reports,
            "naive_baseline": baseline_reports,
            "execution_permission": "none",
            "limitations": [
                "Only the forecast head is optimized; encoder projections are fixed.",
                "The frozen bundle contains price observations, so no volume or order-book feature is claimed.",
                "Regime slicing is omitted rather than fabricating regime labels.",
            ],
        }

    def register_model(
        self,
        model: FittedTransformerModel,
        experiment_id: str,
        artifact_uri: str,
        license_ref: str,
        store: ExperimentStore,
    ) -> ModelRecord:
        """Register a model with a deterministic descriptor hash."""
        descriptor = json.dumps(
            {
                "model_id": model.model_id,
                "dataset_id": model.dataset_id,
                "config": model.config.__dict__,
                "output_projection": model.forecaster.output_projection.tolist(),
                "output_bias": model.forecaster.output_bias.tolist(),
                "training_mae": model.training_mae,
                "validation_mae": model.validation_mae,
            },
            sort_keys=True,
        ).encode("utf-8")
        artifact_sha256 = hashlib.sha256(descriptor).hexdigest()
        record = model.to_model_record(
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256,
            experiment_id=experiment_id,
            license_ref=license_ref,
        )
        store.register_model(record)
        return record


def run_transformer_vs_baseline_study(
    dataset: FrozenDatasetBundle,
    config: TransformerConfig | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Run the real Transformer study with the measured naive baseline."""
    provider = TransformerChallengerProvider()
    return provider.run_purged_walk_forward_study(
        dataset=dataset,
        n_splits=3,
        config=config,
        seed=seed,
    )
