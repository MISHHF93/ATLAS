# Price-level programme: 13-phase implementation plan (branch `atlas-sfp-1`)

Paper only. Every detector, model and selector output carries `execution_permission: none`. Only `ActionableControlPlaneEngine` authorizes, rejects or sizes orders.

| # | Phase | Status on this branch | Evidence |
|---|---|---|---|
| 1 | Audit and shared contracts (Bar, Level, LevelEvent, UnifiedCandidate, NoTradeReason, resolve) | done | `contracts.py`, `docs/audit/2026-10-24-repo-audit.md` |
| 2 | Exchange calendars: CME/COMEX/NYMEX with DST and holidays (early closes) | done (maintenance break not modelled) | `calendar.py`, tests |
| 3 | Liquidity level registry: prior day/week/month, Asia/London/NY session, fractal swings, equal highs/lows, boxes, availability timestamps | done | `levels.py` |
| 4 | Generic level interaction engine, shared by SFP / snapback / ORB | done | `LevelInteractionEngine`, tests |
| 5 | SFP detector (confirm modes, stop/target modes, net-RR and cost gates, re-entry) | done | `suite.py` |
| 6 | Gold slice: opening box 08:20–08:50 (and 08:30–09:00 variant), premarket 08:00–08:05, ORB acceptance, snapback retest with 4 stop modes, gold-only gating | done; 08:20 box not buildable on 15m data | `suite.py`, research doc |
| 7 | HTF bias (daily SMA50/200 + swings, 4h trend), conflict filter | done | `htf.py` |
| 8 | Continuation vs reversal vs abstain resolution; shared-evidence dedupe | done | `contracts.resolve`, tests |
| 9 | Replay + statistics (net expectancy, CI, PF, DD, tail, cost ×0/×1/×2, halves, session/regime splits) | done | `scripts/run_level_research.py` |
| 10 | **Strategy registry** with per-technique toggles (API + UI) | done | `strategies.py`, `GET/POST /api/quant/strategies` |
| 11 | **Strategy selector**: context classifier (HTF bias, vol tercile, NY session bucket, level-interaction state) + per-family meta-label models; ranks enabled candidates per scenario or abstains | done (research/shadow) | `ml/selector.py` |
| 12 | Frontend "Levels & sweeps" research tab (overlays, inspect panel, strategy switches) | done | `LevelsView.tsx` |
| 13 | Promotion gates: shadow ledger, minimum n, DSR/PBO, owner approval before any toggle feeds the paper autopilot | **deferred** | — |

## Selector design (math)
- Context vector `x_ctx(t)` = one-hot(daily bias ∈ {bullish, bearish, neutral, conflicting, insufficient}) ⊕ one-hot(vol tercile of `rv_pctile_480`) ⊕ one-hot(NY session ∈ {asia, london, ny_am, ny_pm}) ⊕ {htf_aligned, htf_against}.
  - Everything in it is known at bar close t. Daily bars count only after open + 1 day.
- For each family f the meta-label model gives `p_f(x)`, calibrated by Platt or isotonic scaling fitted on the tail of the training data.
- Expected value in R: `EV_f = p_f·RR_net − (1 − p_f)·(1 + cost_r)`.
- Selection at time t: among candidates from **enabled** strategies with EV_f > 0, pick argmax EV, one per t, deduped by `event_id`. If none qualifies, output NO_TRADE.
- Validation: purged walk-forward, embargo of 86,400 s, and min 60 training rows per family; otherwise `insufficient_rows`, which means abstain.
- Baselines: take_all, htf_rule, scenario_table, and abstain.
- Reported metrics: Brier, log loss, ECE and reliability bins. Brier is compared with the base rate.

## Deferred (explicitly not done)
- Phase 13 promotion gates and the shadow ledger for the selector.
- A dedicated regime classifier model. Context is currently a deterministic feature vector, not a learned regime model.
- Four-box levels: no definition or data exists in the repo.
- Key pivots.
- Economic-calendar abstain windows.
- Order-flow confirmation.
- 1m/5m history for the 08:20 box.
- The COMEX maintenance break.
- Registry toggles for the legacy detectors filter output in the API, but the engine still runs them.
