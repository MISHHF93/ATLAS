"""Technique selector (meta-model): given causal market context, choose one registered price-action technique's
candidate, or abstain.

- ``ContextTracker`` computes context features bar by bar from closed bars only (regime/trend, efficiency ratio,
  volatility, ATR ratio, time of day, distance to prior-session levels, gap, opening-range stats). The same
  streaming code is used in research and live, so there is no batch/live skew.
- ``TechniqueSelector`` holds one contextual classifier per technique (logistic regression or gradient boosting),
  each predicting P(target before stop) from context + the candidate's own reward/risk and cost. ``choose`` picks
  the candidate with the largest EV-after-cost in R, and abstains when none is positive.
- The selector never trades. A chosen candidate gets ``selector_logit`` in its features, and only a model
  registered in the ``predict()`` registry (``selector_registered_model``, with a held-out Platt calibrator) can turn
  that into a probability. The opportunity EV gate and the deterministic control plane still decide.
- Nothing is registered by default. Registration requires the offline gates in
  ``atlas.research.technique_selection`` (beat always-abstain and best-single-technique after costs under purged
  walk-forward CV, DSR across all trials), and then shadow weeks.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from atlas.features.price_action.bars import EPS, Bar
from atlas.features.price_action.sessions import SessionSpec

TECHNIQUES = ("orb_retest", "dual_bollinger", "wick_reversal", "prior_day_range_reversal")
CONTEXT_FEATURES = ("trend_ema50_atr", "ema20_slope_atr", "efficiency_ratio_20", "atr_bps", "atr_ratio_14_96",
                    "tod_sin", "tod_cos", "minutes_since_open", "dist_prior_high_atr", "dist_prior_low_atr",
                    "gap_atr", "opening_range_atr", "close_in_opening_range")
CANDIDATE_FEATURES = ("reward_risk", "cost_r")


class ContextTracker:
    """Causal streaming context. ``update(bar)`` returns the features known at ``bar.end``."""

    def __init__(self, session: SessionSpec, opening_range_seconds: int = 3600):
        self.session, self.or_s = session, opening_range_seconds
        self.closes: deque[float] = deque(maxlen=21)
        self.trs: deque[float] = deque(maxlen=96)
        self.ema20 = self.ema50 = self.atr = None
        self.ema20_hist: deque[float] = deque(maxlen=6)
        self.n = 0
        self.prev_close: float | None = None
        self.sid = None
        self.sess: dict[str, Any] = {}
        self.prior: dict[str, float] | None = None

    def update(self, b: Bar) -> dict[str, float | None]:
        tr = b.high - b.low if self.prev_close is None else max(b.high - b.low, abs(b.high - self.prev_close),
                                                                 abs(b.low - self.prev_close))
        self.n += 1
        self.trs.append(tr)
        self.atr = tr if self.atr is None else (self.atr * 13 + tr) / 14 if self.n > 14 else (self.atr * (self.n - 1) + tr) / self.n
        self.ema20 = b.close if self.ema20 is None else self.ema20 + 2 / 21 * (b.close - self.ema20)
        self.ema50 = b.close if self.ema50 is None else self.ema50 + 2 / 51 * (b.close - self.ema50)
        self.ema20_hist.append(self.ema20)
        self.closes.append(b.close)
        win = self.session.window_for(b.start)
        if win is not None and win[0] != self.sid:
            if self.sess.get("hi") is not None:
                self.prior = {"hi": self.sess["hi"], "lo": self.sess["lo"], "close": self.sess["close"]}
            self.sid = win[0]
            self.sess = {"open_t": win[1], "close_t": win[2], "open": b.open, "hi": None, "lo": None, "close": None,
                         "or_hi": None, "or_lo": None, "or_done": False}
        s = self.sess
        if win is not None:
            s["hi"] = b.high if s["hi"] is None else max(s["hi"], b.high)
            s["lo"] = b.low if s["lo"] is None else min(s["lo"], b.low)
            s["close"] = b.close
            if b.end <= s["open_t"] + self.or_s:
                s["or_hi"] = b.high if s["or_hi"] is None else max(s["or_hi"], b.high)
                s["or_lo"] = b.low if s["or_lo"] is None else min(s["or_lo"], b.low)
                s["or_done"] = b.end == s["open_t"] + self.or_s
        self.prev_close = b.close
        a = max(self.atr, EPS)
        er = None
        if len(self.closes) == 21:
            path = sum(abs(self.closes[i] - self.closes[i - 1]) for i in range(1, 21))
            er = abs(self.closes[-1] - self.closes[0]) / path if path > 0 else 0.0
        f: dict[str, float | None] = {
            "trend_ema50_atr": (b.close - self.ema50) / a if self.n >= 50 else None,
            "ema20_slope_atr": (self.ema20_hist[-1] - self.ema20_hist[0]) / a if len(self.ema20_hist) == 6 and self.n >= 20 else None,
            "efficiency_ratio_20": er,
            "atr_bps": self.atr / b.close * 1e4 if self.n >= 14 else None,
            "atr_ratio_14_96": self.atr / max(sum(self.trs) / len(self.trs), EPS) if len(self.trs) == 96 else None,
            "tod_sin": None, "tod_cos": None, "minutes_since_open": None, "dist_prior_high_atr": None,
            "dist_prior_low_atr": None, "gap_atr": None, "opening_range_atr": None, "close_in_opening_range": None,
        }
        if win is not None:
            frac = (b.end - s["open_t"]) / max(s["close_t"] - s["open_t"], 1)
            f["tod_sin"], f["tod_cos"] = math.sin(2 * math.pi * frac), math.cos(2 * math.pi * frac)
            f["minutes_since_open"] = (b.end - s["open_t"]) / 60
            if self.prior is not None:
                f["dist_prior_high_atr"] = (self.prior["hi"] - b.close) / a
                f["dist_prior_low_atr"] = (b.close - self.prior["lo"]) / a
                f["gap_atr"] = (s["open"] - self.prior["close"]) / a
            if s["or_done"] or (s["or_hi"] is not None and b.end > s["open_t"] + self.or_s):
                rng = s["or_hi"] - s["or_lo"]
                f["opening_range_atr"] = rng / a
                f["close_in_opening_range"] = (b.close - s["or_lo"]) / rng if rng > 0 else 0.5
        return f


def feature_row(ctx: Mapping[str, Any], reward_risk: float, cost_r: float) -> list[float]:
    """Missing context values are imputed as 0 with no extra flag (documented; the trackers warm up quickly)."""
    row = [float(ctx.get(k)) if ctx.get(k) is not None else 0.0 for k in CONTEXT_FEATURES]
    return row + [float(reward_risk), float(cost_r)]


@dataclass
class TechniqueSelector:
    kind: str = "logistic"                      # "logistic" | "gbm"
    min_train: int = 60
    models: dict[str, Any] = field(default_factory=dict)
    fitted_through: int | None = None
    random_state: int = 7

    def _new(self):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        if self.kind == "gbm":
            return HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=40,
                                                  l2_regularization=1.0, random_state=self.random_state)
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))

    def fit(self, rows: Sequence[Mapping[str, Any]], fitted_through: int) -> "TechniqueSelector":
        """rows: {technique, x (feature_row), y (1 target first else 0)} from TRAINING data only."""
        import numpy as np
        self.models, self.fitted_through = {}, int(fitted_through)
        for tech in sorted({r["technique"] for r in rows}):
            X = np.array([r["x"] for r in rows if r["technique"] == tech], float)
            y = np.array([r["y"] for r in rows if r["technique"] == tech], int)
            if len(y) < self.min_train or len(set(y.tolist())) < 2:
                continue
            self.models[tech] = self._new().fit(X, y)
        return self

    def proba(self, technique: str, x: Sequence[float]) -> float | None:
        m = self.models.get(technique)
        if m is None:
            return None
        return float(m.predict_proba([list(x)])[0][1])

    def choose(self, options: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
        """options: {technique, x, reward_risk, cost_r, ...}. Returns (best option or None, scored list)."""
        scored = []
        for o in options:
            p = self.proba(o["technique"], o["x"])
            ev = None if p is None else p * o["reward_risk"] - (1 - p) - o["cost_r"]
            scored.append({**o, "p": p, "ev_r": ev, "reason": "untrained_technique" if p is None else None})
        live = [s for s in scored if s["ev_r"] is not None and s["ev_r"] > 0]
        if not live:
            return None, scored
        return max(live, key=lambda s: s["ev_r"]), scored


def annotate_choice(candidate, p: float) -> None:
    """Attach the selector output to a chosen candidate (as a logit) so ``predict()`` can calibrate it."""
    q = min(max(p, 1e-6), 1 - 1e-6)
    candidate.features["selector_logit"] = math.log(q / (1 - q))
    candidate.features["selector_choice"] = candidate.detector


def selector_registered_model(model_version: str, calibrator, data_version: str):
    """Registry entry for a validated selector. Only call after the offline gates AND shadow weeks pass."""
    from atlas.models.predict import RegisteredModel
    return RegisteredModel(model_version, data_version, "setup_resolution", "setup_success", ("selector_logit",),
                           lambda v: v["selector_logit"], calibrator, frozenset({"probability_positive"}))
