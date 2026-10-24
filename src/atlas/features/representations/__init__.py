"""Alternative chart / bar representations built causally from the ATLAS feed's time bars.

See ``builders.py`` for formulas. HA is FEATURES/DISPLAY ONLY: its prices are synthetic and never used for fills or
P&L. Every representation here is used only to derive features or draw a chart; execution, labels and replay P&L stay
on real time-bar prices."""
from atlas.features.representations.builders import (  # noqa: F401
    BAR_TYPES, AltBar, build, heikin_ashi, range_bars, renko, tick_bars, threshold_bars, availability,
)
from atlas.features.representations.features import REP_FEATURES, rep_features  # noqa: F401
