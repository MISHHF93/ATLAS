# Mandate gap matrix — 2026-10-24 (branch `atlas-full-1`, base main 87d24a0)

Status: **existing** = code present (not re-verified end to end unless noted); **partial** = some of the section exists;
**missing** = nothing found by grep/inspection; **new** = added on this branch. Built from a grep + directory survey,
so "existing" means "found", not "audited".

| § | Topic | Status | Paths / notes |
|---|---|---|---|
| 2–4 | Platform scope / architecture | partial | FastAPI `src/atlas/api/app.py`, Next.js `frontend/app/*`, feeds `src/atlas/feeds/` |
| 5 | Provider-neutral market data | partial | `feeds/core.py` (adapter base, reconnect, backoff), `feeds/providers/*`, `marketdata/quality.py`, `marketdata/data_rights.py` (entitlements), `marketdata/pit/calendars.py`. Gap detection is in `tests/test_stream_gaps.py`. No unified capability-tier registry |
| 6 | Instrument specs | partial | `marketdata/futures.py`, `models/quant/multi.py` multipliers; no single `ContractSpec` (rolls/expiry) contract |
| 7 | Market structure engine | **new** | `features/price_action/structure.py`: causal swings HH/HL/LH/LL, BOS, CHoCH, breakout success/fail, compression/expansion, with event records. Impulse/retrace not separated yet |
| 8 | Zone registry + interaction SM | partial | `levels.py` (LiquidityLevelRegistry, LevelInteractionEngine), `zones.py` Zone. Missing fields: confluence_ids, breakout/rejection counts, provenance; MA/VWAP/psych/supply-demand zone types |
| 9 | Four-Box | implemented (research; Event disabled) — pass 5 `intel/fourbox.py`, /research?tab=zones (moved from /research/lab?tab=fourbox 2026-10-24); | Opening/ORB `detectors.ORBRetestDetector`, Breakout `DualBollingerDetector`, Anchor `WickReversalDetector`, Event `events.event_zone` (no verified calendar data; disabled) |
| 10 | Snapback | partial | `strategies/snapback.py`, `suite.py`, stop alternatives in `docs/research/levels-2026-10-24.md`; trailing/partial/time exits not tested |
| 11 | Gold session models | **new** + existing | `gold_models.py` (Early Bird, range-bound to open, ORB alignment overlap math, Asian context; gold-only; 08:20–08:50 default); `suite.GoldBox` |
| 12 | SFP states | existing | `suite.py` SFP (BREAKOUT_ACCEPTED/FAILED/SWEEP_RECLAIMED/UNRESOLVED per audit) |
| 13 | Reentry | existing | `reentry.py` ReentryGovernor (max attempts, cooldown; per-level bug fixed earlier). Cumulative-loss cap not verified |
| 14–15 | Indicators + math | **new** + existing | `indicators.py` (EMA/RSI/ATR/BB/VWAP) + `library.py` (SMA, slope, MACD, ADX/DMI, ROC, momentum, log-ret, RV, Donchian, AVWAP, RVOL, anatomy, doji/engulfing/displacement, trend band, HTF mapping, fib, overlap, normalized distance, OBI, TI, Kyle λ, Hawkes, VPIN, EV, p_BE, sizing, wᵀμ/wᵀΣw, VaR/CVaR, Brier, log loss, reliability, IS). Almgren-Chriss existing `execution/scheduling.py`. Chart overlays for new ones: missing |
| 16–18 | Unified ML | existing (partial) | `ml/` (registry, selector, calibration, cv purged WF, drift), `models/quant/*` (lgbm, DSR, PBO, registry rollback). Two ML trees exist (`ml/` and `models/`) — overlap not reconciled. Full prediction contract/abstention set not verified |
| 19 | Continuation vs reversal | existing | `resolve()` in unified candidate (per spec docs) |
| 20 | Microstructure | partial (bar tier only; higher tiers gated) — pass 5 `intel/microstructure.py`; | `microstructure/orderbook.py`, `features/microstructure.py`, `features/toxicity.py`, whale modules. No L2 data in feed → disabled |
| 21 | Regime | implemented (causal classifier + strategy-by-regime) — pass 5 `intel/regime.py`; | `regime/hawkes_detector.py`, `models/quant` regime models |
| 22 | Cross-asset/macro | missing | no timestamp-correct macro dataset |
| 23 | Unified candidate | existing (partial) | `detectors.Candidate`, `proposals.py`; full field list not verified |
| 24 | Research lab | implemented — pass 5 `intel/lab.py` (DSR/PBO/bootstrap/cost/report ids); | `experiments/`, `research/`, DSR/PBO in `models/quant/metrics.py` |
| 25 | Backtest/replay | partial | `price_action/replay.py` (conservative_ohlc_v1), `research/backtester.py`; partial fills/latency not in PA replay |
| 26 | Portfolio | implemented (VaR/CVaR/stress; unpriced positions listed) — pass 5 `intel/portfolio.py`; | `portfolio/construction.py` (CVaR) |
| 27 | OMS/paper | existing | `execution/paper`, `risk/killswitch.py`, `risk/reconcile.py` |
| 28 | Control plane | existing | `control/engine.py`, `control/rules.py` (not modified) |
| 29 | Competition mode | implemented (separate rulebooks, probes) — pass 5 `control/tracks.py`; | `models/platform_state.py`, `models/trade_readiness.py` |
| 30–31 | Charting / UI | partial | `/research` Levels & sweeps tab; new structure/gold-session/indicator overlays **not wired** on this branch |
| 32 | Grounded assistant | implemented (retrieval + evidence IDs; LLM off) — pass 5 `intel/assistant.py`; | `ai/assistant/{tools,guard,store,providers}.py` |
| 33 | Market memory | partial (pass 5 `intel/memory.py` overlaps `research/memory.py`; consolidate) | `research/memory.py`, `ledgers/`, `journal/` |
| 34–35 | Security/obs | partial | `keys/api_keys.py` rate limit, `ops/health.py`; no correlation IDs found |
| 36 | Tests | partial | 57+ test modules; new `tests/price_action/test_mandate_full1.py` |
| 37–41 | DoD / process | not met | see checkpoint |

## External blockers
- No L2/L3 or aggressor-flagged trades in the feed → OBI/TI/VPIN/Kyle cannot run on real data (code is gated).
- No verified economic calendar → Event Box disabled.
- 1m gold history ≈ 5 trading days; no 5m; 15m cannot tile 08:20–08:50.
- No macro dataset for §22.

## Pass 6 / evo1 additions
| Item | Status |
|---|---|
| Governed ML evolution loop (genes incl. bar type, purged WF, lineage, champion/challenger, no auto-promotion) | Done (branch atlas-evo-1); no model beats baseline |
| Opportunity markers on Levels and desk charts (classes, tooltip, toggle, disclaimer, historical outcomes) | Done; TradingView widget itself cannot take markers |
| Alt bars HA/Renko/range/volume/dollar; tick gated; Kagi/P&F | Done; tick unavailable (no trade prints); Kagi/P&F not built |
| snapback/orb zero trades | Explained: timeframe_mismatch on 15m |
| Weekend "live" freshness on daily data; memory merge | Fixed |
