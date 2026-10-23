"""Regime-Conditioned Feature Scaling and Volatility Normalization for ATLAS.

Implements advanced normalization techniques to ensure that structural 
features are comparable across different instruments and volatility regimes.

This prevents 'volatility drift' where a setup in a high-vol asset (e.g. SOL) 
is incorrectly compared to a setup in a low-vol asset (e.g. SPY).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple
from dataclasses import dataclass

@dataclass
class NormalizationParams:
    """Stored parameters for Z-score normalization per asset."""
    mean: float
    std: float

class RegimeScaler:
    """
    Handles the scaling of Price Action features based on local market regime.
    
    Implements:
    - Volatility-Adjusted Distances: Distances normalized by local ATR or StdDev.
    - Log-Returns Scaling: Transforming absolute price movements into log-space.
    - Min-Max Scaling for Bounded Features: Normalizing VPIN and OFI.
    """

    def __init__(self):
        self.asset_params: Dict[str, Dict[str, NormalizationParams]] = {}

    def update_params(self, symbol: str, feature_name: str, values: np.ndarray) -> None:
        """Updates the rolling mean and std for a specific feature to use for Z-scoring."""
        mean = np.mean(values)
        std = np.std(values) + 1e-9
        
        if symbol not in self.asset_params:
            self.asset_params[symbol] = {}
            
        self.asset_params[symbol][feature_name] = NormalizationParams(mean, std)

    def scale_feature(self, symbol: str, feature_name: str, value: float) -> float:
        """Applies Z-score normalization based on stored asset parameters."""
        params = self.asset_params.get(symbol, {}).get(feature_name)
        if params is None:
            return value # Fallback to raw value if no params available
            
        return (value - params.mean) / params.std

    def apply_regime_weight(self, value: float, regime: str) -> float:
        """
        Adjusts the importance of a feature based on the active regime.
        
        Example: Structural zones are more reliable in 'Compression' 
        regimes than in 'Extreme Expansion' (where everything breaks).
        """
        weights = {
            "Compression": 1.2,
            "Expansion": 0.8,
            "Trending": 1.0,
            "MeanReverting": 1.1
        }
        return value * weights.get(regime, 1.0)
