# Real time observer — October 22, 2026

The Real time panel now shows a separate experimental online logistic observer,
not the daily heuristic policy. It reads completed bars from the same sampled
Coinbase public last-trade tape used by the viewer. It never falls back to the
demo ring buffer or synthetic history. Stocks without this feed stay withheld.

The first snapshot creates a pending prediction without replaying startup history
as learned live outcomes. A subsequent read labels that prediction using the
first later completed sampled bar, provided it arrives within ten seconds.
Unchanged prices and longer gaps skip the training update. Duplicate reads of
the same bar do not train twice. Forming bars are excluded. Fewer than four bars,
or a last completed bar older than fifteen seconds, withholds interpretation.

Features are the latest close return, three-bar close return (both scaled by
1,000 and clipped to [-3, 3]), and candle body divided by range. Logistic
coefficients and bias update with a fixed 0.05 gradient step per resolved
directional outcome. Read cadence controls how many pending forecasts are
created; it does not capture every exchange trade or learn on every tick.

The panel displays exact model candles, experimental probability, input values,
learned coefficients, sample count, and recent predictions versus actual later
outcomes. Eight labeled outcomes ends the display's warm-up; this threshold is
not model validation. The output is UP above 0.55, DOWN below 0.45, and UNCERTAIN
otherwise. Probabilities are not calibrated and no profitability is established.

State is held in memory for this process and is shared across viewers of a symbol.
It resets on server restart. The observer has no order authority, promotion,
broker integration, or deployment into the separate daily policy model.

Regression checks cover delayed labels, unfinished bars, duplicate refreshes,
stale feeds, and real-only input selection. The production frontend build passed.
Live API inspection confirmed coefficient updates and resolved public outcomes.
