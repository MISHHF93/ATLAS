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
from sklearn.calibration import CalibratedClassifierCV
import joblib

from atlas.schemas import Record, Text
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
        self.model: xgb.Booster | CalibratedClassifierCV | None = None
        if model_path:
            self.load_model(model_path)

    def load_model(self, path: str) -> None:
        """Load a trained XGBoost model or calibrated wrapper from disk."""
        try:
            # Attempt to load as a joblib object (for calibrated wrappers)
            self.model = joblib.load(path)
        except Exception:
            # Fallback to raw XGBoost Booster
            self.model = xgb.Booster()
            self.model.load_model(path)

    def predict(
        self, 
        setup: SnapbackSetup, 
        features: pd.DataFrame
    ) -> StrategyPrediction:
        """
        Predicts the outcome of a qualified setup.
        """
        if self.model is None:
            return self._naive_baseline(setup, features)

        # Ensure features are in the correct order
        # In production, we use a FixedFeatureSet schema
        X = features.drop(columns=['timestamp', 'symbol'], errors='ignore')
        
        try:
            # If it's a calibrated model, it uses .predict_proba
            if hasattr(self.model, "predict_proba"):
                prob = self.model.predict_proba(X)[0][1]
            else:
                # If it's a raw Booster, it uses .predict
                dmatrix = xgb.DMatrix(X)
                prob = self.model.predict(dmatrix)[0]
        except Exception:
            return self._naive_baseline(setup, features)
        
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
