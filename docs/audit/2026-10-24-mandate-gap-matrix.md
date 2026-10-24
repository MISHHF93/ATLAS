# Mandate gap matrix — 2026-10-24 (branch `atlas-full-1`, base main 87d24a0)

Status: **existing** = code present (not re-verified end to end unless noted); **partial** = some of the section exists;
**missing** = nothing found by grep/inspection; **new** = added on this branch. Built from a grep + directory survey,
so "existing" means "found", not "audited".

| § | Topic | Status | Paths / notes |
|---|---|---|---|
| 2–4 | Platform scope / architecture | partial | FastAPI `src/atlas/api/app.py`, Next.js `frontend/app/*`, feeds `src/atlas/feeds/` |
| 5 | Provider-neutral market data | partial | `feeds/core.py` (adapter base, reconnect, backoff), `feeds/providers/*`, `marketdata/quality.py`, `marketdata/data_rights.py` (entitlements), `marketdata/pit/calendars.py`. Gap detection is in `tests/test_stream_gaps.py`. No unified capability-tier registry |
| 6 | Instrument specs | existing (evo3) | `feeds/contracts.py` is the one source (rolls/expiry/costs, `verified:false` flags); intel SPEC, level research script and `risk.sizing.contracts_for_risk` derive from it; `/api/intel/contracts`. Pass 10: the remaining duplicates were actually in `feeds/universe.py` (FUTURES) and `feeds/instruments.py` (ES); both now read `CONTRACT_TERMS` (`marketdata/futures.py` / `models/quant/multi.py` never held multipliers — earlier note was wrong) |
| 7 | Market structure engine | **new** | `features/price_action/structure.py`: causal swings HH/HL/LH/LL, BOS, CHoCH, breakout success/fail, compression/expansion, with event records. Impulse/retrace not separated yet |
| 8 | Zone registry + interaction SM | partial (pass 8: `levels.py` Level has confluence_ids + provenance) | `levels.py` (LiquidityLevelRegistry, LevelInteractionEngine), `zones.py` Zone. Missing fields: confluence_ids, breakout/rejection counts, provenance; MA/VWAP/psych/supply-demand zone types |
| 9 | Four-Box | implemented (research; Event disabled) — pass 5 `intel/fourbox.py`, /research?tab=zones (moved from /research/lab?tab=fourbox 2026-10-24); | Opening/ORB `detectors.ORBRetestDetector`, Breakout `DualBollingerDetector`, Anchor `WickReversalDetector`, Event `events.event_zone` (no verified calendar data; disabled) |
| 10 | Snapback | partial (pass 10: `SnapbackSetup` subclassed the frozen pydantic Record so the detector raised on first use; now a mutable dataclass and the backtester path runs) | `strategies/snapback.py`, `suite.py`, stop alternatives in `docs/research/levels-2026-10-24.md`; trailing/partial/time exits not tested |
| 11 | Gold session models | **new** + existing | `gold_models.py` (Early Bird, range-bound to open, ORB alignment overlap math, Asian context; gold-only; 08:20–08:50 default); `suite.GoldBox` |
| 12 | SFP states | existing | `suite.py` SFP (BREAKOUT_ACCEPTED/FAILED/SWEEP_RECLAIMED/UNRESOLVED per audit) |
| 13 | Reentry | existing (evo3) | ReentryGovernor + tighten-only loss caps (family/day R, all-family day R, consecutive losses) from `config/risk_overlays/reentry_tighten.yaml`; outcomes fed back causally in replay and at the autopilot OMS; tested |
| 14–15 | Indicators + math | **new** + existing | `indicators.py` (EMA/RSI/ATR/BB/VWAP) + `library.py` (SMA, slope, MACD, ADX/DMI, ROC, momentum, log-ret, RV, Donchian, AVWAP, RVOL, anatomy, doji/engulfing/displacement, trend band, HTF mapping, fib, overlap, normalized distance, OBI, TI, Kyle λ, Hawkes, VPIN, EV, p_BE, sizing, wᵀμ/wᵀΣw, VaR/CVaR, Brier, log loss, reliability, IS). Almgren-Chriss existing `execution/scheduling.py`. Chart overlays for new ones: missing |
| 16–18 | Unified ML | existing (partial) | `ml/` (registry, selector, calibration, cv purged WF, drift), `models/quant/*` (lgbm, DSR, PBO, registry rollback). Two ML trees exist (`ml/` and `models/`) — overlap not reconciled. Full prediction contract/abstention set not verified |
| 19 | Continuation vs reversal | existing | `resolve()` in unified candidate (per spec docs) |
| 20 | Microstructure | partial (bar tier only; higher tiers gated) — pass 5 `intel/microstructure.py`; | `microstructure/orderbook.py`, `features/microstructure.py`, `features/toxicity.py`, whale modules. No L2 data in feed → disabled |
| 21 | Regime | implemented (causal classifier + strategy-by-regime) — pass 5 `intel/regime.py`; | `regime/hawkes_detector.py`, `models/quant` regime models |
| 22 | Cross-asset/macro | existing (evo5, partial) | Keyless FRED (DGS10, DGS2, VIXCLS, DTWEXBGS, CPIAUCNS) in feed `observations` with conservative availability dates; `ml/context.py` joins them causally (no-lookahead tests). Limits: latest vintage only (no ALFRED key), so revisions are approximated by lags; no cross-asset correlations/futures curve yet |
| 23 | Unified candidate | existing (partial) | `detectors.Candidate`, `proposals.py`; full field list not verified |
| 24 | Research lab | implemented — pass 5 `intel/lab.py` (DSR/PBO/bootstrap/cost/report ids); | `experiments/`, `research/`, DSR/PBO in `models/quant/metrics.py` |
| 25 | Backtest/replay | existing (evo3) | PA replay latency/trade-through/participation now default for lab, intel API, ML dataset and autopilot (`PAPER_REALISM`); `PaperBroker` opt-in `ExecRealism`. Pass 10: control plane `close_position(fraction=)` reduce-only partial close (audited `position_reduced`); autopilot books the real filled quantity by cancelling the unfilled remainder at zero P&L; `research/backtester.py` uses `PAPER_REALISM` by default (`realism=None` = legacy) |
| 26 | Portfolio | implemented (VaR/CVaR/stress; unpriced positions listed) — pass 5 `intel/portfolio.py`; | `portfolio/construction.py` (CVaR) |
| 27 | OMS/paper | existing | `execution/paper`, `risk/killswitch.py`, `risk/reconcile.py` |
| 28 | Control plane | existing | `control/engine.py`, `control/rules.py` (not modified) |
| 29 | Competition mode | implemented (separate rulebooks, probes) — pass 5 `control/tracks.py`; | `models/platform_state.py`, `models/trade_readiness.py` |
| 30–31 | Charting / UI | partial | `/research` Levels & sweeps tab; new structure/gold-session/indicator overlays **not wired** on this branch |
| 32 | Grounded assistant | implemented (retrieval + evidence IDs; LLM off) — pass 5 `intel/assistant.py`; | `ai/assistant/{tools,guard,store,providers}.py` |
| 33 | Market memory | partial (pass 5 `intel/memory.py` overlaps `research/memory.py`; consolidate) | `research/memory.py`, `ledgers/`, `journal/` |
| 34–35 | Security/obs | partial (pass 8: correlation IDs exist, `ops/correlation.py`, header x-correlation-id, JSON request logs) | `keys/api_keys.py` rate limit, `ops/health.py` |
| 36 | Tests | partial | 57+ test modules; new `tests/price_action/test_mandate_full1.py` |
| 37–41 | DoD / process | not met | see checkpoint |

## External blockers
- No L2/L3 or aggressor-flagged trades in the feed → OBI/TI/VPIN/Kyle cannot run on real data (code is gated).
- No verified economic calendar → Event Box disabled.
- 1m gold history ≈ 5 trading days; no 5m; 15m cannot tile 08:20–08:50.
- §22: macro now present (keyless FRED, release-lagged). True vintages need a FRED key.

## Pass 6 / evo1 additions
| Item | Status |
|---|---|
| Governed ML evolution loop (genes incl. bar type, purged WF, lineage, champion/challenger, no auto-promotion) | Done (branch atlas-evo-1); no model beats baseline |
| Opportunity markers on Levels and desk charts (classes, tooltip, toggle, disclaimer, historical outcomes) | Done; TradingView widget itself cannot take markers |
| Alt bars HA/Renko/range/volume/dollar; tick gated; Kagi/P&F | Done; tick unavailable (no trade prints); Kagi/P&F added in pass 8 |
| snapback/orb zero trades | Explained: timeframe_mismatch on 15m |
| Weekend "live" freshness on daily data; memory merge | Fixed |

## Pass 8 / evo2 (branch atlas-evo-2 from main 727975f)
| Item | Status |
|---|---|
| Marker categories: accurate per-class counts, n/a when a class cannot occur, rule-only not labelled a rejection | Done |
| Kagi (ATR reversal) and Point & Figure (ATR box, 3-box reversal) builders, genes, chart switcher | Done; causal, prefix-invariance tested |
| Evolution generation with the new bar types (run 3bdaaf38ba24) | Done; no model beats baseline |
| Legacy pathname map in InstitutionalWorkspacesView | Removed (it overrode tab views on hub paths) |
| Re-verified rows: §8 confluence/provenance exist; §34–35 correlation IDs exist | Matrix corrected |
| Closed in evo3: §13 cumulative-loss cap, §6 single contract source, §25 realism in PA replay paths. Pass 10 closed: multiplier duplicates (universe/instruments), control-plane partial close, backtester realism, snapback runnable. Pass 11 closed: §22 macro dataset (FRED, release-lagged) + HTF/macro context gene + ML diagnosis (docs/ml/evo5-diagnosis.md). Still open: ALFRED vintages (needs key), primary-strategy edge (negative gross R; founder decision) | Partly done |
| ext-1 | Seven-repo extensions (options/VaR/DCF/EDGAR/scan/Pine/dossier/personas/agents/Alpaca paper/alerts/MCP) | built (research/paper only) | `src/atlas/ext/`, `/api/ext/*`; see `2026-10-24-seven-repo-gap.md`. Blocked: option chains, news, maritime. Yield curve deferred to evo-5. |

## Pass 12 / evo6 additions
| Item | Status |
|---|---|
| Wider ATR stops / higher timeframe / cost-aware setup variants | Done (research, toggleable, off by default); 0/230 pass gates |
| Retire 15m orb_retest | Done as research-retired, reversible, documented reason |
| ML on gross-positive variant (PDR 4h) | Done; no challenger beats baseline |
