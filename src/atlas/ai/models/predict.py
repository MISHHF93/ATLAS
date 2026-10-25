"""Unified prediction contract (spec 12.1).

One logical inference interface for every fitted model:

    predict(instrument, observation_time, horizon, feature_snapshot, model_version) -> Prediction

Rules:
- A field is populated only if the registered model declares it in ``validated_outputs``. Any other
  field stays ``None`` rather than being derived or guessed.
- A probability is returned only when it has gone through a held-out calibrator that is in scope and
  fitted strictly before ``observation_time``. Otherwise the prediction abstains with reason ``uncalibrated``.
- Abstaining is a valid output. ``abstention_reason`` lists every reason found, not only the first.
- A prediction is never an order. It carries ``execution_permission = "none"``, and only the
  deterministic control plane can act on anything derived from it.

The calibrators reuse the existing code: ``atlas.calibration.platt_scale_probability`` (Platt sigmoid)
and ``atlas.ai.models.evaluation.ProbabilityCalibrator`` (empirical bins). Uncertainty comes from
``atlas.ai.models.quant.conformal.AdaptiveConformal``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence

from atlas.calibration import platt_scale_probability

VALIDATABLE = frozenset({"probability_up", "probability_down", "probability_neutral", "probability_positive",
                         "expected_return", "expected_volatility", "uncertainty"})

# Abstention reason codes (stable strings; UI and tests depend on them)
STALE = "stale_data"
MISSING = "missing_features"
FUTURE = "feature_from_future"
UNKNOWN_MODEL = "unknown_model"
HORIZON = "horizon_mismatch"
SCOPE = "instrument_out_of_scope"
UNCALIBRATED = "uncalibrated"
CAL_UNSUPPORTED = "calibration_unsupported"
UNC_UNAVAILABLE = "uncertainty_unavailable"
UNC_WIDE = "uncertainty_too_wide"
NO_MODEL = "no_validated_model"
DATA_QUALITY = "data_quality"   # ATLAS feed flagged stale/gap/unconfirmed/provider_disagreement


@dataclass(frozen=True)
class FeatureSnapshot:
    """Point-in-time features. ``available_at`` is the earliest unix time each value could have been known."""
    values: Mapping[str, float | None]
    available_at: Mapping[str, int]
    data_quality_flags: tuple[str, ...] = ()   # from atlas.feeds AtlasFeed.quality_flags(); non-empty -> abstain


@dataclass(frozen=True)
class PlattCalibrator:
    """Platt sigmoid p = 1/(1+exp(A*s+B)), fitted on held-out (score, outcome) pairs only."""
    slope_a: float
    intercept_b: float
    fitted_through: int          # unix seconds of the last held-out sample used
    n_samples: int
    brier_holdout: float
    min_samples: int = 50

    def apply(self, score: float, *, observation_time: int) -> float:
        if self.n_samples < self.min_samples:
            raise LookupError(UNCALIBRATED)
        if observation_time <= self.fitted_through:
            raise LookupError(CAL_UNSUPPORTED)   # would leak: calibration saw this period
        return platt_scale_probability(score, slope_a=self.slope_a, intercept_b=self.intercept_b)


def fit_platt(scores: Sequence[float], outcomes: Sequence[int], *, fitted_through: int,
              min_samples: int = 50, iters: int = 100) -> PlattCalibrator:
    """Newton-Raphson logistic fit of y ~ sigmoid(w*s + c), returned in Platt (A=-w, B=-c) form.
    Call this on a held-out calibration split only; never on the final test set."""
    s = [float(x) for x in scores]
    y = [int(v) for v in outcomes]
    if len(s) != len(y) or any(v not in (0, 1) for v in y) or not s:
        raise ValueError("aligned binary outcomes required")
    w = c = 0.0
    for _ in range(iters):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for si, yi in zip(s, y):
            p = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, w * si + c))))
            r, q = p - yi, p * (1 - p)
            g0 += r * si; g1 += r
            h00 += q * si * si; h01 += q * si; h11 += q
        h00 += 1e-9; h11 += 1e-9
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-18:
            break
        dw, dc = (h11 * g0 - h01 * g1) / det, (h00 * g1 - h01 * g0) / det
        w, c = w - dw, c - dc
        if abs(dw) + abs(dc) < 1e-10:
            break
    probs = [platt_scale_probability(si, slope_a=-w, intercept_b=-c) for si in s]
    brier = sum((p - yi) ** 2 for p, yi in zip(probs, y)) / len(y)
    return PlattCalibrator(-w, -c, int(fitted_through), len(s), brier, min_samples)


@dataclass(frozen=True)
class BinCalibratorAdapter:
    """Adapter over the existing ``ProbabilityCalibrator``. Its scope check and sparse-bin check are kept."""
    calibrator: Any
    scope: Mapping[str, str]   # instrument_id, horizon_id, model_revision, target, unit

    def apply(self, score: float, *, observation_time: int) -> float:
        from datetime import datetime, timezone
        try:
            return float(self.calibrator.apply(min(1.0, max(0.0, score)),
                                               as_of=datetime.fromtimestamp(observation_time, timezone.utc), **self.scope))
        except ValueError as exc:
            raise LookupError(CAL_UNSUPPORTED) from exc


@dataclass
class RegisteredModel:
    model_version: str
    data_version: str
    horizon: str
    target: str                                  # label definition, e.g. "direction_up" or "setup_success"
    required_features: tuple[str, ...]
    score_fn: Callable[[Mapping[str, float]], float]
    calibrator: PlattCalibrator | BinCalibratorAdapter | None
    validated_outputs: frozenset[str]
    instruments: frozenset[str] | None = None    # None = any instrument
    max_feature_age_seconds: int = 3600
    conformal: Any | None = None                 # AdaptiveConformal-like object with half_width()
    max_uncertainty: float | None = None
    expected_return_fn: Callable[[Mapping[str, float]], float] | None = None
    expected_volatility_fn: Callable[[Mapping[str, float]], float] | None = None

    def __post_init__(self) -> None:
        bad = set(self.validated_outputs) - VALIDATABLE
        if bad:
            raise ValueError(f"unknown outputs {sorted(bad)}")
        if {"probability_up", "probability_positive"} <= set(self.validated_outputs):
            raise ValueError("a binary model has exactly one positive-class semantic")
        if "probability_neutral" in self.validated_outputs:
            raise ValueError("three-class outputs are not supported by any registered model yet")


@dataclass
class Prediction:
    instrument: str
    observation_time: int
    prediction_horizon: str
    model_version: str
    data_version: str | None
    target: str | None
    probability_up: float | None = None
    probability_down: float | None = None
    probability_neutral: float | None = None
    probability_positive: float | None = None
    expected_return: float | None = None
    expected_volatility: float | None = None
    uncertainty: float | None = None
    calibration_status: str = "none"
    feature_quality: float = 0.0
    abstention_reason: list[str] = field(default_factory=list)
    execution_permission: str = "none"

    @property
    def abstained(self) -> bool:
        return bool(self.abstention_reason)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["abstained"] = self.abstained
        return d


class ModelRegistry:
    def __init__(self) -> None:
        self._m: dict[str, RegisteredModel] = {}

    def register(self, m: RegisteredModel) -> None:
        if m.model_version in self._m:
            raise ValueError("model_version already registered (versions are immutable)")
        self._m[m.model_version] = m

    def get(self, version: str) -> RegisteredModel | None:
        return self._m.get(version)

    def versions(self) -> list[str]:
        return sorted(self._m)


DEFAULT_REGISTRY = ModelRegistry()   # no validated price-action model is registered yet: everything abstains


def predict(instrument: str, observation_time: int, horizon: str, feature_snapshot: FeatureSnapshot,
            model_version: str | None, registry: ModelRegistry | None = None) -> Prediction:
    reg = registry or DEFAULT_REGISTRY
    m = reg.get(model_version) if model_version else None
    if m is None:
        return Prediction(instrument, observation_time, horizon, model_version or "", None, None,
                          abstention_reason=[UNKNOWN_MODEL if model_version else NO_MODEL])
    out = Prediction(instrument, observation_time, horizon, m.model_version, m.data_version, m.target)
    reasons = out.abstention_reason
    if horizon != m.horizon:
        reasons.append(HORIZON)
    if m.instruments is not None and instrument not in m.instruments:
        reasons.append(SCOPE)

    vals, ok = {}, 0
    missing = stale = future = False
    for name in m.required_features:
        v, t = feature_snapshot.values.get(name), feature_snapshot.available_at.get(name)
        if v is None or t is None or not math.isfinite(float(v)):
            missing = True
            continue
        if t > observation_time:
            future = True
            continue
        if observation_time - t > m.max_feature_age_seconds:
            stale = True
            continue
        vals[name] = float(v)
        ok += 1
    out.feature_quality = ok / len(m.required_features) if m.required_features else 1.0
    reasons += [r for r, flag in ((MISSING, missing), (FUTURE, future), (STALE, stale)) if flag]
    if feature_snapshot.data_quality_flags:
        reasons.append(DATA_QUALITY)
        reasons += [f"{DATA_QUALITY}:{f}" for f in feature_snapshot.data_quality_flags]
    if reasons:
        return out

    score = float(m.score_fn(vals))
    wants_prob = bool({"probability_up", "probability_positive"} & m.validated_outputs)
    if wants_prob:
        if m.calibrator is None:
            reasons.append(UNCALIBRATED)
        else:
            try:
                p = m.calibrator.apply(score, observation_time=observation_time)
                out.calibration_status = "calibrated"
                if "probability_up" in m.validated_outputs:
                    out.probability_up = p
                    if "probability_down" in m.validated_outputs:
                        out.probability_down = 1.0 - p
                else:
                    out.probability_positive = p
            except LookupError as exc:
                reasons.append(str(exc.args[0]))
                out.calibration_status = str(exc.args[0])
    if "uncertainty" in m.validated_outputs:
        hw = m.conformal.half_width() if m.conformal is not None else float("inf")
        if not math.isfinite(hw):
            reasons.append(UNC_UNAVAILABLE)
        else:
            out.uncertainty = hw
            if m.max_uncertainty is not None and hw > m.max_uncertainty:
                reasons.append(UNC_WIDE)
    if "expected_return" in m.validated_outputs and m.expected_return_fn:
        out.expected_return = float(m.expected_return_fn(vals))
    if "expected_volatility" in m.validated_outputs and m.expected_volatility_fn:
        out.expected_volatility = float(m.expected_volatility_fn(vals))
    if reasons:   # never leak a probability alongside an abstention
        out.probability_up = out.probability_down = out.probability_positive = None
    return out
