"""Walk-forward model selection, softmax, optional XGBoost, and feature ablations for the vertical slice."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import numpy as np

from atlas.research.vertical_slice_features import (
    CLASS_INDEX,
    CLASS_NAMES,
    CROSS_ASSET_FEATURE_NAMES,
    FEATURE_FAMILIES,
    FEATURE_NAMES,
    MODEL_FAMILY,
    RESEARCH_FEATURE_NAMES,
    SESSION_FEATURE_NAMES,
    XGBOOST_FAMILY,
    FeatureRow,
    SliceConfig,
    _finite,
)

# ---------------------------------------------------------------------------
# Model and evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoftmaxModel:
    model_id: str
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]
    training_rows: int
    training_loss: float
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        x = (np.asarray(features, dtype=np.float64) - np.asarray(self.mean)) / np.asarray(self.scale)
        z = x @ np.asarray(self.weights) + np.asarray(self.bias)
        z -= z.max()
        exp = np.exp(z)
        return exp / exp.sum()

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        x = (np.asarray(matrix, dtype=np.float64) - np.asarray(self.mean)) / np.asarray(self.scale)
        z = x @ np.asarray(self.weights) + np.asarray(self.bias)
        z -= z.max(axis=1, keepdims=True)
        exp = np.exp(z)
        return exp / exp.sum(axis=1, keepdims=True)

    def importance(self) -> list[dict[str, Any]]:
        weights = np.asarray(self.weights)
        magnitude = np.abs(weights).sum(axis=1)
        total = float(magnitude.sum()) or 1.0
        order = np.argsort(-magnitude)
        return [
            {
                "feature": self.feature_names[int(index)],
                "importance": round(float(magnitude[int(index)] / total), 6),
                "coef_down": round(float(weights[int(index), 0]), 6),
                "coef_neutral": round(float(weights[int(index), 1]), 6),
                "coef_up": round(float(weights[int(index), 2]), 6),
            }
            for index in order
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": MODEL_FAMILY,
            "feature_names": list(self.feature_names),
            "mean": list(self.mean),
            "scale": list(self.scale),
            "weights": [list(row) for row in self.weights],
            "bias": list(self.bias),
            "training_rows": self.training_rows,
            "training_loss": self.training_loss,
            "dataset_hash": self.dataset_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SoftmaxModel":
        return cls(
            model_id=str(payload["model_id"]),
            feature_names=tuple(payload["feature_names"]),
            mean=tuple(float(value) for value in payload["mean"]),
            scale=tuple(float(value) for value in payload["scale"]),
            weights=tuple(tuple(float(value) for value in row) for row in payload["weights"]),
            bias=tuple(float(value) for value in payload["bias"]),
            training_rows=int(payload["training_rows"]),
            training_loss=float(payload["training_loss"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def _xgboost_module() -> Any | None:
    try:
        import xgboost  # type: ignore[import-not-found]
    except ImportError:
        return None
    return xgboost


@dataclass
class XGBoostModel:
    """Small adapter around the optional XGBoost multiclass classifier."""

    model: Any
    feature_names: tuple[str, ...]
    model_id: str
    version: str
    training_rows: int
    training_log_loss: float
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        return self.predict_many(np.asarray([features], dtype=np.float64))[0]

    def _booster(self) -> Any:
        return self.model.get_booster() if hasattr(self.model, "get_booster") else self.model

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        values = np.asarray(matrix, dtype=np.float64)
        if hasattr(self.model, "get_booster"):
            raw = np.asarray(self.model.predict(values), dtype=np.float64)
        else:
            xgboost = getattr(sys.modules.get("atlas.research.vertical_slice"), "_xgboost_module", _xgboost_module)()
            if xgboost is None:
                raise RuntimeError("xgboost is unavailable")
            raw = np.asarray(
                self._booster().predict(
                    xgboost.DMatrix(values, feature_names=list(self.feature_names))
                ),
                dtype=np.float64,
            )
        if raw.ndim == 1:
            raw = np.column_stack([1.0 - raw, raw, np.zeros_like(raw)])
        raw = np.clip(raw, 1e-12, 1.0)
        return raw / raw.sum(axis=1, keepdims=True)

    def importance(self) -> list[dict[str, Any]]:
        booster = self._booster()
        raw = booster.get_score(importance_type="gain")
        values = np.asarray(
            [
                float(raw.get(f"f{index}", raw.get(name, 0.0)))
                for index, name in enumerate(self.feature_names)
            ],
            dtype=np.float64,
        )
        total = float(values.sum()) or 1.0
        order = np.argsort(-values)
        return [
            {
                "feature": self.feature_names[int(index)],
                "importance": round(float(values[int(index)] / total), 6),
                "method": "gain",
            }
            for index in order
        ]

    def explain(
        self,
        features: Sequence[float],
        class_index: int,
        feature_map: dict[str, float],
    ) -> list[dict[str, Any]]:
        xgboost = getattr(sys.modules.get("atlas.research.vertical_slice"), "_xgboost_module", _xgboost_module)()
        if xgboost is None:
            raise RuntimeError("xgboost is unavailable")
        matrix = xgboost.DMatrix(
            np.asarray([features], dtype=np.float64),
            feature_names=list(self.feature_names),
        )
        values = np.asarray(
            self._booster().predict(matrix, pred_contribs=True),
            dtype=np.float64,
        )
        if values.ndim == 3:
            contributions = values[0, :-1, class_index]
        else:
            contributions = values[0, :-1]
        order = np.argsort(-np.abs(contributions))
        return [
            {
                "feature": self.feature_names[int(index)],
                "value": round(float(feature_map[self.feature_names[int(index)]]), 8),
                "contribution": round(float(contributions[int(index)]), 8),
                "method": "tree_shap",
            }
            for index in order[:6]
        ]

    def to_dict(self) -> dict[str, Any]:
        raw = self._booster().save_raw()
        return {
            "model_id": self.model_id,
            "model_family": XGBOOST_FAMILY,
            "feature_names": list(self.feature_names),
            "training_rows": self.training_rows,
            "training_log_loss": round(self.training_log_loss, 8),
            "dataset_hash": self.dataset_hash,
            "version": self.version,
            "raw_model_b64": base64.b64encode(bytes(raw)).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "XGBoostModel":
        xgboost = getattr(sys.modules.get("atlas.research.vertical_slice"), "_xgboost_module", _xgboost_module)()
        if xgboost is None:
            raise RuntimeError("xgboost is required to load this model")
        booster = xgboost.Booster()
        booster.load_model(bytearray(base64.b64decode(payload["raw_model_b64"])))
        return cls(
            model=booster,
            feature_names=tuple(payload["feature_names"]),
            model_id=str(payload["model_id"]),
            version=str(payload.get("version") or "unknown"),
            training_rows=int(payload["training_rows"]),
            training_log_loss=float(payload["training_log_loss"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def fit_xgboost(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
    seed: int = 42,
    dataset_hash: str = "",
) -> XGBoostModel | None:
    xgboost = getattr(sys.modules.get("atlas.research.vertical_slice"), "_xgboost_module", _xgboost_module)()
    if xgboost is None:
        return None
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if x.ndim != 2 or x.shape[1] != len(feature_names) or len(y) != len(x):
        raise ValueError("feature matrix and labels are not aligned")
    if len(np.unique(y)) < 2:
        return None
    dtrain = xgboost.DMatrix(
        x,
        label=y,
        feature_names=list(feature_names),
    )
    parameters = {
        "objective": "multi:softprob",
        "num_class": 3,
        "max_depth": 3,
        "eta": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "min_child_weight": 2.0,
        "lambda": 1.0,
        "tree_method": "hist",
        "nthread": 1,
        "seed": seed,
        "verbosity": 0,
        "eval_metric": "mlogloss",
    }
    model = xgboost.train(parameters, dtrain, num_boost_round=120)
    probabilities = np.asarray(model.predict(dtrain), dtype=np.float64)
    probabilities = np.clip(probabilities, 1e-12, 1.0)
    training_log_loss = float(
        -np.log(probabilities[np.arange(len(y)), y]).mean()
    )
    fingerprint = dataset_hash or hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    return XGBoostModel(
        model=model,
        feature_names=tuple(feature_names),
        model_id=f"{XGBOOST_FAMILY}:{fingerprint[:12]}:{len(feature_names)}f",
        version=str(getattr(xgboost, "__version__", "unknown")),
        training_rows=len(y),
        training_log_loss=training_log_loss,
        dataset_hash=fingerprint,
    )


@dataclass(frozen=True)
class ConstantProbabilityModel:
    """Baseline champion used when a learned model loses out of sample."""

    model_id: str
    model_family: str
    probabilities: tuple[float, float, float]
    feature_names: tuple[str, ...]
    training_rows: int
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        return np.asarray(self.probabilities, dtype=np.float64)

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray(self.probabilities, dtype=np.float64), (len(matrix), 1))

    def importance(self) -> list[dict[str, Any]]:
        return []

    def explain(
        self,
        features: Sequence[float],
        class_index: int,
        feature_map: dict[str, float],
    ) -> list[dict[str, Any]]:
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "probabilities": list(self.probabilities),
            "feature_names": list(self.feature_names),
            "training_rows": self.training_rows,
            "dataset_hash": self.dataset_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConstantProbabilityModel":
        values = tuple(float(value) for value in payload["probabilities"])
        if len(values) != 3:
            raise ValueError("baseline probabilities must have three classes")
        return cls(
            model_id=str(payload["model_id"]),
            model_family=str(payload["model_family"]),
            probabilities=(values[0], values[1], values[2]),
            feature_names=tuple(payload["feature_names"]),
            training_rows=int(payload["training_rows"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def _one_hot(labels: np.ndarray) -> np.ndarray:
    out = np.zeros((len(labels), 3), dtype=np.float64)
    out[np.arange(len(labels)), labels] = 1.0
    return out


def fit_softmax(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
    l2: float = 0.02,
    epochs: int = 450,
    learning_rate: float = 0.05,
    seed: int = 42,
    dataset_hash: str = "",
) -> SoftmaxModel:
    if len(features) != len(labels) or not features:
        raise ValueError("features and labels must be non-empty and aligned")
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if x.ndim != 2 or x.shape[1] != len(feature_names):
        raise ValueError("feature matrix width does not match feature_names")
    if y.min() < 0 or y.max() > 2:
        raise ValueError("labels must be 0, 1, or 2")
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    normalized = (x - mean) / scale
    rng = np.random.default_rng(seed)
    weights = rng.normal(0.0, 0.01, size=(x.shape[1], 3))
    bias = np.zeros(3, dtype=np.float64)
    target = _one_hot(y)
    m_w = np.zeros_like(weights)
    v_w = np.zeros_like(weights)
    m_b = np.zeros_like(bias)
    v_b = np.zeros_like(bias)
    beta1, beta2, epsilon = 0.9, 0.999, 1e-8
    loss = float("inf")
    for epoch in range(1, epochs + 1):
        logits = normalized @ weights + bias
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probabilities = exp / exp.sum(axis=1, keepdims=True)
        loss = float(-np.log(np.clip(probabilities[np.arange(len(y)), y], 1e-12, 1.0)).mean())
        loss += float(l2 * np.sum(weights * weights))
        gradient = (probabilities - target) / len(y)
        grad_w = normalized.T @ gradient + 2.0 * l2 * weights
        grad_b = gradient.sum(axis=0)
        m_w = beta1 * m_w + (1 - beta1) * grad_w
        v_w = beta2 * v_w + (1 - beta2) * (grad_w * grad_w)
        m_b = beta1 * m_b + (1 - beta1) * grad_b
        v_b = beta2 * v_b + (1 - beta2) * (grad_b * grad_b)
        m_w_hat = m_w / (1 - beta1**epoch)
        v_w_hat = v_w / (1 - beta2**epoch)
        m_b_hat = m_b / (1 - beta1**epoch)
        v_b_hat = v_b / (1 - beta2**epoch)
        weights -= learning_rate * m_w_hat / (np.sqrt(v_w_hat) + epsilon)
        bias -= learning_rate * m_b_hat / (np.sqrt(v_b_hat) + epsilon)
    fingerprint = dataset_hash or hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    model_id = f"{MODEL_FAMILY}:{fingerprint[:12]}:{len(feature_names)}f"
    return SoftmaxModel(
        model_id=model_id,
        feature_names=tuple(feature_names),
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        weights=tuple(tuple(float(value) for value in row) for row in weights),
        bias=tuple(float(value) for value in bias),
        training_rows=len(y),
        training_loss=round(loss, 8),
        dataset_hash=fingerprint,
    )


def _frequency_baseline(labels: Sequence[int]) -> np.ndarray:
    counts = np.bincount(np.asarray(labels, dtype=np.int64), minlength=3).astype(np.float64)
    counts += 0.5
    return counts / counts.sum()


def _action(probabilities: Sequence[float], config: SliceConfig) -> tuple[str, str | None, float]:
    p_down, p_neutral, p_up = (float(value) for value in probabilities)
    confidence = max(p_down, p_up)
    edge = p_up - p_down
    if (
        p_up >= config.confidence_threshold
        and p_up >= p_neutral
        and edge >= config.edge_threshold
    ):
        return "long", "up_probability_and_positive_edge", edge
    if (
        p_down >= config.confidence_threshold
        and p_down >= p_neutral
        and edge <= -config.edge_threshold
    ):
        return "short", "down_probability_and_negative_edge", edge
    if p_neutral == max(probabilities):
        return "abstain", "neutral_class", edge
    return "abstain", "confidence_or_edge_below_threshold", edge


def _bucket(value: float, bins: int = 5) -> int:
    return min(bins - 1, max(0, int(value * bins)))


def evaluate_predictions(
    probabilities: np.ndarray,
    labels: Sequence[int],
    forward_returns: Sequence[float],
    *,
    cost_bps: float,
    config: SliceConfig,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64)
    p = np.asarray(probabilities, dtype=np.float64)
    returns = np.asarray(forward_returns, dtype=np.float64)
    target = _one_hot(y)
    brier = float(np.sum((p - target) ** 2, axis=1).mean())
    log_loss = float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1.0)).mean())
    accuracy = float((p.argmax(axis=1) == y).mean())
    actions = [_action(row, config) for row in p]
    taken = [index for index, (action, _, _) in enumerate(actions) if action != "abstain"]
    cost = cost_bps / 10_000.0
    net_returns: list[float] = []
    direction_hits = 0
    for index in taken:
        signed = returns[index] if actions[index][0] == "long" else -returns[index]
        net_returns.append(float(signed - cost))
        if signed > 0:
            direction_hits += 1
    bins: list[dict[str, Any]] = []
    predicted_class = p.argmax(axis=1)
    confidence = p[np.arange(len(y)), predicted_class]
    correct = (predicted_class == y).astype(np.float64)
    ece = 0.0
    for bucket in range(5):
        mask = np.array([_bucket(value) == bucket for value in confidence])
        count = int(mask.sum())
        mean_conf = float(confidence[mask].mean()) if count else 0.0
        observed = float(correct[mask].mean()) if count else 0.0
        if count:
            ece += count / len(y) * abs(mean_conf - observed)
        bins.append(
            {
                "lower": round(bucket / 5, 2),
                "upper": round((bucket + 1) / 5, 2),
                "count": count,
                "mean_confidence": round(mean_conf, 6) if count else None,
                "observed_accuracy": round(observed, 6) if count else None,
            }
        )
    return {
        "rows": int(len(y)),
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "accuracy": round(accuracy, 6),
        "coverage": round(len(taken) / len(y), 6) if len(y) else 0.0,
        "taken": len(taken),
        "direction_hits": direction_hits,
        "direction_accuracy": round(direction_hits / len(taken), 6) if taken else None,
        "mean_net_return": round(float(np.mean(net_returns)), 8) if net_returns else None,
        "cumulative_net_return": round(float(np.sum(net_returns)), 8) if net_returns else None,
        "cost_bps": cost_bps,
        "expected_calibration_error": round(ece, 6),
        "calibration_bins": bins,
        "execution": "not_attempted",
        "execution_permission": "none",
    }


def _dataset_fingerprint(rows: Sequence[FeatureRow], symbol: str, config: SliceConfig) -> str:
    digest = hashlib.sha256()
    digest.update(symbol.encode("utf-8"))
    digest.update(json.dumps(config.as_dict(), sort_keys=True).encode("utf-8"))
    for row in rows:
        digest.update(row.decision_time.isoformat().encode("ascii"))
        digest.update(np.asarray(row.features, dtype=np.float64).tobytes())
        if row.label is not None:
            digest.update(bytes([row.label]))
    return digest.hexdigest()


def purged_walk_forward_model_selection_by_rows(
    rows: Sequence[FeatureRow],
    symbol: str,
    *,
    cost_bps: float,
    config: SliceConfig,
    feature_names: Sequence[str] = FEATURE_NAMES,
    collect_rows: bool = False,
) -> dict[str, Any]:
    """Compare candidates on purged expanding-window model-selection folds.

    Every candidate, including the frequency baseline, is fitted on that fold's
    training labels only. Pooled OOS comparison selects a candidate; it is not an
    independent evaluation of the selected model or deployment approval.
    """
    resolved = [row for row in rows if row.resolved]
    total = len(resolved)
    if total < config.min_train_rows + 5:
        return {
            "status": "insufficient_history",
            "required_rows": config.min_train_rows + 5,
            "available_rows": total,
            "notice": "The slice will not report walk-forward metrics without enough resolved labels.",
        }
    predictions: list[np.ndarray] = []
    frequency_predictions: list[np.ndarray] = []
    xgb_predictions: list[np.ndarray] = []
    labels: list[int] = []
    returns: list[float] = []
    prediction_rows: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    xgb_errors: list[str] = []
    xgb = getattr(sys.modules.get("atlas.research.vertical_slice"), "_xgboost_module", _xgboost_module)()
    xgb_version = None if xgb is None else str(getattr(xgb, "__version__", "unknown"))
    train_floor = config.min_train_rows
    remaining = total - train_floor
    block = max(5, remaining // max(1, config.walk_forward_splits))
    dataset_hash = _dataset_fingerprint(resolved, symbol, config)
    for fold in range(config.walk_forward_splits):
        test_start = train_floor + fold * block
        if test_start >= total:
            break
        test_end = min(total, test_start + block)
        # A row at index i resolves at i + horizon. Anything at or after
        # test_start - horizon can share bars with the test decision.
        train_end = test_start - config.purge() - config.embargo_steps
        if train_end < train_floor:
            continue
        train_rows = resolved[:train_end]
        test_rows = resolved[test_start:test_end]
        if not train_rows or not test_rows:
            continue
        # Freeze the class prior before any test outcomes are scored. Fitting a
        # single prior to the pooled test labels would give the baseline future
        # information unavailable to the other candidates.
        frequency = _frequency_baseline([int(row.label) for row in train_rows])
        fold_frequency_predictions = np.tile(frequency, (len(test_rows), 1))
        frequency_predictions.extend(fold_frequency_predictions)
        _fit_sm = getattr(sys.modules.get("atlas.research.vertical_slice"), "fit_softmax", fit_softmax)
        model = _fit_sm(
            [row.features for row in train_rows],
            [int(row.label) for row in train_rows],
            feature_names=feature_names,
            l2=config.l2,
            epochs=config.epochs,
            learning_rate=config.learning_rate,
            seed=config.seed + fold,
            dataset_hash=dataset_hash,
        )
        probabilities = model.predict_many(np.asarray([row.features for row in test_rows]))
        predictions.extend(probabilities)
        labels.extend(int(row.label) for row in test_rows)
        returns.extend(float(row.forward_return) for row in test_rows)
        if collect_rows:
            prediction_rows.extend(
                {
                    "decision_time": row.decision_time.isoformat(),
                    "label": int(row.label),
                    "forward_return": float(row.forward_return),
                    "probabilities": [float(value) for value in probability],
                    "frequency_baseline_probabilities": [float(value) for value in frequency],
                }
                for row, probability in zip(test_rows, probabilities)
            )
        if xgb is not None and not xgb_errors:
            try:
                challenger = fit_xgboost(
                    [row.features for row in train_rows],
                    [int(row.label) for row in train_rows],
                    feature_names=feature_names,
                    seed=config.seed + fold,
                    dataset_hash=dataset_hash,
                )
                if challenger is None:
                    xgb_errors.append("insufficient_class_diversity")
                    xgb_predictions.clear()
                else:
                    xgb_predictions.extend(
                        challenger.predict_many(np.asarray([row.features for row in test_rows]))
                    )
            except Exception as exc:
                xgb_errors.append(f"{type(exc).__name__}: {exc}")
                xgb_predictions.clear()
        folds.append(
            {
                "fold": fold,
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
                "train_last_decision": train_rows[-1].decision_time.isoformat(),
                "train_last_target": train_rows[-1].target_time.isoformat(),
                "test_first_decision": test_rows[0].decision_time.isoformat(),
                "frequency_baseline_probabilities": [float(value) for value in frequency],
                "purged_steps": config.purge(),
                "embargo_steps": config.embargo_steps,
                "no_label_overlap": train_rows[-1].target_time < test_rows[0].decision_time,
            }
        )
    if not predictions:
        return {
            "status": "insufficient_history",
            "available_rows": total,
            "notice": "No fold had enough training rows after purging.",
        }
    matrix = np.asarray(predictions)
    softmax_metrics = evaluate_predictions(
        matrix, labels, returns, cost_bps=cost_bps, config=config
    )
    frequency_metrics = evaluate_predictions(
        np.asarray(frequency_predictions), labels, returns, cost_bps=cost_bps, config=config
    )
    uniform_metrics = evaluate_predictions(
        np.full((len(labels), 3), 1.0 / 3.0),
        labels,
        returns,
        cost_bps=cost_bps,
        config=config,
    )
    if xgb is None:
        challenger: dict[str, Any] = {
            "name": "xgboost",
            "status": "unavailable",
            "version": None,
            "reason": "Package is not installed; no challenger metrics are reported.",
        }
    elif xgb_errors:
        challenger = {
            "name": "xgboost",
            "status": "failed",
            "version": xgb_version,
            "reason": xgb_errors[-1],
        }
    elif len(xgb_predictions) == len(labels):
        challenger = {
            "name": "xgboost",
            "status": "scored",
            "version": xgb_version,
            "model_family": XGBOOST_FAMILY,
            "model": evaluate_predictions(
                np.asarray(xgb_predictions),
                labels,
                returns,
                cost_bps=cost_bps,
                config=config,
            ),
        }
    else:
        challenger = {
            "name": "xgboost",
            "status": "failed",
            "version": xgb_version,
            "reason": "Challenger predictions did not align with test rows.",
        }
    candidates: list[tuple[str, dict[str, Any]]] = [
        (MODEL_FAMILY, softmax_metrics),
        ("frequency_baseline", frequency_metrics),
        ("uniform_baseline", uniform_metrics),
    ]
    if challenger["status"] == "scored":
        candidates.append((XGBOOST_FAMILY, challenger["model"]))
    primary_family, primary_metrics = min(
        candidates,
        key=lambda item: (
            float(item[1]["brier_score"]),
            float(item[1]["log_loss"]),
        ),
    )
    return {
        "status": "scored",
        "model": softmax_metrics,
        "primary_model_family": primary_family,
        "primary_metrics": primary_metrics,
        "selection": {
            "primary_model_family": primary_family,
            "reason": "lowest_walk_forward_brier_then_log_loss",
            "comparison_metric": "brier_score_then_log_loss",
            "evaluation_scope": "pooled_walk_forward_model_selection",
            "independent_validation": False,
        },
        "xgboost_challenger": challenger,
        "frequency_baseline": frequency_metrics,
        "uniform_baseline": uniform_metrics,
        "folds": folds,
        "dataset_hash": dataset_hash,
        **({"prediction_rows": prediction_rows} if collect_rows else {}),
        "notice": (
            "Walk-forward rows are predictions made before their outcomes. "
            "Brier/log loss measure probabilities; net return includes the "
            "track round-trip cost and is not an executed P&L. Model selection "
            "uses pooled purged walk-forward folds with train-only class priors. "
            "These folds are model-selection evidence, not independent validation "
            "of the winner or deployment approval."
        ),
    }


# Deprecated name; use ``purged_walk_forward_model_selection_by_rows`` (fits and scores candidates). Callers in this module keep using the old global name so tests that monkeypatch it still apply.
purged_walk_forward = purged_walk_forward_model_selection_by_rows


def _drop_feature_columns(
    rows: Sequence[FeatureRow],
    drop_indices: set[int],
    feature_count: int,
) -> list[FeatureRow]:
    keep = [index for index in range(feature_count) if index not in drop_indices]
    return [
        FeatureRow(
            features=tuple(row.features[index] for index in keep),
            decision_time=row.decision_time,
            target_time=row.target_time,
            reference_price=row.reference_price,
            target_price=row.target_price,
            forward_return=row.forward_return,
            label=row.label,
        )
        for row in rows
    ]


def _regime_labels(
    rows: Sequence[FeatureRow],
    feature_names: Sequence[str],
) -> dict[str, str]:
    """Label each decision with a causal volatility/trend regime.

    The volatility threshold is the median of the trailing (up to 60) decisions,
    so the label never uses a later bar. This is descriptive research metadata,
    not a validated regime classifier or a trading signal.
    """
    names = tuple(feature_names)
    if "realized_vol_5" not in names or "return_10" not in names:
        return {}
    vol_index = names.index("realized_vol_5")
    return_index = names.index("return_10")
    history: list[float] = []
    labels: dict[str, str] = {}
    for row in sorted((item for item in rows if item.resolved), key=lambda item: item.decision_time):
        volatility = float(row.features[vol_index])
        prior = history[-60:]
        median = float(np.median(prior)) if len(prior) >= 5 else None
        high_vol = median is not None and volatility >= median
        direction = "up" if float(row.features[return_index]) >= 0 else "down"
        labels[row.decision_time.isoformat()] = (
            f"{direction}_{'high' if high_vol else 'low'}_vol"
        )
        history.append(volatility)
    return labels


def _regime_metrics(
    prediction_rows: Sequence[dict[str, Any]],
    regime_labels: dict[str, str],
    *,
    cost_bps: float,
    config: SliceConfig,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in prediction_rows:
        regime = regime_labels.get(str(row.get("decision_time")))
        if regime:
            groups.setdefault(regime, []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for regime, group in sorted(groups.items()):
        if len(group) < 5:
            result[regime] = {
                "status": "insufficient",
                "rows": len(group),
                "notice": "Fewer than five out-of-sample rows in this regime.",
                "execution_permission": "none",
            }
            continue
        result[regime] = {
            "status": "scored",
            "rows": len(group),
            "metrics": evaluate_predictions(
                np.asarray([row["probabilities"] for row in group], dtype=np.float64),
                [int(row["label"]) for row in group],
                [float(row["forward_return"]) for row in group],
                cost_bps=cost_bps,
                config=config,
            ),
            "execution_permission": "none",
        }
    return result


def ablate_feature_families(
    rows: Sequence[FeatureRow],
    symbol: str,
    *,
    cost_bps: float,
    config: SliceConfig,
    feature_names: Sequence[str] = FEATURE_NAMES,
    families: Sequence[str] | None = None,
    include_regimes: bool = False,
) -> dict[str, Any]:
    """Measure each feature family by retraining with that family removed.

    Every ablation uses the same purged expanding walk-forward and the same
    labels as the baseline. A family is only evidence-supported when removing
    it makes out-of-sample Brier/log loss worse; otherwise the result is
    inconclusive or negative. This is not a profitability claim.
    """
    names = tuple(feature_names)
    wanted = tuple(families or FEATURE_FAMILIES.keys())
    _pwf = getattr(sys.modules.get("atlas.research.vertical_slice"), "purged_walk_forward", purged_walk_forward)
    baseline = _pwf(
        rows,
        symbol,
        cost_bps=cost_bps,
        config=config,
        feature_names=names,
        collect_rows=include_regimes,
    )
    baseline_softmax = baseline.get("model") or {}
    regime_labels = _regime_labels(rows, names) if include_regimes else {}
    payload: dict[str, Any] = {
        "status": baseline.get("status", "unavailable"),
        "symbol": symbol.upper(),
        "config": config.as_dict(),
        "feature_names": list(names),
        "families": {
            family: list(members)
            for family, members in FEATURE_FAMILIES.items()
        },
        "baseline": {
            "primary_model_family": baseline.get("primary_model_family"),
            "primary_metrics": baseline.get("primary_metrics"),
            "softmax_metrics": baseline_softmax or None,
            **(
                {
                    "regime_metrics": _regime_metrics(
                        baseline.get("prediction_rows") or [],
                        regime_labels,
                        cost_bps=cost_bps,
                        config=config,
                    )
                }
                if include_regimes
                else {}
            ),
        },
        **({"regimes": sorted(set(regime_labels.values()))} if include_regimes else {}),
        "ablations": [],
        "notice": (
            "Each row retrains the softmax model without one feature family on "
            "the same purged walk-forward folds. Positive delta_brier_removed "
            "means removing the family made Brier worse, so the family carried "
            "out-of-sample information. Small deltas are inconclusive. Regime "
            "breakdowns, when present, are descriptive trailing thresholds, not "
            "a validated regime classifier. This is research evidence, not a "
            "profitability or live-trading claim."
        ),
        "execution_permission": "none",
    }
    if baseline.get("status") != "scored":
        return payload
    baseline_brier = float(baseline_softmax.get("brier_score") or 0.0)
    baseline_log_loss = float(baseline_softmax.get("log_loss") or 0.0)
    baseline_accuracy = float(baseline_softmax.get("accuracy") or 0.0)
    for family in wanted:
        members = tuple(
            name for name in FEATURE_FAMILIES.get(family, ()) if name in names
        )
        if not members:
            payload["ablations"].append(
                {
                    "family": family,
                    "status": "unknown_or_absent",
                    "removed_features": [],
                    "execution_permission": "none",
                }
            )
            continue
        drop_indices = {names.index(name) for name in members}
        remaining_names = tuple(name for name in names if name not in members)
        ablated = _pwf(
            _drop_feature_columns(rows, drop_indices, len(names)),
            symbol,
            cost_bps=cost_bps,
            config=config,
            feature_names=remaining_names,
            collect_rows=include_regimes,
        )
        metrics = ablated.get("model") or {}
        if ablated.get("status") != "scored" or not metrics:
            payload["ablations"].append(
                {
                    "family": family,
                    "status": ablated.get("status", "unavailable"),
                    "removed_features": list(members),
                    "remaining_features": list(remaining_names),
                    "execution_permission": "none",
                }
            )
            continue
        brier = float(metrics.get("brier_score") or 0.0)
        log_loss = float(metrics.get("log_loss") or 0.0)
        accuracy = float(metrics.get("accuracy") or 0.0)
        delta_brier = brier - baseline_brier
        delta_log_loss = log_loss - baseline_log_loss
        delta_accuracy = accuracy - baseline_accuracy
        if delta_brier > 0.005:
            evidence = "removal_worsened"
        elif delta_brier < -0.005:
            evidence = "removal_improved"
        else:
            evidence = "inconclusive"
        payload["ablations"].append(
            {
                "family": family,
                "status": "scored",
                "removed_features": list(members),
                "remaining_features": list(remaining_names),
                "metrics": metrics,
                "delta_brier_removed": round(delta_brier, 8),
                "delta_log_loss_removed": round(delta_log_loss, 8),
                "delta_accuracy_removed": round(delta_accuracy, 8),
                "evidence": evidence,
                **(
                    {
                        "regime_metrics": _regime_metrics(
                            ablated.get("prediction_rows") or [],
                            regime_labels,
                            cost_bps=cost_bps,
                            config=config,
                        )
                    }
                    if include_regimes
                    else {}
                ),
                "execution_permission": "none",
            }
        )
    payload["status"] = "measured"
    return payload


def optional_gbdt_status() -> list[dict[str, Any]]:
    """Report optional challengers honestly; never fabricate a run."""
    status: list[dict[str, Any]] = []
    for name in ("xgboost", "lightgbm"):
        try:
            module = __import__(name)
            status.append(
                {
                    "name": name,
                    "status": "available",
                    "version": getattr(module, "__version__", "unknown"),
                    "reason": "Trained as a challenger on the same purged walk-forward folds when enough history exists.",
                }
            )
        except ImportError:
            status.append(
                {
                    "name": name,
                    "status": "unavailable",
                    "version": None,
                    "reason": "Package is not installed; no challenger metrics are reported.",
                }
            )
    return status
