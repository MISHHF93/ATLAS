"""Unit tests for Transformer forecaster."""

import pytest
import numpy as np
from datetime import datetime, timedelta, timezone

from atlas.models.transformer_forecaster import (
    MultiHeadAttention,
    PositionalEncoding,
    TransformerEncoderLayer,
    TransformerConfig,
    TransformerForecaster,
    train_transformer_forecaster,
)


def test_multi_head_attention():
    """Test multi-head attention mechanism."""
    d_model = 64
    n_heads = 4
    attention = MultiHeadAttention(d_model, n_heads)
    
    # Create dummy inputs
    batch_size = 2
    seq_len = 10
    query = np.random.randn(batch_size, seq_len, d_model)
    key = np.random.randn(batch_size, seq_len, d_model)
    value = np.random.randn(batch_size, seq_len, d_model)
    
    # Compute attention
    output, weights = attention.scaled_dot_product_attention(query, key, value)
    
    assert output.shape == (batch_size, seq_len, d_model)
    assert weights.shape == (batch_size, seq_len, seq_len)
    assert np.all(np.isfinite(output))


def test_positional_encoding():
    """Test positional encoding."""
    d_model = 64
    pe = PositionalEncoding(d_model)
    
    # Test encoding shape
    assert pe.encoding.shape == (pe.max_len, d_model)
    
    # Test forward pass
    x = np.random.randn(10, d_model)
    output = pe.forward(x)
    
    assert output.shape == x.shape
    assert not np.allclose(output, x)  # Should be different


def test_transformer_encoder_layer():
    """Test transformer encoder layer."""
    d_model = 64
    n_heads = 4
    d_ff = 256
    dropout = 0.1
    
    layer = TransformerEncoderLayer(d_model, n_heads, d_ff, dropout)
    
    # Create dummy input
    batch_size = 2
    seq_len = 10
    x = np.random.randn(batch_size, seq_len, d_model)
    
    # Forward pass
    output = layer.forward(x, training=True)
    
    assert output.shape == x.shape
    assert np.all(np.isfinite(output))


def test_transformer_config():
    """Test transformer configuration."""
    config = TransformerConfig(
        d_model=128,
        n_heads=8,
        n_layers=4,
        d_ff=512,
        dropout=0.2,
    )
    
    assert config.d_model == 128
    assert config.n_heads == 8
    assert config.mc_dropout_samples == 100


def test_train_transformer_forecaster():
    """Test training a transformer forecaster."""
    config = TransformerConfig(d_model=32, n_heads=2, n_layers=1)
    
    # Create dummy data
    features = np.random.randn(100, 60, 10)
    targets = np.random.randn(100, 5)
    
    model = train_transformer_forecaster(
        dataset_id="test_dataset",
        features=features,
        targets=targets,
        config=config,
        seed=42,
    )
    
    assert model.model_id is not None
    assert model.dataset_id == "test_dataset"
    assert model.config.d_model == 32
    assert model.seed == 42


def test_transformer_prediction():
    """Test transformer prediction with uncertainty."""
    config = TransformerConfig(d_model=32, n_heads=2, n_layers=1)
    
    features = np.random.randn(100, 60, 10)
    targets = np.random.randn(100, 5)
    
    model = train_transformer_forecaster(
        dataset_id="test_dataset",
        features=features,
        targets=targets,
        config=config,
        seed=42,
    )
    
    # Test prediction
    test_features = np.random.randn(1, 60, 10)
    mean_pred, (lower, upper) = model.forecaster.predict(
        test_features,
        mc_samples=10,
        training=True,
    )
    
    assert mean_pred.shape[0] == 1
    assert lower.shape == mean_pred.shape
    assert upper.shape == mean_pred.shape
    assert np.all(lower <= mean_pred)
    assert np.all(mean_pred <= upper)


def test_transformer_forecast_request():
    """Test generating forecast from request."""
    from atlas.models.schemas import ForecastRequest, Observation, FeatureValue
    
    config = TransformerConfig(d_model=32, n_heads=2, n_layers=1)
    features = np.random.randn(100, 60, 10)
    targets = np.random.randn(100, 5)
    
    model = train_transformer_forecaster(
        dataset_id="test_dataset",
        features=features,
        targets=targets,
        config=config,
        seed=42,
    )
    
    # Create forecast request
    now = datetime.now(timezone.utc)
    request = ForecastRequest(
        request_id="test_request",
        instrument_id="test_instrument",
        horizon_id="test_horizon",
        as_of=now,
        target="price",
        unit="usd",
        observations=(
            Observation(event_time=now, available_at=now, value=100.0),
        ),
        features=(
            FeatureValue(
                name="feature1",
                source="test",
                event_time=now,
                available_at=now,
                value=1.0,
                lineage_ref="test",
                license_ref="test",
            ),
        ),
        target_times=(now + timedelta(hours=1),),
        dataset_id="test_dataset",
        data_license_ref="test",
    )
    
    # Generate forecast
    forecast = model.forecaster.forecast(request)
    
    assert forecast.request_id == "test_request"
    assert forecast.execution_permission == "none"
    assert len(forecast.points) > 0
    assert forecast.points[0].lower is not None
    assert forecast.points[0].upper is not None
