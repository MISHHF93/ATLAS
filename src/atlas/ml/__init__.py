"""ATLAS meta-labeling ML stack (research + shadow only).

Pipeline: ATLAS feed (point-in-time) -> causal features + setup-detector outputs -> triple-barrier labels
(1-day max hold) -> meta-label model (take/skip + size per detected setup) -> purged/embargoed walk-forward ->
isotonic calibration + split-conformal abstention -> metrics (Brier, ECE, AUC, net expectancy, DSR, PBO) ->
versioned registry under var/ml (eligible for predict() only if every pre-declared gate passes).
Nothing in this package can place an order. See docs/ml/.
"""
