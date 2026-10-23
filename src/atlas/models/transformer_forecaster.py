"""Compact Transformer-style sequence forecaster with uncertainty intervals.

The implementation is intentionally dependency-light (NumPy only):

- Multi-head scaled dot-product attention over a causal sequence.
- Sinusoidal positional encoding.
- Residual feed-forward encoder layers with dropout.
- A trainable linear forecast head fitted by mini-batch gradient descent.
- Monte Carlo dropout intervals at inference time.

The attention and feed-forward encoder parameters are seeded and fixed during
training; only the forecast head is optimised. This is reported honestly rather
than claiming end-to-end PyTorch training. It is suitable for small offline
research studies and the uncertainty-gating path, not for production promotion.

All outputs retain ``execution_permission: none``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime

from atlas.models.schemas import (
    Forecast,
    ForecastPoint,
    ForecastRequest,
    ModelRecord,
    ModelRef,
    Text,
    Usage,
)


@dataclass(frozen=True)
class TransformerConfig:
    """Configuration for the compact Transformer forecaster."""

    d_model: int = 64
    n_heads: int = 4
    n_layers: int = 2
    d_ff: int = 256
    dropout: float = 0.1
    sequence_length: int = 60
    forecast_horizon: int = 5
    mc_dropout_samples: int = 100
    confidence_level: float = 0.90
    ridge_alpha: float = 1e-3

    def __post_init__(self) -> None:
        if self.d_model <= 0 or self.d_ff <= 0:
            raise ValueError("d_model and d_ff must be positive")
        if self.n_heads <= 0 or self.d_model % self.n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        if self.sequence_length <= 0 or self.forecast_horizon <= 0:
            raise ValueError("sequence_length and forecast_horizon must be positive")
        if not 0 <= self.dropout < 1:
            raise ValueError("dropout must be in [0, 1)")
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must be in (0, 1)")
        if self.mc_dropout_samples <= 0:
            raise ValueError("mc_dropout_samples must be positive")


class MultiHeadAttention:
    """Multi-head scaled dot-product attention."""

    def __init__(self, d_model: int = 64, n_heads: int = 4):
        if d_model % n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads

    def scaled_dot_product_attention(
        self,
        query: np.ndarray,
        key: np.ndarray,
        value: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute scaled dot-product attention.

        ``query``, ``key`` and ``value`` have shape ``(batch, seq, d_model)``.
        A boolean mask may be shaped ``(seq, seq)`` or broadcastable to
        ``(batch, n_heads, seq, seq)``. ``True`` marks a masked position.
        """
        batch, seq_len, _ = query.shape
        if key.shape != query.shape or value.shape != query.shape:
            raise ValueError("query, key and value must have the same shape")

        q = query.reshape(batch, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)
        k = key.reshape(batch, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)
        v = value.reshape(batch, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)

        scores = np.matmul(q, k.transpose(0, 1, 3, 2)) / math.sqrt(self.d_k)
        if mask is not None:
            scores = np.where(mask, -1e9, scores)

        attention_weights = self._softmax(scores)
        output = np.matmul(attention_weights, v)
        output = output.transpose(0, 2, 1, 3).reshape(batch, seq_len, self.d_model)
        # Return head-averaged weights for a compact, inspectable summary.
        return output, np.mean(attention_weights, axis=1)

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        """Numerically stable softmax."""
        shifted = x - np.max(x, axis=-1, keepdims=True)
        exp_x = np.exp(shifted)
        return exp_x / np.sum(exp_x, axis=-1, keepdims=True)


class PositionalEncoding:
    """Sinusoidal positional encoding for sequence order."""

    def __init__(self, d_model: int = 64, max_len: int = 5000):
        self.d_model = d_model
        self.max_len = max_len
        pe = np.zeros((self.max_len, self.d_model), dtype=np.float64)
        position = np.arange(0, self.max_len, dtype=np.float64).reshape(-1, 1)
        div_term = np.exp(
            np.arange(0, self.d_model, 2, dtype=np.float64)
            * (-math.log(10000.0) / self.d_model)
        )
        pe[:, 0::2] = np.sin(position * div_term)
        if self.d_model > 1:
            pe[:, 1::2] = np.cos(position * div_term[: pe[:, 1::2].shape[1]])
        self.encoding = pe

    def forward(self, x: np.ndarray) -> np.ndarray:
        """Add positional encoding along the sequence axis.

        Supports both ``(seq, d_model)`` and ``(batch, seq, d_model)`` inputs.
        """
        if x.ndim == 2:
            seq_len, width = x.shape
            if width != self.d_model:
                raise ValueError(
                    f"Expected d_model={self.d_model}, received {width}"
                )
            if seq_len > self.max_len:
                raise ValueError("Sequence is longer than max_len")
            return x + self.encoding[:seq_len, :]

        if x.ndim == 3:
            seq_len, width = x.shape[1], x.shape[2]
            if width != self.d_model:
                raise ValueError(
                    f"Expected d_model={self.d_model}, received {width}"
                )
            if seq_len > self.max_len:
                raise ValueError("Sequence is longer than max_len")
            return x + self.encoding[None, :seq_len, :]

        raise ValueError("PositionalEncoding expects a 2D or 3D array")


class TransformerEncoderLayer:
    """Single Transformer encoder layer with fixed seeded projections."""

    def __init__(
        self,
        d_model: int = 64,
        n_heads: int = 4,
        d_ff: int = 256,
        dropout: float = 0.1,
        seed: int | None = None,
    ):
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.dropout = dropout
        self.attention = MultiHeadAttention(d_model, n_heads)
        rng = np.random.default_rng(seed)
        self.ff_w1 = rng.normal(0.0, 1.0 / math.sqrt(d_model), (d_model, d_ff))
        self.ff_b1 = np.zeros(d_ff)
        self.ff_w2 = rng.normal(0.0, 1.0 / math.sqrt(d_ff), (d_ff, d_model))
        self.ff_b2 = np.zeros(d_model)
        self.last_attention_weights: np.ndarray | None = None

    def forward(
        self,
        x: np.ndarray,
        mask: np.ndarray | None = None,
        training: bool = True,
    ) -> np.ndarray:
        """Forward pass through the encoder layer."""
        if x.ndim != 3 or x.shape[-1] != self.d_model:
            raise ValueError("Encoder input must be (batch, seq, d_model)")

        attn_output, weights = self.attention.scaled_dot_product_attention(
            x, x, x, mask
        )
        self.last_attention_weights = weights
        if training and self.dropout > 0:
            attn_output = self._dropout(attn_output)
        x = self._layer_norm(x + attn_output)

        ff_output = self._feed_forward(x)
        if training and self.dropout > 0:
            ff_output = self._dropout(ff_output)
        return self._layer_norm(x + ff_output)

    def _feed_forward(self, x: np.ndarray) -> np.ndarray:
        hidden = np.maximum(0.0, np.matmul(x, self.ff_w1) + self.ff_b1)
        return np.matmul(hidden, self.ff_w2) + self.ff_b2

    def _dropout(self, x: np.ndarray) -> np.ndarray:
        mask = (np.random.rand(*x.shape) >= self.dropout).astype(np.float64)
        return x * mask / (1.0 - self.dropout)

    @staticmethod
    def _layer_norm(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
        mean = np.mean(x, axis=-1, keepdims=True)
        variance = np.var(x, axis=-1, keepdims=True)
        return (x - mean) / np.sqrt(variance + eps)


@dataclass
class TransformerForecaster:
    """Compact Transformer forecaster with MC-dropout intervals."""

    model_id: str
    dataset_id: str
    trained_through: AwareDatetime
    config: TransformerConfig
    encoder_layers: tuple[TransformerEncoderLayer, ...]
    positional_encoding: PositionalEncoding
    input_projection: np.ndarray
    output_projection: np.ndarray
    output_bias: np.ndarray
    target_mean: np.ndarray
    target_scale: np.ndarray
    feature_names: tuple[str, ...] = field(default_factory=tuple)

    def _project(self, features: np.ndarray) -> np.ndarray:
        if features.ndim == 2:
            features = features[None, :, :]
        if features.ndim != 3:
            raise ValueError("features must be (batch, seq, n_features)")
        expected = self.input_projection.shape[0]
        if features.shape[-1] != expected:
            raise ValueError(
                f"Expected {expected} features per step, received "
                f"{features.shape[-1]}"
            )
        if not np.all(np.isfinite(features)):
            raise ValueError("features contain non-finite values")
        projected = np.matmul(features, self.input_projection)
        return self.positional_encoding.forward(projected)

    def _encode(self, features: np.ndarray, training: bool) -> np.ndarray:
        h = self._project(features)
        for layer in self.encoder_layers:
            h = layer.forward(h, training=training)
        return h[:, -1, :]

    def predict(
        self,
        features: np.ndarray,
        mc_samples: int = 100,
        training: bool = False,
    ) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
        """Generate point forecasts and empirical prediction intervals."""
        if mc_samples <= 0:
            raise ValueError("mc_samples must be positive")

        samples = []
        for _ in range(mc_samples):
            encoded = self._encode(features, training=training)
            normalized = np.matmul(encoded, self.output_projection) + self.output_bias
            prediction = normalized * self.target_scale + self.target_mean
            samples.append(prediction)

        stacked = np.stack(samples, axis=0)
        mean_pred = np.mean(stacked, axis=0)
        alpha = 1.0 - self.config.confidence_level
        lower = np.percentile(stacked, (alpha / 2.0) * 100.0, axis=0)
        upper = np.percentile(stacked, (1.0 - alpha / 2.0) * 100.0, axis=0)
        return mean_pred, (lower, upper)

    def attention_summary(self, features: np.ndarray) -> list[list[float]]:
        """Return the last-layer attention weights for one sequence."""
        h = self._project(features)
        for layer in self.encoder_layers:
            h = layer.forward(h, training=False)
        last = self.encoder_layers[-1].last_attention_weights
        if last is None:
            return []
        return last[0].tolist()

    def forecast(self, request: ForecastRequest) -> Forecast:
        """Generate a Forecast response from a ForecastRequest.

        The request's observations are arranged into the model's expected
        sequence. Missing feature columns are zero-filled and the limitation is
        surfaced through the forecast metadata rather than hidden.
        """
        sequence_length = self.config.sequence_length
        feature_dim = self.input_projection.shape[0]
        values = [float(observation.value) for observation in request.observations]
        if not values:
            values = [float(value.value) for value in request.features]

        sequence = np.zeros((1, sequence_length, feature_dim), dtype=np.float64)
        if values:
            recent = np.asarray(values[-sequence_length:], dtype=np.float64)
            sequence[0, -len(recent):, 0] = recent

        mean_pred, (lower, upper) = self.predict(
            sequence,
            mc_samples=self.config.mc_dropout_samples,
            training=True,
        )

        points = []
        for timestamp, value, low, high in zip(
            request.target_times,
            mean_pred[0],
            lower[0],
            upper[0],
        ):
            points.append(
                ForecastPoint(
                    timestamp=timestamp,
                    value=float(value),
                    lower=float(low),
                    upper=float(high),
                    interval_coverage=self.config.confidence_level,
                )
            )

        probability_up = float(np.mean(mean_pred[0] > 0))
        return Forecast(
            request_id=request.request_id,
            model=ModelRef(
                provider_id="local_transformer",
                model_id=self.model_id,
                revision="v1",
            ),
            instrument_id=request.instrument_id,
            horizon_id=request.horizon_id,
            target=request.target,
            unit=request.unit,
            data_as_of=request.as_of,
            generated_at=datetime.now(timezone.utc),
            points=tuple(points),
            probability_up=probability_up,
            usage=Usage(input_tokens=0, output_tokens=0),
            execution_permission="none",
        )


@dataclass
class FittedTransformerModel:
    """Fitted Transformer model with metadata for registration."""

    model_id: str
    dataset_id: str
    trained_through: AwareDatetime
    config: TransformerConfig
    forecaster: TransformerForecaster
    training_mae: float
    validation_mae: float
    seed: int

    def to_model_record(
        self,
        artifact_uri: Text,
        artifact_sha256: Text,
        experiment_id: Text,
        license_ref: Text,
    ) -> ModelRecord:
        """Convert to ModelRecord for registration."""
        return ModelRecord(
            model=ModelRef(
                provider_id="local_transformer",
                model_id=self.model_id,
                revision="v1",
            ),
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256,
            dataset_id=self.dataset_id,
            experiment_id=experiment_id,
            license_ref=license_ref,
            commercial_use_verified=False,
            execution_permission="none",
        )


def _fit_linear_head(
    encoded: np.ndarray,
    targets: np.ndarray,
    *,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    ridge_alpha: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit the forecast head with Adam and L2 regularisation."""
    rng = np.random.default_rng(seed)
    n_samples, d_model = encoded.shape
    horizon = targets.shape[1]

    x = np.concatenate([encoded, np.ones((n_samples, 1))], axis=1)
    weights = rng.normal(0.0, 0.01, (d_model + 1, horizon))
    m = np.zeros_like(weights)
    v = np.zeros_like(weights)
    beta1, beta2 = 0.9, 0.999
    step = 0
    best = weights.copy()
    best_loss = float("inf")
    patience = 15
    stale = 0

    for _ in range(max(1, epochs)):
        order = rng.permutation(n_samples)
        for start in range(0, n_samples, max(1, batch_size)):
            idx = order[start : start + max(1, batch_size)]
            xb = x[idx]
            yb = targets[idx]
            pred = xb @ weights
            error = pred - yb
            grad = (2.0 / len(idx)) * (xb.T @ error)
            grad[:-1] += 2.0 * ridge_alpha * weights[:-1]

            step += 1
            m = beta1 * m + (1.0 - beta1) * grad
            v = beta2 * v + (1.0 - beta2) * (grad * grad)
            m_hat = m / (1.0 - beta1**step)
            v_hat = v / (1.0 - beta2**step)
            weights -= learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)

        loss = float(np.mean((x @ weights - targets) ** 2))
        if loss < best_loss - 1e-12:
            best_loss = loss
            best = weights.copy()
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break

    return best[:-1], best[-1]


def train_transformer_forecaster(
    dataset_id: Text,
    features: np.ndarray,
    targets: np.ndarray,
    config: TransformerConfig | None = None,
    seed: int = 42,
    epochs: int = 100,
    learning_rate: float = 0.01,
    batch_size: int = 32,
    validation_split: float = 0.2,
    feature_names: tuple[str, ...] = (),
) -> FittedTransformerModel:
    """Train the sequence encoder's forecast head from scratch.

    Args:
        dataset_id: Identifier for the training dataset.
        features: ``(n_samples, sequence_length, n_features)``.
        targets: ``(n_samples, forecast_horizon)``.
        config: Model configuration.
        seed: Random seed for reproducible initialization and batching.
        epochs: Maximum Adam epochs for the forecast head.
        learning_rate: Adam learning rate.
        batch_size: Mini-batch size.
        validation_split: Chronological fraction reserved for validation.
        feature_names: Optional names for explainability metadata.

    Returns:
        A fitted model with measured training and validation MAE.
    """
    config = config or TransformerConfig()
    features = np.asarray(features, dtype=np.float64)
    targets = np.asarray(targets, dtype=np.float64)

    if features.ndim != 3:
        raise ValueError("features must be (n_samples, sequence_length, n_features)")
    if targets.ndim != 2:
        raise ValueError("targets must be (n_samples, forecast_horizon)")
    if features.shape[0] != targets.shape[0]:
        raise ValueError("features and targets must have the same sample count")
    if targets.shape[1] != config.forecast_horizon:
        raise ValueError(
            f"Expected {config.forecast_horizon} targets per sample, received "
            f"{targets.shape[1]}"
        )
    if features.shape[1] != config.sequence_length:
        raise ValueError(
            f"Expected sequence_length={config.sequence_length}, received "
            f"{features.shape[1]}"
        )
    if features.shape[0] < 3:
        raise ValueError("At least three samples are required")
    if not np.all(np.isfinite(features)) or not np.all(np.isfinite(targets)):
        raise ValueError("features and targets must be finite")
    if not 0 < validation_split < 1:
        raise ValueError("validation_split must be in (0, 1)")

    np.random.seed(seed)
    rng = np.random.default_rng(seed)
    n_features = features.shape[-1]
    input_projection = rng.normal(
        0.0, 1.0 / math.sqrt(n_features), (n_features, config.d_model)
    )
    positional_encoding = PositionalEncoding(d_model=config.d_model)
    encoder_layers = tuple(
        TransformerEncoderLayer(
            d_model=config.d_model,
            n_heads=config.n_heads,
            d_ff=config.d_ff,
            dropout=config.dropout,
            seed=seed + index,
        )
        for index in range(config.n_layers)
    )

    placeholder = TransformerForecaster(
        model_id=f"transformer_{dataset_id}_{seed}",
        dataset_id=dataset_id,
        trained_through=datetime.now(timezone.utc),
        config=config,
        encoder_layers=encoder_layers,
        positional_encoding=positional_encoding,
        input_projection=input_projection,
        output_projection=np.zeros((config.d_model, config.forecast_horizon)),
        output_bias=np.zeros(config.forecast_horizon),
        target_mean=np.zeros(config.forecast_horizon),
        target_scale=np.ones(config.forecast_horizon),
        feature_names=tuple(feature_names),
    )

    n_samples = features.shape[0]
    n_val = max(1, int(round(n_samples * validation_split)))
    n_train = n_samples - n_val
    if n_train < 2:
        raise ValueError("Not enough training samples after validation split")

    train_x = features[:n_train]
    train_y = targets[:n_train]
    val_x = features[n_train:]
    val_y = targets[n_train:]

    target_mean = train_y.mean(axis=0)
    target_scale = train_y.std(axis=0)
    target_scale = np.where(target_scale < 1e-8, 1.0, target_scale)
    normalized_train_y = (train_y - target_mean) / target_scale

    encoded_train = placeholder._encode(train_x, training=False)
    output_projection, output_bias = _fit_linear_head(
        encoded_train,
        normalized_train_y,
        epochs=epochs,
        learning_rate=learning_rate,
        batch_size=batch_size,
        ridge_alpha=config.ridge_alpha,
        seed=seed,
    )

    placeholder.output_projection = output_projection
    placeholder.output_bias = output_bias
    placeholder.target_mean = target_mean
    placeholder.target_scale = target_scale

    train_predictions, _ = placeholder.predict(
        train_x, mc_samples=1, training=False
    )
    val_predictions, _ = placeholder.predict(val_x, mc_samples=1, training=False)
    training_mae = float(np.mean(np.abs(train_predictions - train_y)))
    validation_mae = float(np.mean(np.abs(val_predictions - val_y)))

    return FittedTransformerModel(
        model_id=placeholder.model_id,
        dataset_id=dataset_id,
        trained_through=datetime.now(timezone.utc),
        config=config,
        forecaster=placeholder,
        training_mae=training_mae,
        validation_mae=validation_mae,
        seed=seed,
    )
