"""Uncertainty-aware risk gating for position sizing and trade authorization.

Implements:
- Uncertainty-based position sizing adjustment
- Interval width-based risk scaling
- Confidence-aware trade filtering
- Integration with existing control plane rules
- Risk budget adjustment based on prediction uncertainty

All outputs retain execution_permission: none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, Field

from atlas.schemas import Probability, Record, Text


@dataclass(frozen=True)
class UncertaintyGatingConfig:
    """Configuration for uncertainty-aware risk gating."""
    
    max_position_scale: float = 1.0  # Maximum position scaling factor
    min_position_scale: float = 0.1  # Minimum position scaling factor
    interval_width_threshold: float = 0.05  # 5% price threshold for full reduction
    confidence_threshold: float = 0.70  # Minimum confidence for trade consideration
    uncertainty_penalty_factor: float = 2.0  # Penalty factor for high uncertainty
    enable_interval_filtering: bool = True
    enable_confidence_filtering: bool = True


class UncertaintyRiskAdjustment(Record):
    """Risk adjustment based on prediction uncertainty."""
    
    adjustment_id: Text
    model_id: Text
    instrument_id: Text
    original_position_size: float
    adjusted_position_size: float
    scaling_factor: float
    interval_width: float
    confidence: float
    uncertainty_level: Literal["low", "medium", "high", "extreme"]
    reason: Text
    timestamp: AwareDatetime
    execution_permission: Literal["none"] = "none"


class UncertaintyGateDecision(Record):
    """Decision from uncertainty gating."""
    
    decision_id: Text
    model_id: Text
    instrument_id: Text
    trade_allowed: bool
    position_scale: float
    confidence: float
    interval_width: float
    uncertainty_level: Literal["low", "medium", "high", "extreme"]
    rejection_reason: Text | None
    timestamp: AwareDatetime
    execution_permission: Literal["none"] = "none"


class UncertaintyAwareGating(Record):
    """Uncertainty-aware risk gating system."""
    
    gate_id: Text
    config: UncertaintyGatingConfig
    
    def compute_interval_width(
        self,
        lower: float,
        upper: float,
        price: float,
    ) -> float:
        """Compute normalized interval width.
        
        Args:
            lower: Lower prediction bound
            upper: Upper prediction bound
            price: Current price
        
        Returns:
            Normalized interval width as percentage of price
        """
        if price <= 0:
            raise ValueError("Price must be positive")
        width = (upper - lower) / price
        return max(0.0, width)
    
    def classify_uncertainty(
        self,
        interval_width: float,
        confidence: float,
    ) -> Literal["low", "medium", "high", "extreme"]:
        """Classify uncertainty level.
        
        Args:
            interval_width: Normalized interval width
            confidence: Prediction confidence
        
        Returns:
            Uncertainty level classification
        """
        # High interval width or low confidence = high uncertainty
        if interval_width > 0.15 or confidence < 0.50:
            return "extreme"
        elif interval_width > 0.10 or confidence < 0.60:
            return "high"
        elif interval_width > 0.05 or confidence < 0.70:
            return "medium"
        else:
            return "low"
    
    def compute_position_scale(
        self,
        interval_width: float,
        confidence: float,
        uncertainty_level: Literal["low", "medium", "high", "extreme"],
    ) -> float:
        """Compute position scaling factor based on uncertainty.
        
        Args:
            interval_width: Normalized interval width
            confidence: Prediction confidence
            uncertainty_level: Classified uncertainty level
        
        Returns:
            Position scaling factor [0, 1]
        """
        # Confidence sets the base size. A low-uncertainty interval does not
        # receive an additional width penalty; wider or more uncertain
        # intervals are reduced progressively and then clamped.
        width_penalty = min(
            1.0,
            interval_width / self.config.interval_width_threshold
            if self.config.interval_width_threshold > 0
            else 1.0,
        )
        level_width_penalties = {
            "low": 1.0,
            "medium": 1.0 - min(0.75, width_penalty * 0.5),
            "high": 1.0 - min(0.90, width_penalty * 0.75),
            "extreme": 1.0 - min(0.95, width_penalty * 0.9),
        }
        level_adjustments = {
            "low": 1.0,
            "medium": 0.75,
            "high": 0.5,
            "extreme": 0.25,
        }
        combined_scale = (
            confidence
            * level_width_penalties[uncertainty_level]
            * level_adjustments[uncertainty_level]
        )
        
        # Clamp to configured bounds
        scale = max(
            self.config.min_position_scale,
            min(self.config.max_position_scale, combined_scale)
        )
        
        return float(scale)
    
    def evaluate_trade(
        self,
        model_id: str,
        instrument_id: str,
        prediction: float,
        lower: float | None,
        upper: float | None,
        confidence: float,
        current_price: float,
        proposed_position: float,
    ) -> UncertaintyGateDecision:
        """Evaluate a trade proposal with uncertainty gating.
        
        Args:
            model_id: Model identifier
            instrument_id: Instrument identifier
            prediction: Point prediction
            lower: Lower prediction bound
            upper: Upper prediction bound
            confidence: Prediction confidence
            current_price: Current market price
            proposed_position Proposed position size
        
        Returns:
            Uncertainty gate decision
        """
        # Compute interval width if bounds provided
        interval_width = 0.0
        if lower is not None and upper is not None:
            interval_width = self.compute_interval_width(lower, upper, current_price)
        
        # Classify uncertainty
        uncertainty_level = self.classify_uncertainty(interval_width, confidence)
        
        # Check confidence filtering
        rejection_reason = None
        if self.config.enable_confidence_filtering and confidence < self.config.confidence_threshold:
            rejection_reason = f"Confidence {confidence:.2f} below threshold {self.config.confidence_threshold}"
        
        # Check interval filtering. The configured threshold is the maximum
        # tolerated interval width, not a level that must be exceeded threefold.
        if (
            self.config.enable_interval_filtering
            and interval_width > self.config.interval_width_threshold
        ):
            rejection_reason = (
                f"Interval width {interval_width:.2%} exceeds threshold "
                f"{self.config.interval_width_threshold:.2%}"
            )
        
        # Compute position scale
        position_scale = self.compute_position_scale(
            interval_width, confidence, uncertainty_level
        )
        
        # Determine if trade allowed
        trade_allowed = rejection_reason is None
        
        return UncertaintyGateDecision(
            decision_id=f"gate_{model_id}_{datetime.now(timezone.utc).isoformat()}",
            model_id=model_id,
            instrument_id=instrument_id,
            trade_allowed=trade_allowed,
            position_scale=position_scale,
            confidence=confidence,
            interval_width=interval_width,
            uncertainty_level=uncertainty_level,
            rejection_reason=rejection_reason,
            timestamp=datetime.now(timezone.utc),
        )
    
    def adjust_position(
        self,
        model_id: str,
        instrument_id: str,
        original_position: float,
        prediction: float,
        lower: float | None,
        upper: float | None,
        confidence: float,
        current_price: float,
    ) -> UncertaintyRiskAdjustment:
        """Adjust position size based on uncertainty.
        
        Args:
            model_id: Model identifier
            instrument_id: Instrument identifier
            original_position: Original proposed position size
            prediction: Point prediction
            lower: Lower prediction bound
            upper: Upper prediction bound
            confidence: Prediction confidence
            current_price: Current market price
        
        Returns:
            Risk adjustment record
        """
        # Compute interval width
        interval_width = 0.0
        if lower is not None and upper is not None:
            interval_width = self.compute_interval_width(lower, upper, current_price)
        
        # Classify uncertainty
        uncertainty_level = self.classify_uncertainty(interval_width, confidence)
        
        # Compute scaling factor
        scaling_factor = self.compute_position_scale(
            interval_width, confidence, uncertainty_level
        )
        
        # Adjust position
        adjusted_position = original_position * scaling_factor
        
        # Generate reason
        reasons = {
            "low": "Low uncertainty - full position allowed",
            "medium": "Medium uncertainty - position scaled",
            "high": "High uncertainty - position significantly reduced",
            "extreme": "Extreme uncertainty - position minimized",
        }
        reason = reasons[uncertainty_level]
        
        return UncertaintyRiskAdjustment(
            adjustment_id=f"adjust_{model_id}_{datetime.now(timezone.utc).isoformat()}",
            model_id=model_id,
            instrument_id=instrument_id,
            original_position_size=original_position,
            adjusted_position_size=adjusted_position,
            scaling_factor=scaling_factor,
            interval_width=interval_width,
            confidence=confidence,
            uncertainty_level=uncertainty_level,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
        )
    
    def batch_evaluate_trades(
        self,
        trade_proposals: list[dict],
    ) -> list[UncertaintyGateDecision]:
        """Evaluate multiple trade proposals.
        
        Args:
            trade_proposals: List of trade proposal dictionaries
        
        Returns:
            List of gate decisions
        """
        decisions = []
        
        for proposal in trade_proposals:
            decision = self.evaluate_trade(
                model_id=proposal["model_id"],
                instrument_id=proposal["instrument_id"],
                prediction=proposal["prediction"],
                lower=proposal.get("lower"),
                upper=proposal.get("upper"),
                confidence=proposal["confidence"],
                current_price=proposal["current_price"],
                proposed_position=proposal["proposed_position"],
            )
            decisions.append(decision)
        
        return decisions


class UncertaintyRiskBudget(Record):
    """Risk budget adjustment based on aggregate uncertainty."""
    
    budget_id: Text
    total_risk_budget: float
    allocated_risk: float
    remaining_risk: float
    uncertainty_adjustment: float
    effective_risk_budget: float
    timestamp: AwareDatetime
    execution_permission: Literal["none"] = "none"


class UncertaintyBudgetManager(Record):
    """Manager for uncertainty-aware risk budgeting."""
    
    manager_id: Text
    gating: UncertaintyAwareGating
    base_risk_budget: float
    
    def compute_aggregate_uncertainty(
        self,
        decisions: list[UncertaintyGateDecision],
    ) -> float:
        """Compute aggregate uncertainty across all decisions.
        
        Args:
            decisions: List of gate decisions
        
        Returns:
            Aggregate uncertainty score [0, 1]
        """
        if not decisions:
            return 0.0
        
        # Weight uncertainty by position scale
        weights = [d.position_scale for d in decisions]
        total_weight = sum(weights)
        
        if total_weight == 0:
            return 1.0
        
        # Map uncertainty levels to scores
        level_scores = {
            "low": 0.0,
            "medium": 0.33,
            "high": 0.67,
            "extreme": 1.0,
        }
        
        weighted_uncertainty = sum(
            weights[i] * level_scores[d.uncertainty_level]
            for i, d in enumerate(decisions)
        )
        
        return weighted_uncertainty / total_weight
    
    def adjust_risk_budget(
        self,
        decisions: list[UncertaintyGateDecision],
    ) -> UncertaintyRiskBudget:
        """Adjust risk budget based on aggregate uncertainty.
        
        Args:
            decisions: List of gate decisions
        
        Returns:
            Adjusted risk budget
        """
        aggregate_uncertainty = self.compute_aggregate_uncertainty(decisions)
        
        # Reduce budget based on uncertainty
        uncertainty_adjustment = 1.0 - (aggregate_uncertainty * 0.5)
        effective_budget = self.base_risk_budget * uncertainty_adjustment
        
        # Compute allocated risk from allowed trades
        allocated_risk = sum(
            d.position_scale for d in decisions if d.trade_allowed
        ) / max(1, len(decisions))
        
        remaining_risk = effective_budget - allocated_risk
        
        return UncertaintyRiskBudget(
            budget_id=f"budget_{datetime.now(timezone.utc).isoformat()}",
            total_risk_budget=self.base_risk_budget,
            allocated_risk=allocated_risk,
            remaining_risk=max(0.0, remaining_risk),
            uncertainty_adjustment=uncertainty_adjustment,
            effective_risk_budget=effective_budget,
            timestamp=datetime.now(timezone.utc),
        )


def create_uncertainty_gating(
    gate_id: str,
    config: UncertaintyGatingConfig | None = None,
) -> UncertaintyAwareGating:
    """Create an uncertainty-aware gating system.
    
    Args:
        gate_id: Gate identifier
        config: Gating configuration
    
    Returns:
        Configured UncertaintyAwareGating
    """
    if config is None:
        config = UncertaintyGatingConfig()
    
    return UncertaintyAwareGating(gate_id=gate_id, config=config)


def create_budget_manager(
    manager_id: str,
    gating: UncertaintyAwareGating,
    base_risk_budget: float,
) -> UncertaintyBudgetManager:
    """Create an uncertainty-aware budget manager.
    
    Args:
        manager_id: Manager identifier
        gating: Uncertainty gating system
        base_risk_budget: Base risk budget
    
    Returns:
        Configured UncertaintyBudgetManager
    """
    return UncertaintyBudgetManager(
        manager_id=manager_id,
        gating=gating,
        base_risk_budget=base_risk_budget,
    )
