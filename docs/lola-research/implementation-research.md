# Implementation research: ranked techniques for the paper-first multi-asset platform
_Written 2026-10-16. Research only; nothing in /workspace/trading-bot-app was changed. On 2026-10-16 every URL returned HTTP 200 except the SSRN pages, which answer automated clients with 403 (SSRN blocks bots; the pages exist, so open them in a browser). Licences come from the GitHub API._

Ranking = (benefit to *this* stack: LightGBM sleeves + stacker, HMM/GARCH, risk gate, autonomy ladder) ÷ effort, with evidence quality weighted heavily. Evidence: **A** = peer-reviewed or widely replicated, **B** = credible practitioner or book, **C** = early or mixed.

## Tier 1: validation integrity (do these first; they decide whether any later result can be trusted)
1. **Purged + embargoed K-fold and Combinatorial Purged CV (CPCV).** CV that drops training samples whose label windows overlap the test fold. CPCV produces a *distribution* of out-of-sample paths instead of a single walk-forward path. *Why here:* the champion/challenger process and the autonomy ladder need OOS estimates that are honest. Evidence A/B (López de Prado, AFML ch.7, 12). Effort M. Libs: skfolio `CombinatorialPurgedCV` (BSD-3). mlfinlab is now proprietary, so re-implement from the book. Risk: needs accurate label end-times (t1). https://github.com/skfolio/skfolio
2. **Deflated Sharpe Ratio (DSR) / Probabilistic Sharpe (PSR) + trial registry.** These correct the Sharpe ratio for skew, kurtosis and the number of trials. *Why:* make promotion between autonomy levels conditional on DSR > 0.95 using the full trial count. Evidence A. Effort S. No library needed; it is a few lines of scipy. Risk: undercounting trials gives a false pass. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
3. **Probability of Backtest Overfitting (PBO, CSCV).** Bailey/Borwein/López de Prado/Zhu. A second, independent overfitting gate for strategy selection. Evidence A. Effort S–M. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
4. **Triple-barrier labels.** Labels are set by profit-take and stop-loss barriers scaled by volatility (use the GARCH σ already in the stack) plus a time-out. This replaces fixed-horizon returns. *Why:* the label then matches how positions actually exit and comes with t1 built in for item 1. Evidence B. Effort M. Risk: barrier width becomes a hyperparameter, so count it as a trial.
5. **Meta-labeling.** The primary signal (sleeve scorer or rule) picks the side; a secondary classifier predicts P(the trade is profitable) and that probability drives the bet size. *Why:* the LightGBM stacker fits naturally as the meta-model, and the news-screener veto becomes one of its features. Evidence B (AFML ch.3; Hudson & Thames/Joubert, JFDS 2022). Effort M. Risk: leakage if the primary model is fitted on the same folds.
6. **Point-in-time data + survivorship-free universes.** Keep delisted TSX/TSXV names, use as-of fundamentals, and record corporate actions (CAD splits and consolidations are common on the TSXV). Evidence A (the bias is well documented). Effort M–L (mostly data procurement). Risk: free sources such as yfinance are survivorship-biased.

## Tier 2: alpha and features
7. **Alpha158/Alpha360 factor library + Qlib data/feature pipeline.** These are about 158 price/volume features, a sensible baseline input for the LightGBM sleeves. Evidence B (Qlib benchmarks are on China A-shares, so re-validate on CA/US). Effort S–M. Qlib is MIT. https://github.com/microsoft/qlib
8. **Cross-sectional value + momentum + quality (+ low-vol) sleeves.** These factor premia are robust across asset classes, including FX. Value and momentum are negatively correlated, which makes them good diversifiers. Evidence A. Effort M. https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere ; Quality Minus Junk https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432 . Risk: the Canadian universe is small and sector-concentrated (energy, financials, materials), so neutralize by sector.
9. **Time-series momentum / trend for FX and crypto.** Evidence A (Moskowitz-Ooi-Pedersen 2012; AQR "A Century of Evidence on Trend-Following"). Effort S. Risk: trend has had long flat stretches, so size it by vol target.
10. **Fractional differentiation (FFD).** Make price series stationary while keeping memory: pick the minimum d that passes ADF. Evidence B/C (gains are modest in independent tests). Effort S. Risk: the feature becomes window-dependent, so fit d inside each training fold only.
11. **Factor evaluation tooling (IC, turnover, decay).** Use alphalens-reloaded (Apache-2.0) to screen features before they reach the stacker. Effort S. https://github.com/stefan-jansen/alphalens-reloaded
12. **Crypto funding/basis as a *signal only* (spot-only constraint).** Perp funding rates, the quarterly basis and open interest act as crowding and sentiment indicators. They tilt or veto spot exposure; the platform holds no perps. Evidence C/B (BIS WP 1087 "Crypto carry"). Effort S–M; Kraken/Coinbase/Binance public market-data endpoints suffice. Risk: exchange data quality, and venue ToS for redistribution. https://www.bis.org/publ/work1087.htm

## Tier 3: portfolio construction, sizing, uncertainty
13. **HRP / HERC / NCO portfolio construction.** Clustering-based allocation that avoids inverting an unstable covariance matrix. Use it across sleeves and within the equity sleeve. Evidence B (beats Markowitz OOS in many studies but does not dominate inverse-vol). Effort S. Libs: skfolio (BSD-3) and Riskfolio-Lib (BSD-3), https://github.com/dcajasn/Riskfolio-Lib ; HRP paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678 . Benchmark it against 1/σ.
14. **Regime-aware vol targeting / sizing.** Scale the gross exposure of each sleeve by the HMM regime posterior and the GARCH forecast. Volatility-managed portfolios improve Sharpe for many factors (Moreira-Muir 2017, J. Finance; replication debate in Cederburg et al. 2020). Evidence A/B. Effort S. Libs: hmmlearn (BSD-3), arch (NCSA, permissive). Risk: HMM regime labels can flip after the fact, so use filtered probabilities, never smoothed ones.
15. **Conformal prediction for uncertainty.** Distribution-free prediction intervals. Wide intervals → smaller size, or abstain. This gives the risk engine an explicit "model not confident" input. Evidence B/C in finance (exchangeability is violated, so use adaptive or online conformal: Gibbs & Candès ACI). Effort S–M. MAPIE (BSD-3) https://github.com/scikit-learn-contrib/MAPIE ; ACI https://arxiv.org/abs/2106.00170

## Tier 4: execution
16. **Pre-trade cost/impact model (square-root impact + spread) calibrated on paper fills, with Almgren-Chriss scheduling.** Impact ≈ spread/2 + Yσ√(Q/ADV). Use AC to trade off urgency against impact for larger child-order schedules. Evidence A (the square-root law is widely replicated). Effort M. Risk: paper fills understate impact, so add conservative haircuts for TSXV and illiquid names. https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf (AC 2000, mirror)
17. **Execution algos: TWAP/VWAP/POV + participation caps.** Use IBKR native algos (Adaptive, VWAP) where possible rather than building them. Build your own POV capped at ~5–10% of ADV only for crypto. Evidence B. Effort S (broker native) to M (own). Measure implementation shortfall against arrival price.

## Tier 5: safety, monitoring, research hygiene
18. **Drift/anomaly monitoring + model registry.** Track PSI/KS drift on features, live-vs-backtest slippage, and IC decay. The existing isolation forest feeds automatic demotion down the autonomy ladder. Evidence B. Effort M. Evidently (Apache-2.0) https://github.com/evidentlyai/evidently ; MLflow (Apache-2.0) for the champion/challenger registry.
19. **Legally usable alternative data (Canada).** Low-risk sources: SEDAR+ filings, SEDI insider reports, CIRO short-sale data, Bank of Canada/StatCan open data, GDELT news. Avoid scraping personal data (PIPEDA) and scraping against ToS. Treat material non-public information under Ontario securities law (OSC) as off-limits. Evidence C for alpha. Effort M. https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/ , https://www.osc.ca/en
20. **LLM agents/sentiment (research only, veto/feature role).** Headline sentiment from LLMs showed predictive power (Lopez-Lira & Tang, https://arxiv.org/abs/2304.07619). Multi-agent frameworks also exist (TradingAgents, https://arxiv.org/abs/2412.20138). Evidence C: the training corpus leaks future information into backtests (look-ahead), and results are non-reproducible and mostly survive only in small caps. Restrict to point-in-time evaluation on post-cutoff data. Keep the existing veto-only design, and never give an LLM order authority.
21. **RL execution/allocation (FinRL).** Evidence C; prone to overfitting. Use only as a sandbox challenger. MIT. https://github.com/AI4Finance-Foundation/FinRL

## Open-source engines: borrow vs build
| Project | Licence | Recommendation |
|---|---|---|
| NautilusTrader | LGPL-3.0 | **Strongest candidate to borrow for the event-driven core** (Rust core, same code for backtest and live, IBKR + crypto adapters). LGPL is fine as a dependency; changes to the library itself must be published. https://github.com/nautechsystems/nautilus_trader |
| Qlib | MIT | Borrow the data layer, Alpha158 and the workflow/recorder ideas. Its backtester is too simple for multi-venue use. |
| vectorbt | Apache-2.0 + Commons Clause | Fast vectorized research sweeps. Commons Clause restricts selling it, so use it internally only. https://github.com/polakowo/vectorbt |
| zipline-reloaded | Apache-2.0 | Reference for the daily-bar equity pipeline and calendars (has a TSX calendar via exchange_calendars). |
| freqtrade | GPL-3.0 | Study its crypto dry-run, hyperopt and protections. Do **not** copy code: GPL is viral. |
| hummingbot | Apache-2.0 | Borrow exchange connector patterns (Kraken/Coinbase). |
| skfolio / Riskfolio-Lib | BSD-3 | Use directly for HRP/NCO and CPCV. |
| mlfinlab | proprietary now | Do not depend on it; re-implement the AFML methods. |
| arch, hmmlearn, MAPIE, alphalens-reloaded, Evidently | permissive | Use directly. |

**Build in-house:** the risk engine/final gate, the autonomy ladder, Canadian tax lots/ACB, venue eligibility, the policy signing. These are differentiating and safety-critical, and the existing tests already cover them.

## Red flags checklist (enforce in CI or the promotion gate)
- **Look-ahead:** features using same-bar close to trade at that close; fundamentals by period-end instead of filing date; smoothed HMM states; scalers or FFD d fitted on the full sample; LLM knowledge cutoff.
- **Survivorship:** current TSX/S&P constituents used historically; delisted coins dropped (crypto survivorship is severe).
- **Overfitting:** unlogged trials; hyperparameter tuning on the test fold; promotion without DSR/PBO; too few independent bets in a small CA universe.
- **Costs:** zero-spread backtests; ignoring FX conversion costs (CAD↔USD ~ IBKR spread plus Norbert's gambit alternatives), borrow costs, and crypto maker/taker fees and withdrawal fees.
- **Paper-to-live gap:** paper fills are optimistic, so require a live-shadow period with an implementation-shortfall budget before each autonomy step.
- **Data licensing:** exchange data redistribution limits (TSX via IBKR subscriptions are for personal use).

## Suggested order
CPCV + DSR/PBO + trial registry → triple-barrier + meta-labeling in the stacker → PIT/survivorship-free data → Alpha158 + value/mom/quality sleeves → vol/regime sizing + HRP → cost model calibrated on paper fills → drift monitoring tied to the autonomy ladder → alt data / LLM research sandbox.
