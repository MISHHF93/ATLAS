"""Unit tests for uncertainty gating."""

import pytest
from datetime import datetime, timezone

from atlas.control.uncertainty_gating import (
    UncertaintyAwareGating,
    UncertaintyGatingConfig,
    UncertaintyGateDecision,
    UncertaintyRiskAdjustment,
    UncertaintyBudgetManager,
    create_uncertainty_gating,
    create_budget_manager,
)


def test_uncertainty_gating_config():
    """Test uncertainty gating configuration."""
    config = UncertaintyGatingConfig(
        max_position_scale=0.8,
        min_position_scale=0.2,
        interval_width_threshold=0.08,
        confidence_threshold=0.75,
    )
    
    assert config.max_position_scale == 0.8
    assert config.min_position_scale == 0.2
    assert config.interval_width_threshold == 0.08


def test_compute_interval_width():
    """Test interval width computation."""
    gating = create_uncertainty_gating("test")
    
    width = gating.compute_interval_width(lower=95.0, upper=105.0, price=100.0)
    
    assert width == 0.10  # (105 - 95) / 100


def test_classify_uncertainty():
    """Test uncertainty classification."""
    gating = create_uncertainty_gating("test")
    
    # Low uncertainty
    level = gating.classify_uncertainty(interval_width=0.02, confidence=0.85)
    assert level == "low"
    
    # Medium uncertainty
    level = gating.classify_uncertainty(interval_width=0.06, confidence=0.65)
    assert level == "medium"
    
    # High uncertainty
    level = gating.classify_uncertainty(interval_width=0.12, confidence=0.55)
    assert level == "high"
    
    # Extreme uncertainty
    level = gating.classify_uncertainty(interval_width=0.20, confidence=0.40)
    assert level == "extreme"


def test_compute_position_scale():
    """Test position scale computation."""
    gating = create_uncertainty_gating("test")
    
    # Low uncertainty should give high scale
    scale = gating.compute_position_scale(
        interval_width=0.02,
        confidence=0.85,
        uncertainty_level="low",
    )
    assert scale > 0.8
    
    # High uncertainty should give low scale
    scale = gating.compute_position_scale(
        interval_width=0.15,
        confidence=0.50,
        uncertainty_level="high",
    )
    assert scale < 0.6


def test_evaluate_trade_allowed():
    """Test trade evaluation when trade is allowed."""
    gating = create_uncertainty_gating("test")
    
    decision = gating.evaluate_trade(
        model_id="test_model",
        instrument_id="BTC-USD",
        prediction=68000.0,
        lower=67500.0,
        upper=68500.0,
        confidence=0.80,
        current_price=68000.0,
        proposed_position=10000.0,
    )
    
    assert decision.trade_allowed == True
    assert decision.rejection_reason is None
    assert decision.confidence == 0.80
    assert decision.uncertainty_level == "low"


def test_evaluate_trade_rejected_confidence():
    """Test trade rejection due to low confidence."""
    config = UncertaintyGatingConfig(confidence_threshold=0.70)
    gating = create_uncertainty_gating("test", config)
    
    decision = gating.evaluate_trade(
        model_id="test_model",
        instrument_id="BTC-USD",
        prediction=68000.0,
        lower=67000.0,
        upper=69000.0,
        confidence=0.55,  # Below threshold
        current_price=68000.0,
        proposed_position=10000.0,
    )
    
    assert decision.trade_allowed == False
    assert "confidence" in decision.rejection_reason.lower()


def test_evaluate_trade_rejected_interval():
    """Test trade rejection due to wide interval."""
    config = UncertaintyGatingConfig(interval_width_threshold=0.05)
    gating = create_uncertainty_gating("test", config)
    
    decision = gating.evaluate_trade(
        model_id="test_model",
        instrument_id="BTC-USD",
        prediction=68000.0,
        lower=65000.0,  # Very wide interval
        upper=71000.0,
        confidence=0.75,
        current_price=68000.0,
        proposed_position=10000.0,
    )
    
    assert decision.trade_allowed == False
    assert "interval" in decision.rejection_reason.lower()


def test_adjust_position():
    """Test position adjustment based on uncertainty."""
    gating = create_uncertainty_gating("test")
    
    adjustment = gating.adjust_position(
        model_id="test_model",
        instrument_id="BTC-USD",
        original_position=10000.0,
        prediction=68000.0,
        lower=67500.0,
        upper=68500.0,
        confidence=0.80,
        current_price=68000.0,
    )
    
    assert adjustment.original_position_size == 10000.0
    assert adjustment.adjusted_position_size <= adjustment.original_position_size
    assert adjustment.scaling_factor > 0
    assert adjustment.scaling_factor <= 1.0


def test_batch_evaluate_trades():
    """Test batch evaluation of multiple trades."""
    gating = create_uncertainty_gating("test")
    
    proposals = [
        {
            "model_id": "test_model",
            "instrument_id": "BTC-USD",
            "prediction": 68000.0,
            "lower": 67500.0,
            "upper": 68500.0,
            "confidence": 0.80,
            "current_price": 68000.0,
            "proposed_position": 10000.0,
        },
        {
            "model_id": "test_model",
            "instrument_id": "ETH-USD",
            "prediction": 2650.0,
            "lower": 2600.0,
            "upper": 2700.0,
            "confidence": 0.75,
            "current_price": 2650.0,
            "proposed_position": 5000.0,
        },
    ]
    
    decisions = gating.batch_evaluate_trades(proposals)
    
    assert len(decisions) == 2
    assert all(isinstance(d, UncertaintyGateDecision) for d in decisions)


def test_uncertainty_budget_manager():
    """Test uncertainty-aware budget manager."""
    gating = create_uncertainty_gating("test")
    manager = create_budget_manager("test_budget", gating, base_risk_budget=0.02)
    
    # Create some decisions
    decisions = [
        UncertaintyGateDecision(
            decision_id="d1",
            model_id="test_model",
            instrument_id="BTC-USD",
            trade_allowed=True,
            position_scale=0.8,
            confidence=0.80,
            interval_width=0.03,
            uncertainty_level="low",
            rejection_reason=None,
            timestamp=datetime.now(timezone.utc),
        ),
        UncertaintyGateDecision(
            decision_id="d2",
            model_id="test_model",
            instrument_id="ETH-USD",
            trade_allowed=True,
            position_scale=0.5,
            confidence=0.60,
            interval_width=0.08,
            uncertainty_level="medium",
            rejection_reason=None,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    
    budget = manager.adjust_risk_budget(decisions)
    
    assert budget.total_risk_budget == 0.02
    assert budget.effective_risk_budget <= budget.total_risk_budget
    assert budget.remaining_risk >= 0
