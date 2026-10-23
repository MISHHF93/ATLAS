"""Market Memory Retrieval and Analogous Case-Based Reasoning (CBR) for ATLAS.

This system allows the ML brain to move beyond simple parametric predictions
by retrieving the most similar historical setups from the OpportunityLedger.

By analyzing the outcomes of 'analogue' cases, ATLAS can adjust its probability
forecasts based on empirical evidence from the past.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

from atlas.research.ledger import OpportunityLedger
from atlas.models.schemas import Record, Text


@dataclass(frozen=True)
class MarketAnalogue(Record):
    """A historical analogue to the current market state."""
    setup_id: Text
    symbol: Text
    timestamp: datetime
    similarity_score: float # Cosine similarity [0, 1]
    outcome: str # 'win', 'loss', 'expired'
    pnl_bps: float
    features: dict[str, Any]
    execution_permission: Literal["none"] = "none"


class MarketMemoryEngine:
    """
    Implements non-parametric memory retrieval using k-Nearest Neighbors (k-NN).
    
    It transforms the current structural state into a vector and searches the 
    OpportunityLedger for the most similar historical occurrences.
    """

    def __init__(self, ledger: OpportunityLedger):
        self.ledger = ledger
        # The 'Structural Fingerprint' - features used for similarity matching
        self.fingerprint_features = [
            "zone_overlap_count", 
            "vpin", 
            "ofi", 
            "kyles_lambda", 
            "regime",
            "rvol",
            "vol_compression"
        ]

    def find_analogues(
        self, 
        current_features: pd.DataFrame, 
        k: int = 5
    ) -> List[MarketAnalogue]:
        """
        Retrieves the k most similar historical setups.
        """
        # 1. Fetch historical closed setups from the ledger
        historical_df = self.ledger.get_training_set()
        if historical_df.empty:
            return []

        # 2. Align feature space
        # Use intersection of defined fingerprint and available ledger columns
        available_features = [f for f in self.fingerprint_features if f in historical_df.columns]
        if not available_features:
            return []

        # 3. Vectorization and Z-Score Normalization
        # Normalize to prevent high-magnitude features (like volume) from dominating
        hist_vecs = historical_df[available_features].values.astype(float)
        mean = np.mean(hist_vecs, axis=0)
        std = np.std(hist_vecs, axis=0) + 1e-9
        norm_hist_vecs = (hist_vecs - mean) / std

        # Current state vector
        curr_vec = current_features[available_features].values[0].astype(float)
        norm_curr_vec = (curr_vec - mean) / std

        # 4. Cosine Similarity Calculation
        # similarity = (A . B) / (||A|| * ||B||)
        dot_product = np.dot(norm_hist_vecs, norm_curr_vec)
        norm_hist = np.linalg.norm(norm_hist_vecs, axis=1)
        norm_curr = np.linalg.norm(norm_curr_vec)
        
        similarities = dot_product / (norm_hist * norm_curr + 1e-9)
        
        # 5. Retrieve top-k indices
        top_indices = np.argsort(similarities)[::-1][:k]
        
        analogues = []
        for idx in top_indices:
            row = historical_df.iloc[idx]
            analogues.append(MarketAnalogue(
                setup_id=row['setup_id'],
                symbol=row['symbol'],
                timestamp=row['detected_at'],
                similarity_score=float(similarities[idx]),
                outcome=row['outcome'],
                pnl_bps=float(row['pnl_bps']),
                features=row.to_dict()
            ))
            
        return analogues

    def get_consensus_probability(self, analogues: List[MarketAnalogue]) -> float:
        """
        Derives a probability of success from the analogue set.
        
        Returns: Weighted probability based on similarity scores.
        """
        if not analogues:
            return 0.5
            
        # Weight wins by their similarity score to the current case
        weighted_wins = sum(a.similarity_score for a in analogues if a.outcome == "win")
        total_weight = sum(a.similarity_score for a in analogues)
        
        return weighted_wins / (total_weight + 1e-9)
