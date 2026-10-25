# evo8: robustness of the 1h candidate 432dba69a77e

Source: `scripts/champion_robustness.py` -> `docs/research/evo8-champion-robustness.json`. OOS rows from the purged walk-forward folds. No profitability claim.

- More history: none available in the feed (alts 15m from 2026-04-27; BTC/ETH 1h from 2024-10-23). Fetching more is out of scope (integrations).
- Taken R mean +0.071, circular block bootstrap 95% CI [-0.085, +0.224]; EV/opportunity +0.019, CI [-0.021, +0.062]. Both span 0. Block sizes 1/5/20: all span 0.
- Take-all -0.170, CI [-0.258, -0.088].
- Excluding the last fold: -0.032, CI [-0.213, +0.154]. The last fold carries 115% of taken R.
- Groups: alts +0.106 R/trade (333 trades); BTC/ETH -0.063 (86).
- Time: first half -0.054 (137 trades), second half +0.132 (282). 6/13 months positive; Oct 2026 has 164 trades. 15/26 symbols positive.

Conclusion: not stable across time or symbol groups; consistent with the strict-gate demotion.
- Evolve run d0e147849051 (42 genomes, bar types + context genes): 0 pass the strict gate; best = the same logit/no_signed/macro genome (fails min trades/fold, DSR 0.0024, Bonferroni).
