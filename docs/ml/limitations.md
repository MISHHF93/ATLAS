# ML limitations (read before trusting any number)

- **No edge found.** On the 2026-10-23 data, OOS Brier skill is negative in all four groups, and the filtered take
  sets have negative or ~0 mean after-cost R. The honest reading: these features do not predict which setups win
  after costs at the precision needed.
- **Costs dominate crypto 15m.** The take-all mean is −0.81 R per setup: 24 bp round trip is large next to the
  15m stop distances. Equity costs (4 bp + 1¢/sh) are lighter, but take-all is still −0.34 R (1h).
- **Short equity 15m history** (~60 days, provider limit): 93 OOS events, PBO not computable. This is not evidence either way.
- **Fill model**: conservative bar-OHLC replay (stop first when both barriers fall in one bar; gap-through setups
  skipped). No queue, partial fills or latency.
- **Conformal guarantees are marginal and assume exchangeability.** PSI flags significant feature drift in 3 of 4
  groups (volatility features), so realised coverage can be below 1−α.
- **Selection**: 20 trials enter the DSR deflation. Any later variant must be added to the trial count.
- **Shadow gate**: eligibility needs ≥ 4 weeks of forward shadow records, so offline backtests can never make a model eligible.
- **Regime proxy** is a heuristic (vol percentile × trend sign), not a fitted Markov-switching model (Hamilton 1989).
