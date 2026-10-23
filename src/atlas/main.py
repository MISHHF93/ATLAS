"""Main entry point for the ATLAS Autonomous Trading Intelligence System.

This runner orchestrates the full pipeline from market ingestion to risk-authorized execution.
It integrates the MarketDataGateway, OpportunityCoordinator, and ActionableControlPlaneEngine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.models.strategy_classifier import StrategyClassifier
from atlas.features.pa_integration import PriceActionFeatureExtractor
from atlas.features.feature_store import FeatureStore, create_feature_store
from atlas.research.memory import MarketMemoryEngine
from atlas.research.ledger import OpportunityLedger
from atlas.strategies.coordinator import OpportunityCoordinator
from atlas.strategies.runner import AtlasStrategyRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("ATLAS-Core")

class AtlasSystem:
    """
    The central orchestrator for the ATLAS platform.
    """
    def __init__(self):
        logger.info("Initializing ATLAS Unified Intelligence Platform...")
        
        # 1. Infrastructure & Data
        self.feature_store = create_feature_store(
            store_id="main_store",
            db_path="var/features.db",
            parquet_dir="var/parquet_features"
        )
        self.ledger = OpportunityLedger(db_path="var/opportunity_ledger.db")
        
        # 2. Intelligence Layers
        self.classifier = StrategyClassifier(model_path="var/models/pa_classifier_v1.bin")
        self.extractor = PriceActionFeatureExtractor(self.feature_store)
        self.memory = MarketMemoryEngine(self.ledger)
        
        # 3. Strategy Coordination
        self.coordinator = OpportunityCoordinator(
            classifier=self.classifier,
            feature_extractor=self.extractor,
            memory_engine=self.memory
        )
        
        # 4. Deterministic Control Plane
        self.control_plane = ActionableControlPlaneEngine()
        
        # 5. Execution Runner
        self.runner = AtlasStrategyRunner(
            control_plane=self.control_plane,
            classifier=self.classifier,
            feature_extractor=self.extractor,
            memory_engine=self.memory
        )

        # 6. Market Data Gateway
        self.gateway = LiveMarketDataGateway(
            control_engine=self.control_plane,
            demo_mode=True # Default to demo for safety
        )

    async def start(self):
        """Starts the live intelligence loop."""
        logger.info("ATLAS System Active. Monitoring Dual-Track Universe...")
        
        # Start the provider streams (Mocked/Demo for now)
        # In production, this would launch the async run_provider tasks
        
        try:
            while True:
                # Simulate a market tick for a subset of assets
                snapshot = self.gateway.ingest_dual_track_universe_snapshot()
                
                for frame in snapshot:
                    symbol = frame['symbol']
                    # Mocked OHLC data for the laasted hour for the coordinator
                    # In production, this is fetched from the FeatureStore/OrderBook
                    mock_df = self._get_mock_ohlcv(symbol)
                    
                    # Execute the Price Action Pipeline
                    request = self.runner.on_market_update(
                        symbol=symbol,
                        df=mock_df,
                        track=frame['track']
                    )
                    
                    if request:
                        logger.info(f"TRADE AUTHORIZED: {request.side} {request.instrument_id}")
                
                await asyncio.sleep(60) # Evaluate on 1-minute intervals
                
        except asyncio.CancelledError:
            logger.info("Shutting down ATLAS...")

    def _get_mock_ohlcv(self, symbol: str) -> pd.DataFrame:
        """Helper to provide necessary dataframe structure for the coordinator."""
        import pandas as pd
        import numpy as np
        
        now = datetime.now(timezone.utc)
        times = pd.date_range(end=now, periods=30, freq='h', tz='UTC')
        return pd.DataFrame({
            'timestamp': times,
            'open': np.random.uniform(100, 110, 30),
            'high': np.random.uniform(110, 120, 30),
            'low': np.random.uniform(90, 100, 30),
            'close': np.random.uniform(100, 110, 30),
            'volume': np.random.uniform(1000, 5000, 30)
        })

if __name__ == "__main__":
    import pandas as pd
    system = AtlasSystem()
    try:
        asyncio.run(system.start())
    except KeyboardInterrupt:
        pass
