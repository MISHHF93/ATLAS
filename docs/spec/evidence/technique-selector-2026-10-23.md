# Technique selector and range-break hypothesis: 15m real-data evidence (2026-10-23)

Raw output: `technique-selector-2026-10-23.json`. Reproduce it with `python scripts/run_selector_evidence.py var/evidence_cache_15m`. The cache lives in `var/` and is not committed.

## Data

| Instrument | Source | 15m bars | Window (UTC) |
|---|---|---|---|
| SPY, QQQ, IWM | Yahoo chart (public), `range=60d` | 1,561 each | 2026-07-31 to 2026-10-23 |
| BTCUSDT, ETHUSDT | Binance public klines | 70,079 each | 2024-10-23 to 2026-10-23 |

**Caveat:** Yahoo serves only about 60 days of 15m data. The equity results therefore come from about 12 weeks of data in a single market regime, and they are weak evidence.

## Method

- Every technique runs on the same bars:
  - `orb_retest`
  - `dual_bollinger` zones (`dual_band_breakout`), using the zone_entry_v1 rule
  - `wick_reversal`
  - `prior_day_range_reversal`, which uses stop entries
- Labels come from a triple barrier under the conservative_ohlc_v1 replay, with max hold of 32 bars (8h).
- Costs are round trip: equity 4 bp + $0.01/share; crypto 24 bp.
- **Selector.** There is one classifier per technique: logistic regression, or HistGBM as a second trial. Its inputs are:
  - the causal context from `ContextTracker`: trend vs EMA50, EMA20 slope, efficiency ratio, ATR bps, ATR 14/96 ratio, time of day, distance to the prior-session high/low, gap, and opening-range size/position;
  - the candidate's reward/risk and cost in R.

  It picks the candidate with the highest EV_R = p·G − (1−p) − C when that EV is positive, and abstains otherwise. Data is pooled per asset class.
- **Cross-validation.** Expanding walk-forward with 5 test folds over decision times. Training rows are purged by exit time, with a 1-day embargo.
- **Baselines:**
  - always abstain;
  - best single technique, chosen by training-window mean R (it abstains if every technique is negative);
  - take all;
  - each fixed technique (hindsight).
- **DSR.** Computed on daily R sums, with all 16 non-abstain strategies tried across both groups counted as trials.

## Selector results (out of sample, after costs, in R)

| Group | Strategy | Trades taken | Total R | DSR |
|---|---|---|---|---|
| crypto | selector_logistic | 87 | −43.6 | 0.00 |
| crypto | selector_gbm | 255 | −94.3 | 0.00 |
| crypto | best_single_trained | 0 (every technique was negative in training) | 0 | n/a |
| crypto | take_all | 8,795 | −6,430.8 | 0.00 |
| crypto | fixed dual_band / orb / pdr / wick | 3,798 / 1,082 / 611 / 3,561 | −2,175 / −1,182 / −298 / −2,776 | 0.00 |
| equity | selector_logistic | 45 | −20.6 | 0.00 |
| equity | selector_gbm | 16 | −5.4 | 0.00 |
| equity | best_single_trained | 0 | 0 | n/a |
| equity | take_all | 252 | −93.1 | 0.00 |
| equity | fixed dual_band / orb / pdr / wick | 52 / 70 / 43 / 92 | −6.4 / −39.8 / −12.2 / −34.8 | 0.00 |

**Verdict: the selector fails its gates and is not registered.**

- It does not beat always-abstain, and it does not beat best-single-trained (which itself abstains).
- Its DSR is about 0.
- No technique is profitable after costs on these data. The selector loses much less than taking every trade, but abstaining is still better.
- With 24 bp round-trip crypto costs on 15m stops, cost alone is a large fraction of 1R.

## Hypothesis: "after the first 15 min, a break of the range level tends to reach the swing level"

- **Test.** For each session, take the first break of the prior-session high or low that happens after the first 15m bar. Measure the distance d from that level to the swing level, then check which comes first: the swing level, or a retreat of d back through the level. The null under a driftless martingale is 0.5. Ambiguous bars and unresolved sessions are excluded.

| Instrument | Resolved | P(swing first) | Wilson 95% | Binomial p vs 0.5 |
|---|---|---|---|---|
| SPY | 31 | 0.71 | 0.53–0.84 | 0.029 |
| QQQ | 23 | 0.83 | 0.63–0.93 | 0.003 |
| IWM | 24 | 0.75 | 0.55–0.88 | 0.023 |
| BTCUSDT | 320 | 0.49 | 0.43–0.54 | 0.70 |
| ETHUSDT | 309 | 0.40 | 0.35–0.46 | 0.0009 (the opposite direction) |
| Pooled | 707 | 0.48 | 0.44–0.52 | 0.33 |

**Reading:**

- On 2y of crypto there is no support for the claim. ETH shows significant *reversion*.
- The equity samples support it, but there are only about 25 sessions per symbol, all from one ~12-week window that was mostly an uptrend. No multiple-testing correction was applied across the 5 symbols. The claim is **not established** and is not encoded anywhere as fact.
- Rerun this when more equity 15m history is available.
