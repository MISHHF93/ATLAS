# ATLAS System Architecture

## Two-Plane Separation
1. **Research & Intelligence Plane (`execution_permission: "none"`)**:
   - Market feeds (`var/feeds/atlas_feed.sqlite`), causal indicators, price-action detectors (`src/atlas/features/price_action/`).
   - Strategy Discovery, Pine v5/v6 static parser, `StrategyIR`, parity validator, and walk-forward backtester (`src/atlas/research/strategy_engine.py`).
   - Calibrated `MetaModel` live inference (`src/atlas/ai/ml/live_intelligence.py`) guarded by `AINodeMiddleware`.
2. **Deterministic Control Plane (`src/atlas/control/engine.py`, `src/atlas/risk/safe_stop.py`)**:
   - Enforces the 2% daily-loss Safe Stop kill-switch, per-trade risk caps (0.5% competition / 1.0% open-market), notional caps, and session gates.
   - Structural independence from LLMs and ML models: operates even when all AI services are offline.

