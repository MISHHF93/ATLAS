# 15m BUY / SELL / HOLD signal model (milestone d): design and heavy-run plan

Status: **research and paper shadow only. Predicted signal, not advice.** `execution_permission` is `none`. Nothing here sizes, places or recommends an order, and nothing here claims profitability.

## What was built
* `src/atlas/ai/ml/signal15.py`: setup frame (existing detectors on real closed 15m bars, triple-barrier labels, venue costs inside the label), the `multires` feature layers that have real coverage, a BUY/SELL/HOLD decision layer on the existing meta-labeler, model save/load with a manifest.
* `dataset.build_rows(hold_bars=...)` and `train.run_training / evaluate_group / fit_final (features=...)`: optional parameters only. Defaults are the old behaviour, so every existing caller is unchanged.
* `scripts/signal15_smoke.py`: small real-data smoke (walk-forward with 5 folds, base features vs base + multires). It is not `retrain --run`.

## Rules kept
* Labels are real bars only. Nowcast / gap-fill output is never a feature source for a label and is never in the feed DB.
* Decision clock: the 900 s grid, a setup is detected at a bar END `T` and every feature is computed from data with end <= T (tests: truncation invariance).
* Triple barrier: target / stop / vertical (`hold_bars`, never below the 3-bar entry window). Meta label y = 1 iff the realized after-cost R > 0. Costs: crypto spot 124 bp round trip, US equity 4 bp + $0.01/share, CME gold 4 bp (`costs.VENUE_COSTS`).
* Purged walk-forward: a training row is kept only if its exit is earlier than the test start minus the 1 day embargo (`cv.walk_forward_splits`). Calibration: isotonic / Platt, plus a split-conformal take rule.
* Gates are `train.GATES` as is: n_oos >= 200, DSR > 0.95, PBO < 0.5, 4 shadow weeks, plus Brier and log-loss beat the base rate. Not edited, not copied. `status = eligible` needs every gate, so a new shadow model is `not_eligible` for at least 4 weeks by construction.
* Primary hold is the pre-declared existing barrier (crypto 96 bars, equity 26). The tuned shorter holds (crypto 32, equity 4) are extra trials, not a selection on test results. The shadow model uses base + multires, fixed before the run.
* BUY = a long setup the model takes (EV_R > 0 after cost and conformal set {1}); SELL = a short setup it takes (on spot crypto that is a bearish signal, not an allowed position); HOLD is the default, including no setup at T.
* Layers with under 60 percent real coverage (1s, 1m, 5m, flow) are not trained on. They are logged live so history accumulates.

## Smoke result (real data, 2026-10-31, nothing selected on it)
| class | hold | rows | base rate | model | OOS n | Brier skill | AUC | taken | mean R taken | failed gates |
|---|---|---|---|---|---|---|---|---|---|---|
| crypto (coinbase BTC/ETH/SOL/XRP, 15m, ~2y) | 32 | 18293 | 0.096 | base | 18047 | +0.088 | 0.788 | 3 | +0.62 | DSR, shadow weeks |
| | | | | base+multires | 18047 | +0.086 | 0.789 | 0 | n/a | DSR, shadow weeks |
| | 96 | 18291 | 0.116 | base | 18045 | +0.121 | 0.802 | 3 | -1.44 | DSR, shadow weeks |
| | | | | base+multires | 18045 | +0.116 | 0.798 | 4 | -1.17 | DSR, shadow weeks |
| equity (polygon SPY/QQQ/AAPL/NVDA/MSFT, 15m) | 4 | 4979 | 0.325 | base | 4824 | -0.011 | 0.546 | 30 | -0.17 | Brier, log-loss, DSR, shadow weeks |
| | | | | base+multires | 4824 | -0.011 | 0.549 | 31 | -0.23 | Brier, log-loss, DSR, shadow weeks |
| | 26 | 4978 | 0.305 | base | 4801 | -0.002 | 0.565 | 219 | -0.15 | Brier, log-loss, DSR, shadow weeks |
| | | | | base+multires | 4801 | -0.004 | 0.568 | 170 | -0.21 | Brier, log-loss, DSR, shadow weeks |

How to read it honestly:
* Crypto AUC of about 0.8 is the cost geometry, not directional skill. Only about 10 percent of setups win after the 124 bp round trip because most stops are tighter than the cost, and the model learns which stops are wide enough. It takes almost nothing (0 to 4 setups out of 18k), and the few it takes have a negative mean R at hold 96. There is no evidence of a tradable crypto edge here, consistent with the horizon screen.
* Equity: Brier skill is not above the base rate, AUC is 0.55 to 0.57, and the taken setups lose after cost. It does not pass the gates.
* The multires layers (15m and 1h only, the ones with history) do not improve either class. The fast layers have too little history to test.
* The persisted shadow models (`var/ml/signal15/models/crypto_h96`, `equity_h26`, gitignored) are `not_eligible` and exist only to log shadow predictions.

## Heavy-run plan (NOT executed; needs the user's go-ahead)
* Scope: crypto 4 symbols and equity 5 symbols as in the smoke, then the full instrument list from `ml_horizons_roll`, 15m, both holds per class, 5 folds, all four detectors, single provider per instrument, and `--days` 730.
* Add as history grows: the 1m layer once the polygon 1m backfill covers 60 percent of the training rows, the flow and 1s layers once weeks of 1s data exist (not before; they have under an hour today).
* Cost: the smoke took about 17 minutes of one laptop (setup replay 40 s per instrument, walk-forward per class and hold). A full run is estimated at 1 to 3 hours and should run alone, off the ingest and roll loop hours.
* Command (do not run without approval): `.\.venv\Scripts\python.exe scripts/signal15_smoke.py --days 730 --folds 5`, output `var/ml/signal15/smoke_<ts>.json`. It never touches the registry or `retrain --run`.
* Pass criterion: unchanged `train.GATES`, then at least 4 shadow weeks of live paper predictions (`signal15_tick`) scored against real bars. Fail means the model stays HOLD only.
