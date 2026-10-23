"""ML Training Orchestrator for the Price Action Classifier.

Handles the pipeline of retrieving recorded opportunities from the 
OpportunityLedger, preparing the feature matrix, and training 
the XGBoost classifier.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import logging

from atlas.models.strategy_classifier import StrategyClassifier
from atlas.research.ledger import OpportunityLedger
from atlas.features.pa_integration import PriceActionFeatureExtractor
from atlas.features.zones import ZoneEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PA-Trainer")

class PATrainer:
    """
    Orchestrates the training of the StrategyClassifier using live data 
    collected in the OpportunityLedger.
    """

    def __init__(
        self, 
        ledger: OpportunityLedger, 
        extractor: PriceActionFeatureExtractor,
        model_save_path: str = "var/models/pa_classifier_v1.bin"
    ):
        self.ledger = ledger
        self.extractor = extractor
        self.model_save_path = Path(model_save_path)

    def prepare_training_set(self, historical_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """
        Transforms ledger records into a feature matrix (X) and labels (y).
        """
        ledgers = self.ledger.get_training_set()
        if ledgers.empty:
            raise ValueError("No closed setups found in ledger to train on.")

        X_list = []
        y_list = []

        for _, row in ledgers.iterrows():
            # Reconstruct the state at the time of detection
            # In a production system, we would query the FeatureStore for the exact PIT state
            # For this implementation, we use the captured structural features from the ledger
            
            # Mocking feature extraction for the historical record
            # In reality, we would pull the exact OHLC window from the laakehouse
            features = {
                "zone_overlap_count": row.get("metadata_overlap", 1),
                "setup_duration_sec": row.get("duration", 3600),
                "snapback_state": 3, # All ledger entries are qualified (state 3)
                "snapback_direction": 1 if row["symbol"].startswith("BTC") else -1,
            }
            
            X_list.append(features)
            # Label: 1 if win, 0 if loss/expired
            y_list.append(1 if row["outcome"] == "win" else 0)

        return pd.DataFrame(X_list), pd.Series(y_list)

    def train_and_save(self) -> str:
        """
        Executes the training loop and persists the model.
        """
        logger.info("Starting Price Action Classifier training...")
        
        try:
            # 1. Get data
            # Note: In a real environment, we'd pass the actual historical OHLC data here
            # For the current setup, we use the labels stored in the ledger
            X, y = self.prepare_training_set(pd.DataFrame()) 
            
            # 2. Train model
            classifier = StrategyClassifier()
            classifier.train(X, y)
            
            # 3. Persist
            self.model_save_path.parent.mkdir(parents=True, exist_ok=True)
            classifier.model.save_model(str(self.model_save_path))
            
            logger.info(f"Model successfully trained and saved to {self.model_save_path}")
            return str(self.model_save_path)
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            raise e
