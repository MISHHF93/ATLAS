# ATLAS Known Issues & Operational Boundaries

1. **External Broker Credentials Optional in Local `.env`**:
   - When `ALPACA_API_KEY_ID` or `IBKR_MCP_TOKEN` are not set in `.env`, `/api/research-integration/broker-intelligence` reports `unconfigured` honestly and never fabricates broker balances; ATLAS control-plane paper balances are explicitly tagged `ATLAS_CALCULATED`.
2. **Pine Script Subset Scope**:
   - ATLAS supports deterministic Pine v5/v6 indicators (`ta.sma`, `ta.ema`, `ta.rsi`, `ta.atr`, `ta.stdev`, `ta.crossover`, `ta.crossunder`, `ta.highest`, `ta.lowest`, `ta.pivothigh`, `ta.pivotlow`, `ta.vwap`, `ta.supertrend`) and `strategy.entry`/`strategy.exit`.
   - Constructs such as `request.footprint`, `matrix.*`, `polyline.*`, or unshifted `lookahead_on` are explicitly rejected with diagnostic reasons.
3. **Bar-Level Intrabar Ambiguity**:
   - When both stop-loss and take-profit fall inside the same historical OHLC bar, ATLAS conservative replay resolves the stop-loss first (`intrabar_stop_first`).

