# ATLAS Project Context

**Project:** Autonomous Trading, Liquidity, Allocation & Strategy Intelligence  
**Governance Invariant:** `execution_permission: "none"` on all AI, ML, and research surfaces. Paper trading only (`ActionableControlPlaneEngine`).

## Core Mission
ATLAS is a Canadian quantitative trading research and paper-execution platform integrating:
1. Multi-asset market data & 17-state exchange session calendars (`src/atlas/market/sessions.py`).
2. A research hand on the desk (`src/atlas/ai/ml/evolution.py`). The stored genome has not passed `evo8-strict-1`, so the stance abstains and cannot buy or sell. `registry.load_eligible()` remains the gate for a `predict()` model, and no version is eligible. `src/atlas/ai/ml/live_intelligence.py` is a separate probability path and is not a passed champion.
3. Open-source & Pine v5/v6 strategy discovery, canonical `StrategyIR` compilation, Python signal parity verification, and realistic purged walk-forward backtesting (`src/atlas/research/strategy_engine.py`).
4. Provider-neutral broker MCP intelligence (`BROKER_READ_ONLY` vs `BROKER_PAPER_EXECUTION`) and equity-curve reconciliation (`src/atlas/research/broker_intelligence.py`).
5. Dynamic position sizing (Fixed-Fractional, ATR, Quarter-Kelly) gated by deterministic control-plane constraints (`src/atlas/research/position_sizing.py`).
6. Durable research memory & cross-session AI handoffs (`src/atlas/research/memory_handoff.py`).

