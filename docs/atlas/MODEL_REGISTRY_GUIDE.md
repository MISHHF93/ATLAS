# ATLAS Model Registry & Calibration Guide

- **Registry Location**: `var/ml/registry/` managed by `src/atlas/ai/ml/registry.py`.
- **Active Production Artifacts**:
  - `crypto-15m`, `crypto-1h`, `crypto-4h` (`BTC-USD`, `ETH-USD`, `SOL-USD`)
  - `equity-15m`, `equity-1h` (`SPY`, `QQQ`, `NVDA`, `AAPL`, `MSFT`, `GC`, `SI`, `NQ`, `ES`)
- **Calibration & Health Monitoring**:
  - Probabilities are calibrated out-of-fold (Platt/Isotonic) and monitored via Brier Score and Expected Calibration Error (ECE) on `/api/ml/prediction-health`.
  - Champion/Challenger promotion and automatic rollback are governed by `/api/ml/champion-challenger`.

