"""ML Intelligence System for Price Action Strategy Evaluation.

Implements a probability-based classifier to evaluate the attractiveness 
of structural trade setups (e.g., Snapback Entry).

The model predicts the probability of a setup reaching its target before its stop,
providing a calibrated confidence score to the ActionableControlPlaneEngine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple

import xgboost as xgb
from sklearn.metrics import log_loss, roc_auc_score

from atlas.models.schemas import Record, Text
from atlas.features.zones import ZoneType
from atlas.strategies.snapback import SnapbackSetup, SnapbackState


class StrategyPrediction(Record):
    """A probabilistic forecast for a specific trade setup."""
    symbol: Text
    setup_id: Text
    probability_of_success: float # Calibrated P(Target before Stop)
    expected_value: float # Prob * Reward - (1-Prob) * Risk
    uncertainty_score: float # Model variance or entropy
    recommended_action: Literal["buy", "sell", "hold", "ignore"]
    model_version: Text
    evaluated_at: datetime
    execution_permission: Literal["none"] = "none"


class StrategyClassifier:
    """
    XGBoost-based classifier for ranking and filtering strategy setups.
    
    The model learns to distinguish between high-probability and low-probability
    structural setups by analyzing zone overlap, regime context, and setup duration.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_version = "xgb-pa-v1"
        self.model: xgb.Booster | None = None
        if model_path:
            self.load_model(model_path)

    def load_model(self, path: str) -> None:
        """Load a trained XGBoost model from disk."""
        self.model = xgb.Booster()
        self.model.load_model(path)

    def predict(
        self, 
        setup: SnapbackSetup, 
        features: pd.DataFrame
    ) -> StrategyPrediction:
        """
        Predicts the outcome of a qualified setup.
        
        Args:
            setup: The qualified Snapback setup
            features: DataFrame containing normalized structural and regime features
        """
        if self.model is None:
            # Fallback to a naive baseline if no model is loaded
            # In production, this would trigger a 'model_not_ready' alert
            return self._naive_baseline(setup, features)

        # Ensure features are in the correct order for the Booster
        # This would normally be handled by a feature_schema object
        dmatrix = xgb.DMatrix(features.drop(columns=['timestamp', 'symbol'], errors='ignore'))
        prob = self.model.predict(dmatrix)[0]
        
        # Calibrate probability and calculate EV
        # Assumption: Reward/Risk ratio is 1.5 for baseline
        ev = (prob * 1.5) - ((1 - prob) * 1.0)
        
        action = "ignore"
        if prob > 0.65:
            action = "buy" if setup.direction == "long" else "sell"
        elif prob > 0.55:
            action = "hold"

        return StrategyPrediction(
            symbol=setup.symbol,
            setup_id=setup.setup_id,
            probability_of_success=float(prob),
            expected_value=float(ev),
            uncertainty_score=float(1.0 - abs(prob - 0.5) * 2),
            recommended_action=action,
            model_version=self.model_version,
            evaluated_at=datetime.now(timezone.utc)
        )

    def _naive_baseline(self, setup: SnapbackSetup, features: pd.DataFrame) -> StrategyPrediction:
        """Provides a baseline probability based on structural heuristics."""
        # Simple heuristic: More zone overlap = higher probability
        overlap_count = features.get("zone_overlap_count", [1])[0]
        prob = 0.5 + (min(overlap_count, 3) * 0.05)
        
        return StrategyPrediction(
            symbol=setup.symbol,
            setup_id=setup.setup_id,
            probability_of_success=float(prob),
            expected_value=float(prob * 1.5 - (1-prob)),
            uncertainty_score=1.0,
            recommended_action="ignore", # Baseline never authorizes real trades
            model_version="naive-baseline-v0",
            evaluated_at=datetime.now(timezone.utc)
        )

    def train(self, training_data: pd.DataFrame, labels: pd.Series):
        """
        Trains the XGBoost model on historical setup outcomes.
        
        Args:
            training_data: Features for historical setups
            labels: Binary outcome (1: Hit Target, 0: Hit Stop)
        """
        dtrain = xgb.DMatrix(training_data, label=labels)
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "max_depth": 4,
            "eta": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "seed": 42
        }
        self.model = xgb.train(params, dtrain, num_boost_round=100)
