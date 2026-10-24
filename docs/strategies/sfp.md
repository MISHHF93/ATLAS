# Swing failure pattern (SFP)

**Definition.** Take a potential liquidity reference level L that became knowable at `available_ts`, with side s = +1 for a level above price and −1 below.
- **Breakout attempt:** the bar extreme trades beyond L by at least 1 tick.
- **Reclaim:** within `max_reclaim_bars`, a bar closes back on the original side.
- The candidate direction is −s (fade the sweep).
- If price is accepted beyond L instead (k closes beyond), the result is a breakout acceptance and SFP does not fire; that is the snapback/ORB path.

**Confirmation modes:**
- `none`: enter on the reclaim close.
- `next_bar`: the next bar closes in direction −s.
- `displacement`: the reclaim bar body is at least 1 ATR.
- `structure`: a confirmed swing on the reclaim side breaks.

**Orders and gates:**
- Entry is the reclaim close (limit, active 3 bars).
- Stop is the sweep extreme ± `stop_atr`·ATR.
- Target is the opposing level or a fixed R.
- Gates, each producing a NO_TRADE reason:
  - net RR = (|T−E| − c)/(|E−S| + c) < min_rr → REWARD_BELOW_COST
  - c/|E−S| > 0.5 → COST_TOO_HIGH
  - HTF conflict (optional) → HTF_CONFLICT
  - re-entry limits → REENTRY_LIMIT

**Explanations** are split OBSERVED / INFERRED / UNVERIFIED. Order flow is always UNVERIFIED (no data).

**Results.** No variant has a CI excluding zero. Crypto 15m loses clearly. See `docs/research/levels-2026-10-24.md`.

**Limitations:**
- 15m bars only.
- About 8 weeks of futures history.
- No order flow.
- Many variants tested.
