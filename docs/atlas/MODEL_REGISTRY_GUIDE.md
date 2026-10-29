# ATLAS Model Registry & Calibration Guide

Registry: `var/ml/registry/`, managed by `src/atlas/ai/ml/registry.py`.

As inspected on **2026-10-28**, five fitted artifacts exist: `crypto-15m`,
`crypto-1h`, `crypto-4h`, `equity-15m` and `equity-1h`. **All five are
`not_eligible`; zero are validated production models.** Being fitted, calibrated,
registered, or labeled a challenger does not establish eligibility.

Live inference requires eligible status, nonempty passed validation gates, the
exact asset/timeframe group and an explicit matching instrument in the training
series. It must not substitute another market, timeframe or asset class. Refer
to each manifest's `series` for scope: the presence of a symbol in the UI does
not put it in a model's validated universe. Metadata that labels futures as
equities requires correction and reevaluation.

`GET /api/ml/registry` shows saved versions and failed gates.
`GET /api/ml/prediction-health` distinguishes registered and eligible counts.
The lifecycle endpoints describe research roles; a lifecycle label does not
override validation gates or authorize orders.

The trained meta-label target is after-cost positive setup return. It is not
automatically an up/down/neutral price forecast or target-before-stop probability.
The newer live feature/target presentation still needs alignment with the actual
training and replay contract before trusting those forecast fields.

See the [global-market assessment](../research/global-market-evolution-2026-10-28.md)
for the exact inspected metrics, remaining inference limitations and phased
research plan. Run `scripts/global_market_check.py` to refresh local evidence
without loading model binaries, retraining or starting trading workers.

