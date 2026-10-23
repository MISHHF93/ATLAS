# Audit and gap map (Phase 1)

Branch `atlas-quant-1`, base `main@6de1e02`. Status was checked by reading the code and running the tests. It does not come from earlier docs.
Statuses used: **implemented+tested**, **partial**, **missing**, **duplicated**. Baseline suite on main: 1308 passed, 9 skipped (local venv run).

| Spec area | Existing location(s) | Status | Notes |
|---|---|---|---|
| Data / instruments / calendars | `marketdata/pit/calendars.py`, `models/calendars.py`, `ops/sessions.py`, `api/udf.py` (`_projected_rows`, `causal_bars`) | partial, duplicated | Three session/calendar modules. No single instrument master with tick size, multiplier or session. |
| Indicators (EMA/RSI/ATR/BB/VWAP) | `features/pine_features.py` (`_ema`, `_rsi`, `average_true_range` with 0 tests, `vwap_bands`), `features/microstructure.compute_atr`, `mcp/trading/research.py`, `api/udf._atr`, `volatility/` | duplicated, inconsistent | Different seeds and smoothing. **New:** `features/price_action/indicators.py` is the canonical, tested streaming + batch set. The old modules are unchanged (consolidation is pending). |
| Zones | `features/zones.py` ZoneEngine (pandas boxes; no lifecycle; 0 tests; used by strategies/snapback, coordinator, research backtester/trainer) | done (slice 3) | ZoneEngine rewritten as a facade over `price_action` (same API, tests vs frozen reference); `to_lifecycle_zone` adapter. |
| Session opening range / breakout-retest | none as a state machine | missing → **built** | `price_action/detectors.ORBRetestDetector` |
| Dual Bollinger / wick reversal | fragments in pine_features | missing → **built** | `price_action/detectors` |
| Economic events | none with availability timestamps | missing → **interface only** | `price_action/events.py`. There is no data source. |
| Order flow: Kyle λ, VPIN, OFI, Hawkes | `features/microstructure.py`, `marketdata/microstructure.py`, `marketdata/live_stream.py`, `whale_saas_az.py`, `regime/hawkes_detector.py` | implemented+tested (light), duplicated | 1–2 test files each. Multiple copies. |
| Order-book imbalance | — | missing | No explicit function. |
| Regimes | `models/regimes.py` (causal rules), `regime/hawkes_detector.classify_regime` | partial | No HMM or change-point model. |
| ML: labels, CV, PBO, DSR, conformal | `models/quant/*` (triple_barrier, purged k-fold/walk-forward, pbo_cscv, deflated_sharpe, conformal, registry gates, costmodel) | implemented+tested | — |
| Calibration | `calibration/` (Platt, ProbabilityCalibrator), `models/uncertainty_calibration` | done (slice 2) | Wired via `models.predict` (PlattCalibrator, BinCalibratorAdapter). |
| Unified predict() contract + abstention | many model-specific `predict()` | done (slice 2) | `models.predict` + `models.opportunity` EV gate; registry empty, so everything abstains until a model is validated. |
| Real-data setup evidence (walk-forward, Platt, DSR/PBO) | `research/setup_evidence.py`, `docs/spec/evidence/` | done (slice 3) | All 21 configs failed the gates; no model registered. |
| Paper setup autopilot (switch, approval, Safe stop) | `autopilot/setups.py`, `api/agent.py` | done (slice 4) | Founder rulebook default-denies until a holding limit is configured (owner decision). |
| Shadow-week collector | `models/shadow.py` | done (slice 4) | Feeds `record_shadow_week`; no live weeks collected yet. |
| API keys + localhost MCP | `keys/api_keys.py`, `keys/cli.py`, `api/agent.py` | done (slice 4) | Existing `/api/quant` UI routes stay unauthenticated (localhost UI). |
| EV / sizing | `autopilot/sizing.fractional_kelly` | partial | No EV-after-cost gate on calibrated probability. |
| Portfolio / ES | `portfolio/construction.py` (HRP/HERC, CVaR), `models/evaluation.expected_shortfall_95` | partial | — |
| Execution / costs | `execution/scheduling.almgren_chriss`, `execution/tactics/optimal`, `execution/paper`, `models/quant/costmodel` | implemented+tested (paper only) | Live trading disabled. |
| Replay / backtest | `research/backtest`, `research/vertical_slice.py` | partial | No bar-replay harness shared with the live path. **New:** the price-action engine shares `update()`/`run_batch()` (parity tested). |
| Experiment registry | `experiments/` (ExperimentStore, purged splits), `models/quant/registry` | implemented+tested | Two registries. |
| Competitions vs open market | comp/open/founder rulebooks in `control/` | implemented+tested | — |
| Control plane / governance | `control/engine.py` (ActionableControlPlaneEngine), `rules.py` (TradingRuleBook), `founder_track.py`, `config/founder/risk_policy.yaml` (sha-pinned) | implemented+tested | Final authority. Unchanged. |
| Frontend overlays | `LiveChartEngine`, `SecondBars` | partial → **added** | `/research/price-action` |
| NL research | `mcp/trading/research.py` | partial | — |
| Security | env-name config, no secrets in repo | partial | API-key scopes not audited in this slice. |
| Technique selection | `models/technique_selector.py`, PDR detector | **added (research)** | Not registered: failed real-data gates 2026-10-23 |
