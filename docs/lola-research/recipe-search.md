# Recipe search: ranked results

Generated 2026-10-17T15:44:51.767724+00:00 · grid 3072 valid combinations · **80 evaluated this run** · **80 trials in the log** (all count toward the Deflated Sharpe penalty) · PBO (CSCV) = 0.74 · OOS 2022-04-20 → 2025-09-30 (5 purged walk-forward folds, embargo 5d, horizon 5d) · TSFM provider: chronos-bolt (ok)

> **Synthetic data warning.** This run used a SYNTHETIC market with small planted effects. It shows the search, validation and multiple-testing machinery working end to end. It does **not** prove any real edge. Re-run on point-in-time historical data (`--parquet-dir`) before drawing conclusions.

Objective = annualised Sharpe − 0.25×(days breaching the 2% daily loss limit) − 0.5×(10% drawdown halts) − 0.1×(DD above 10%). Ranked by objective, then DSR. Not raw return.

| # | model | data | regime | vol | veto | meta | conformal | portfolio | cost gate | exec | Sharpe | DSR | MaxDD % | breaches | CAGR % | CPCV med |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | lgbm | price+news | hmm | rolling | on | on | off | hrp | off | market | 0.15 | 0.14 | 16.3 | 1 | 0.8 | 0.14 |
| 2 | lgbm_stack | price | hmm | har | off | on | off | herc | off | twap | -0.38 | 0.02 | 15.1 | 0 | -2.2 | -0.40 |
| 3 | lgbm | price+news | hmm | har | off | on | on | hrp | on | market | -0.21 | 0.04 | 16.5 | 1 | -1.6 | -0.26 |
| 4 | lgbm_stack | price+fund | hmm | rolling | off | on | off | herc | off | twap | -0.37 | 0.02 | 15.2 | 1 | -2.5 | nan |
| 5 | lgbm_stack | all | none | rolling | off | on | on | hrp | off | market | -0.12 | 0.05 | 12.8 | 1 | -1.0 | nan |
| 6 | lgbm_stack | all | none | rolling | on | on | on | hrp | off | market | -0.28 | 0.03 | 14.9 | 0 | -2.0 | nan |
| 7 | lgbm | all | hmm | har | on | on | on | equal | on | market | -0.17 | 0.05 | 16.6 | 0 | -1.5 | nan |
| 8 | lgbm_stack | price+fund | hmm | har | off | on | on | equal | off | market | -0.30 | 0.03 | 13.1 | 1 | -2.0 | nan |
| 9 | lgbm_stack | price+news | hmm | har | on | on | on | equal | on | twap | -0.75 | 0.00 | 17.7 | 0 | -4.0 | nan |
| 10 | lgbm_stack | price | none | har | off | on | on | hrp | off | twap | -0.51 | 0.01 | 15.1 | 0 | -3.1 | nan |
| 11 | lgbm_stack | price+macro | none | rolling | off | on | off | herc | on | twap | -0.20 | 0.04 | 16.2 | 1 | -1.5 | nan |
| 12 | lgbm_stack | all | hmm | har | on | on | off | herc | off | market | -0.45 | 0.01 | 17.1 | 0 | -2.9 | nan |
| 13 | lgbm_stack | all | hmm | har | off | off | off | herc | on | market | 0.45 | 0.30 | 18.9 | 1 | 3.8 | nan |
| 14 | lgbm_stack | price | hmm | har | off | on | on | equal | off | twap | -0.56 | 0.01 | 14.3 | 1 | -3.0 | nan |
| 15 | lgbm_stack | price+macro | none | rolling | off | on | on | equal | off | market | -0.36 | 0.02 | 16.7 | 1 | -2.4 | nan |

Baseline (momentum, price-only, everything off): Sharpe -0.18, DSR 0.04, MaxDD 29.7%.

## Which data feeds add the most expected value

| channel | Δ objective vs best price-only | Δ Sharpe | DSR with | would come from |
|---|---|---|---|---|
| news | +0.15 | +0.53 | 0.14 | Finnhub news/sentiment MCP, Benzinga, GDELT (our adapter), EODHD news |
| fund | -0.25 | +0.01 | 0.02 | EODHD fundamentals, FMP MCP, Finnhub basic_financials, SEDAR+ (our adapter) |
| macro | -0.27 | +0.25 | 0.05 | Bank of Canada Valet (our adapter), FRED (our adapter), StatCan WDS (our adapter) |

Winner registered as challenger `m0001-2be8270b` in var/demo/models/recipe. It must pass the existing champion/challenger shadow gates (>= 4 weeks) and owner approval; there is no auto-promotion.
