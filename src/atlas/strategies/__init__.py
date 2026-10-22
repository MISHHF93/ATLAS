"""ATLAS Multi-Strategy Quantitative Trading Bot Package (`src/atlas/strategies/`)."""
from atlas.strategies.arbitrage import BasisArbitrageStrategy
from atlas.strategies.auction import ALLOWED_AUCTION_TICKERS, OpeningAuctionDriveStrategy
from atlas.strategies.base import (
    BaseStrategy,
    CandleBar,
    ExecutionTactic,
    MicrostructureMetrics,
    OrderBookDepthSnapshot,
    SignalDirection,
    StrategySignal,
    StrategyTrack,
    dispatch_signal_to_control_plane,
    evaluate_signal_against_rulebook,
)
from atlas.strategies.microstructure import VpinAbsorptionStrategy
from atlas.strategies.range_garden import RangeGardenStrategy
from atlas.strategies.rl_agent import (
     DEFAULT_ACTOR_CRITIC_CHECKPOINT,
    ActorCriticCheckpoint,
    ActorCriticPolicyStrategy,
)

__all__ = [
    "ALLOWED_AUCTION_TICKERS",
    "ActorCriticCheckpoint",
    "ActorCriticPolicyStrategy",
    "BaseStrategy",
    "BasisArbitrageStrategy",
    "CandleBar",
    "DEFAULT_ACTOR_CRITIC_CHECKPOINT",
    "ExecutionTactic",
    "MicrostructureMetrics",
    "OpeningAuctionDriveStrategy",
    "OrderBookDepthSnapshot",
    "RangeGardenStrategy",
    "SignalDirection",
    "StrategySignal",
    "StrategyTrack",
    "VpinAbsorptionStrategy",
    "dispatch_signal_to_control_plane",
    "evaluate_signal_against_rulebook",
]

