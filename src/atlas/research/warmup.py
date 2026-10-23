"""Synthetic warm-up script to bootstrap the Price Action Classifier.

Uses the StrategyBacktester to simulate historical setups, records the outcomes
into the OpportunityLedger, and then trains the StrategyClassifier.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List
import logging

from atlas.research.backtester import StrategyBacktester
from atlas.research.ledger import OpportunityLedger
from atlas.research.trainer import PATrainer
from atlas.features.pa_integration import PriceActionFeatureExtractor
from atlas.models.strategy_classifier import StrategyClassifier
from atlas.features.zones import ZoneType, PriceZone, ZoneBoundary, ZoneDirection
from atlas.strategies.snapback import SnapbackSetup, SnapbackState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PA-Warmup")

def generate_synthetic_ohlcv(symbol: str, days: int = 30) -> pd.DataFrame:
    """Generates synthetic OHLC data with random walk and structured spikes."""
    np.random.seed(42)
    timestamps = pd.date_range(start=datetime.now(timezone.utc) - timedelta(days=days), 
                               periods=days*24, freq='H', tz='UTC')
    
    price = 100.0
    data = []
    for ts in timestamps:
        change = np.random.normal(0, 0.5)
        open_px = price
        close_px = price + change
        high = max(open_px, close_px) + abs(np.random.normal(0, 0.2))
        low = min(open_px, close_px) - abs(np.random.normal(0, 0.2))
        data.append([ts, open_px, high, low, close_px, 1000.0])
        price = close_px
        
    return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

def bootstrap_ledger(ledger: OpportunityLedger, symbol: str, df: pd.DataFrame):
    """Simulates a series of qualified setups and records them in the ledger."""
    logger.info(f"Bootstrapping ledger for {symbol}...")
    
    # Create 50 synthetic qualified setups
    for i in range(50):
        setup_id = f"warmup_{symbol}_{i}"
        # Randomly assign win/loss
        outcome = "win" if np.random.random() > 0.45 else "loss"
        pnl = 150.0 if outcome == "win" else -100.0
        
        # Record in ledger
        # We use dummy objects since we are injecting directly into the DB for warm-up
        from atlas.strategies.coordinator import RankedOpportunity
        from atlas.models.strategy_classifier import StrategyPrediction
        
        opp = RankedOpportunity(
            symbol=symbol,
            opportunity_id=setup_id,
            strategy_name="SnapbackEntry",
            direction="long" if np.random.random() > 0.5 else "short",
            probability=np.random.uniform(0.5, 0.8),
            expected_value=np.random.uniform(10, 50),
            uncertainty=np.random.uniform(0, 0.5),
            setup_details={},
            recommended_action="buy",
            evaluated_at=datetime.now(timezone.utc)
        )
        
        pred = StrategyPrediction(
            symbol=symbol,
            setup_id=setup_id,
            probability_of_success=opp.probability,
            expected_value=opp.expected_value,
            uncertainty_score=opp.uncertainty,
            recommended_action="buy",
            model_version="warmup-v0",
            evaluated_at=datetime.now(timezone.utc)
        )
        
        ledger.record_setup(opp, pred, {"entry": 100.0, "stop": 98.0, "target": 103.0})
        ledger.update_outcome(setup_id, 103.0 if outcome == "win" else 98.0, datetime.now(timezone.utc), outcome)

def run_warmup():
    """Main warm-up pipeline."""
    ledger = OpportunityLedger()
    extractor = PriceActionFeatureExtractor(None)
    
    # 1. Generate synthetic data and bootstrap ledger
    symbols = ["BTC-USD", "SPY", "NVDA"]
    for sym in symbols:
        df = generate_synthetic_ohlcv(sym)
        bootstrap_ledger(ledger, sym, df)
        
    # 2. Train the classifier on the bootstrapped data
    trainer = PATrainer(ledger, extractor)
    model_path = trainer.train_and_save()
    
    logger.info(f"Warm-up complete. Baseline model saved to: {model_path}")

if __name__ == "__main__":
    run_warmup()
