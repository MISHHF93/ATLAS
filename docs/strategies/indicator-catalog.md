# Indicator / context catalog (price-level suite and selector)

| name | definition | availability |
|---|---|---|
| prev_day/week/month high/low | extremes of the prior completed calendar session (exchange calendar) | after that session closes |
| asia/london/ny session high/low | extremes inside the session window (non-XNYS instruments) | at window end |
| swing high/low (fractal k=3) | high[i] > highs of the k bars on each side | at bar i+k close; expires after 3 days |
| equal highs/lows | two swings within tolerance | at the second swing's confirmation |
| gold opening box | high/low of 08:20–08:50 NY (or 08:30–09:00); premarket 08:00–08:05 | at box end; INSUFFICIENT_DATA if bars do not align or are missing |
| ATR | Wilder ATR(14) on the bar timeframe | bar close |
| daily bias | SMA50 vs SMA200 + 5-day SMA50 slope + k=2 swing structure on completed daily bars (≥205 required) → bullish / bearish / neutral / conflicting / insufficient | daily open + 1 day |
| 4h trend | close vs SMA50 of UTC 4h buckets | bucket close |
| vol regime | tercile of rv_pctile_480 (low < 1/3 ≤ mid < 2/3 ≤ high); undefined percentile maps to mid | bar close |
| session bucket | NY local hour: london [03, 08), ny_am [08, 12), ny_pm [12, 19), asia otherwise | bar close |
| htf_aligned / htf_against | candidate direction vs daily bias | bar close |
| level interaction state | approach, touch, rejection, breakout_attempt, sweep, reclaim, breakout_acceptance, retest_success/failure, breakout_failure, consolidation, expiration | bar close |
