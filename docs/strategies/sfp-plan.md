# Swing-failure pattern (SFP) / liquidity-sweep programme: phased plan vs what exists

Status as of branch `atlas-sfp-1` (base `main` 69e2baf). Research and paper trading only. Every detector output has
`execution_permission: "none"`; only the deterministic `ActionableControlPlaneEngine` can authorize, reject or size anything.

## Component audit (what the mission names vs what is in the repo)

| Mission component | In repo before this branch? | Where / note |
|---|---|---|
| Opening range + breakout-retest (snapback-style continuation) | yes | `features/price_action/detectors.py::ORBRetestDetector` (`orb_retest`); legacy `strategies/snapback.py` on `features/zones.py` |
| Dual Bollinger breakout box | yes | `DualBollingerDetector` (zones only, no candidates) |
| Wick reversal zones | yes | `WickReversalDetector` (zones only) |
| Prior-day range reversal (3-candle) | yes | `prior_day.py` |
| Four-box levels | **no** | not found anywhere in `src/`; SFP marks four-box confluence as `missing` |
| Key pivots | **no** | — |
| Asian-session context | **no** (added here) | `liquidity_levels.py` Asian session high/low |
| HTF bias | **no** (added here, minimal) | completed daily / 4h close vs SMA, causal |
| Gold premarket ORB / early-bird | **no** | not implemented; out of scope for this slice |
| Market structure (BOS/CHoCH) | **no** (frontend text only) | minimal swing-break confirmation added in `sfp.py` |
| Equal highs / lows | **no** (added here) | registry |
| Unified candidate kinds (SNAPBACK_CONTINUATION_*, SFP_REVERSAL_*, ORB_BREAKOUT_*, ZONE_REJECTION_*, NO_TRADE) | **no** (added here) | `features/price_action/unified.py` |
| ML meta-label pipeline (triple barrier, purged WF, isotonic, conformal, DSR/PBO, registry gates) | yes | `src/atlas/ml/*` |
| Exchange calendars | partial | NYSE/FX/crypto in `marketdata/pit/calendars.py`; **no CME holiday calendar** |
| Order-flow analytics | code yes, **data no** | `microstructure/orderbook.py`; the feed store holds bars only (no L2/trades) → order-flow features `missing` |
| Control plane + paper autopilot | yes | `control/engine.py`, `autopilot/setups.py` (owner approval to switch on) |

## Phases

| # | Phase | Plan in this slice |
|---|---|---|
| 1 | Liquidity reference level registry | new `liquidity_levels.py`: prev completed month/week/day, session (Asia/London/NY), equal highs/lows, confirmed fractal swings, OR boundaries (from `orb_retest` zones). Four-box: N/A (does not exist) |
| 2 | SFP state machine (bull/bear) | new `sfp.py`, symmetric via sign transform, all alternate outcomes |
| 3 | Sweep-quality features + explanations | point-in-time features; order-flow `missing`; OBSERVED / INFERRED / UNVERIFIED |
| 4 | Unified candidates + conflicts/dedupe | `unified.py` |
| 5 | Invalidation, targets, costs, fills | stop beyond sweep extreme; target = opposing level / fixed R / ATR; net-of-cost R:R gate; replay is conservative_ohlc_v1 (gap-through stops, stop-first) |
| 6 | Governed re-entry | `reentry.py` (can only reject) |
| 7 | Displacement / structure confirmation | confirmation modes `none`, `next_bar`, `displacement`, `structure` |
| 8 | Order flow | N/A: no stored order-flow data |
| 9 | Replay baselines + ML meta-label | `scripts/sfp_research.py`, `ml/sfp_dataset.py`, variants 1–8 |
| 10 | Paper path | `EngineConfig.sfp` (off by default) → `proposals.evaluate` (abstains with no eligible model) → control plane. Nothing auto-enabled |

Final status of each phase is recorded in `docs/strategies/sfp.md`.
