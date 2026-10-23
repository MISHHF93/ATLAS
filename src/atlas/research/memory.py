"""Market Memory Retrieval System for ATLAS.

Implements a structural 'analogue' retrieval system that finds historical market 
situations similar to the current state. 

This system allows the ML brain to perform 'Case-Based Reasoning' by comparing 
the current structural features (Zone overlap, VPIN, OFI) against the 
OpportunityLedger of past outcomes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
import sqlite3

from atlas.research.ledger import OpportunityLedger
from atlas.models.schemas import Record, Text


class MarketAnalogue(Record):
    """A historical analogue to the current market state."""
    setup_id: Text
    symbol: Text
    timestamp: datetime
    similarity_score: float # Cosine similarity or Euclidean distance
    outcome: str # 'win' or 'loss'
    pnl_bps: float
    features: dict[str, Any]
    execution_permission: Literal["none"] = "none"


class MarketMemoryEngine:
    """
    Retrieves historical analogues to the current market state.
    
    This engine uses a k-Nearest Neighbors (k-NN) approach over the structural 
    feature space to find the most similar past setups.
    """

    def __init__(self, ledger: OpportunityLedger):
        self.ledger = ledger
        # Features we use for similarity matching
        self.similarity_features = [
            "zone_overlap_count", 
            "vpin", 
            "ofi", 
            "kyles_lambda", 
            "regime"
        ]

    def find_analogues(
        self, 
        current_features: pd.DataFrame, 
        k: int = 5
    ) -> List[MarketAnalogue]:
        """
        Finds the k most similar historical setups from the ledger.
        
        Args:
            current_features: DataFrame containing the current structural features.
            k: Number of analogues to retrieve.
        """
        # 1. Get all closed setups from ledger
        historical_df = self.ledger.get_training_set()
        if historical_df.empty:
            return []

        # 2. Prepare feature vectors
        # We only use the similarity_features defined above
        available_features = [f for f in self.similarity_features if f in historical_df.columns]
        
        # Normalize historical data (Z-score)
        hist_vecs = historical_df[available_features].values
        mean = np.mean(hist_vecs, axis=0)
        std = np.std(hist_vecs, axis=0) + 1e-9
        norm_hist_vecs = (hist_vecs - mean) / std

        # Normalize current vector
        curr_vec = current_features[available_features].values[0]
        norm_curr_vec = (curr_vec - mean) / std

        # 3. Compute Cosine Similarity
        # dot(A, B) / (||A|| * ||B||)
        dot_product = np.dot(norm_hist_vecs, norm_curr_vec)
        norm_hist = np.linalg.norm(norm_hist_vecs, axis=1)
        norm_curr = np.linalg.norm(norm_curr_vec)
        
        similarities = dot_product / (norm_hist * norm_curr + 1e-9)
        
        # 4. Extract top k
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

    def get_analogue_consensus(self, analogues: List[MarketAnalogue]) -> float:
        """
        Computes the consensus probability of success from retrieved analogues.
        
        Returns: P(Win) among the retrieved set.
        """
        if not analogues:
            return 0.5
            
        wins = sum(1 for a in analogues if a.outcome == "win")
        return wins / len(analogues)
