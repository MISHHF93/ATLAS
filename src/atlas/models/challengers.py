"""Deterministic local tree challenger, purged walk-forward study, and feature ablations.

Training produces an immutable research challenger only (`execution_permission: none`).
No automatic promotion, live weight mutation, or ensemble combiner is enabled.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from statistics import mean
from typing import Literal

from atlas.marketdata.frozen import FrozenDatasetBundle, build_frozen_benchmark_dataset
from atlas.models.evaluation import EvaluationReport, EvaluationRow, evaluate, evaluate_groups
from atlas.models.regimes import RegimeConfig, classify_regime
from atlas.models.schemas import (
    Capability,
    Forecast,
    ForecastPoint,
    ForecastRequest,
    ModelRecord,
    ModelRef,
    Observation,
    ProviderInfo,
    Record,
    Text,
    Usage,
)


class TreeSplitNode(Record):
    feature_index: int
    threshold: float
    left_value: float
    right_value: float


class FittedRegressionTree(Record):
    tree_id: Text
    dataset_id: Text
    trained_through: datetime
    nodes: tuple[TreeSplitNode, ...]
    learning_rate: float = 0.5
    base_prediction: float = 0.0

    def predict_return(self, features: tuple[float, ...]) -> float:
        pred = self.base_prediction
        for node in self.nodes:
            val = features[node.feature_index]
            step = node.left_value if val <= node.threshold else node.right_value
            pred += self.learning_rate * step
        return max(-0.25, min(0.25, pred))


def _extract_causal_features(observations: tuple[Observation, ...]) -> tuple[float, float, float]:
    """Compute causal (lag_1_return, lag_2_return, rolling_abs_return) from available observations."""
    if len(observations) < 4:
        return (0.0, 0.0, 0.0)
    r1 = (observations[-1].value - observations[-2].value) / observations[-2].value
    r2 = (observations[-2].value - observations[-3].value) / observations[-3].value
    r3 = (observations[-3].value - observations[-4].value) / observations[-4].value
    vol = (abs(r1) + abs(r2) + abs(r3)) / 3.0
    return (r1, r2, vol)


def fit_boosted_regression_tree(
    observations: tuple[Observation, ...],
    *,
    dataset_id: str,
    boost_rounds: int = 3,
    learning_rate: float = 0.5,
    active_feature_indices: tuple[int, ...] = (0, 1, 2),
) -> FittedRegressionTree:
    """Fit a deterministic boosted decision-stump tree on chronological observations."""
    if len(observations) < 8:
        raise ValueError("Need at least 8 chronological observations to fit tree challenger")
    if not active_feature_indices:
        raise ValueError("active_feature_indices cannot be empty")

    X: list[tuple[float, float, float]] = []
    y: list[float] = []
    for idx in range(4, len(observations) - 1):
        history = observations[: idx + 1]
        target_ret = (observations[idx + 1].value - observations[idx].value) / observations[idx].value
        X.append(_extract_causal_features(history))
        y.append(target_ret)

    base_pred = mean(y)
    residuals = [target - base_pred for target in y]
    nodes: list[TreeSplitNode] = []

    for _ in range(boost_rounds):
        best_loss = float("inf")
        best_node = TreeSplitNode(feature_index=active_feature_indices[0], threshold=0.0, left_value=0.0, right_value=0.0)
        for feat_idx in active_feature_indices:
            candidates = sorted({row[feat_idx] for row in X})
            for threshold in candidates:
                left_res = [residuals[i] for i, row in enumerate(X) if row[feat_idx] <= threshold]
                right_res = [residuals[i] for i, row in enumerate(X) if row[feat_idx] > threshold]
                if not left_res or not right_res:
                    continue
                left_mean = mean(left_res)
                right_mean = mean(right_res)
                loss = sum((r - left_mean) ** 2 for r in left_res) + sum(
                    (r - right_mean) ** 2 for r in right_res
                )
                if loss < best_loss:
                    best_loss = loss
                    best_node = TreeSplitNode(
                        feature_index=feat_idx,
                        threshold=threshold,
                        left_value=left_mean,
                        right_value=right_mean,
                    )
        nodes.append(best_node)
        for i, row in enumerate(X):
            step = (
                best_node.left_value
                if row[best_node.feature_index] <= best_node.threshold
                else best_node.right_value
            )
            residuals[i] -= learning_rate * step

    return FittedRegressionTree(
        tree_id=f"boosted_stump_tree:{dataset_id}",
        dataset_id=dataset_id,
        trained_through=observations[-1].available_at,
        nodes=tuple(nodes),
        learning_rate=learning_rate,
        base_prediction=base_pred,
    )


class LocalTreeChallengerProvider:
    """Deterministic local tree ForecastProvider. Never mutates weights during inference."""

    def __init__(self, fitted_tree: FittedRegressionTree | None = None) -> None:
        self._tree = fitted_tree

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="local_tree",
            location="local",
            capabilities=frozenset({Capability.FORECAST}),
            models=("boosted_stump_v1",),
        )

    async def forecast(self, model: ModelRef, request: ForecastRequest) -> Forecast:
        if model.provider_id != "local_tree" or model.model_id != "boosted_stump_v1":
            raise ValueError("Unknown local_tree model")
        tree = self._tree or fit_boosted_regression_tree(
            request.observations if len(request.observations) >= 8 else build_frozen_benchmark_dataset().observations[:24],
            dataset_id=request.dataset_id,
        )
        if tree.trained_through > request.as_of:
            raise ValueError("Tree challenger trained_through exceeds request.as_of (lookahead leakage)")

        features = _extract_causal_features(request.observations)
        pred_return = tree.predict_return(features)
        last_val = request.observations[-1].value

        points: list[ForecastPoint] = []
        current_price = last_val
        for step_idx, stamp in enumerate(request.target_times, start=1):
            if request.target == "return":
                point_val = pred_return
                spread = max(0.002, abs(features[2]) * 1.96)
            else:
                current_price = current_price * (1.0 + pred_return)
                point_val = current_price
                spread = max(0.5, current_price * max(0.005, abs(features[2]) * 1.96) * (step_idx ** 0.5))
            points.append(
                ForecastPoint(
                    timestamp=stamp,
                    value=round(point_val, 6),
                    lower=round(point_val - spread, 6),
                    upper=round(point_val + spread, 6),
                    interval_coverage=0.95,
                )
            )
        prob_up = min(0.95, max(0.05, 0.5 + pred_return * 25.0))
        return Forecast(
            request_id=request.request_id,
            model=model,
            instrument_id=request.instrument_id,
            horizon_id=request.horizon_id,
            target=request.target,
            unit=request.unit,
            data_as_of=request.as_of,
            generated_at=datetime.now(timezone.utc),
            points=tuple(points),
            probability_up=round(prob_up, 4),
            usage=Usage(cost_usd=Decimal("0"), cost_kind="estimated"),
        )


class OutcomeFeedbackRecord(Record):
    """Measured evaluation feedback that triggers a next challenger experiment without auto-promotion."""
    feedback_id: Text
    track: Literal["competition", "open_market"]
    dataset_id: Text
    challenger_model: ModelRef
    beats_naive_mae: bool
    beats_no_trade_net_return: bool
    recommended_next_action: Literal[
        "submit_for_human_scoped_review",
        "retain_baseline_and_collect_more_regime_samples",
    ]
    auto_promoted: Literal[False] = False
    weights_mutated_in_place: Literal[False] = False
    execution_permission: Literal["none"] = "none"


class WalkForwardStudyResult(Record):
    study_id: Text
    track: Literal["competition", "open_market"]
    competition_rulebook_ref: Text | None = None
    dataset_id: Text
    manifest_sha256: Text
    purge_bars: int
    embargo_bars: int
    challenger_record: ModelRecord
    overall_report: EvaluationReport
    regime_reports: dict[str, EvaluationReport | None]
    feedback: OutcomeFeedbackRecord
    execution_permission: Literal["none"] = "none"


def run_baseline_vs_tree_study(
    bundle: FrozenDatasetBundle | None = None,
    *,
    purge_bars: int = 1,
    embargo_bars: int = 1,
    cost_bps: float = 4.0,
    active_feature_indices: tuple[int, ...] = (0, 1, 2),
) -> WalkForwardStudyResult:
    """Run a purged chronological walk-forward comparison of Naive vs Local Tree Challenger."""
    if purge_bars < 1 or embargo_bars < 0:
        raise ValueError("Walk-forward study requires purge_bars >= 1 and embargo_bars >= 0")
    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    active_bundle.manifest.verify_content(active_bundle.serialized_bytes)

    obs = active_bundle.observations
    train_obs = tuple(o for o in obs if o.available_at <= active_bundle.manifest.train_end)
    tree = fit_boosted_regression_tree(
        train_obs,
        dataset_id=active_bundle.manifest.dataset_id,
        active_feature_indices=active_feature_indices,
    )

    tree_bytes = json.dumps(tree.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    tree_hash = hashlib.sha256(tree_bytes).hexdigest()
    challenger_ref = ModelRef(provider_id="local_tree", model_id="boosted_stump_v1", revision="1")
    challenger_record = ModelRecord(
        model=challenger_ref,
        artifact_uri=f"memory://challengers/{tree.tree_id}",
        artifact_sha256=tree_hash,
        dataset_id=active_bundle.manifest.dataset_id,
        experiment_id=f"exp:wf:{active_bundle.track}:v1",
        license_ref=active_bundle.manifest.license_refs[0],
        commercial_use_verified=True,
    )

    # Start evaluation after train split + purge + embargo bars
    start_idx = len(train_obs) + purge_bars + embargo_bars
    eval_rows: list[EvaluationRow] = []
    regime_cfg = RegimeConfig(min_observations=5)
    fractional_cost = cost_bps / 10_000.0

    for idx in range(start_idx, len(obs) - 1):
        history = obs[: idx + 1]
        current_obs = obs[idx]
        next_obs = obs[idx + 1]
        feats = _extract_causal_features(history)
        pred_ret = tree.predict_return(feats)
        pred_price = current_obs.value * (1.0 + pred_ret)
        naive_price = current_obs.value
        actual_ret = (next_obs.value - current_obs.value) / current_obs.value

        regime_state = classify_regime(
            as_of=current_obs.available_at,
            instrument_id=active_bundle.instrument.instrument_id,
            observations=history[-8:],
            config=regime_cfg,
            calendar=active_bundle.calendar,
            liquidity_score=0.82,
            spread_bps=cost_bps,
        )
        position = 1.0 if pred_ret > fractional_cost else (-1.0 if pred_ret < -fractional_cost else 0.0)
        tx_cost = fractional_cost if position != 0.0 else 0.0
        prob_up = min(0.95, max(0.05, 0.5 + pred_ret * 25.0))

        eval_rows.append(
            EvaluationRow(
                timestamp=next_obs.event_time,
                actual=next_obs.value,
                predicted=pred_price,
                naive=naive_price,
                actual_return=actual_ret,
                predicted_return=pred_ret,
                proposed_position=position,
                transaction_cost=tx_cost,
                probability_up=prob_up,
                regime=regime_state.volatility,
                instrument_id=active_bundle.instrument.instrument_id,
                horizon_id="1h:walk_forward:v1",
            )
        )

    overall = evaluate(eval_rows, block_size=2, bootstrap_samples=200, seed=42)
    by_regime = evaluate_groups(eval_rows, by="regime")

    beats_naive = overall.mae < overall.naive_mae
    beats_no_trade = overall.expected_net_return > overall.no_trade_return
    next_action: Literal[
        "submit_for_human_scoped_review",
        "retain_baseline_and_collect_more_regime_samples",
    ] = (
        "submit_for_human_scoped_review"
        if (beats_naive and beats_no_trade)
        else "retain_baseline_and_collect_more_regime_samples"
    )

    feedback = OutcomeFeedbackRecord(
        feedback_id=f"feedback:{active_bundle.track}:v1",
        track=active_bundle.track,
        dataset_id=active_bundle.manifest.dataset_id,
        challenger_model=challenger_ref,
        beats_naive_mae=beats_naive,
        beats_no_trade_net_return=beats_no_trade,
        recommended_next_action=next_action,
    )

    return WalkForwardStudyResult(
        study_id=f"wf-study:{active_bundle.track}:v1",
        track=active_bundle.track,
        competition_rulebook_ref=active_bundle.competition_rulebook_ref,
        dataset_id=active_bundle.manifest.dataset_id,
        manifest_sha256=active_bundle.manifest.content_sha256,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
        challenger_record=challenger_record,
        overall_report=overall,
        regime_reports=by_regime,
        feedback=feedback,
    )


class FeatureAblationVariant(Record):
    variant_name: Text
    active_features: tuple[Text, ...]
    mae: float
    naive_mae: float
    expected_net_return: float
    directional_accuracy: float


class AblationStudyResult(Record):
    study_id: Text
    track: Literal["competition", "open_market"]
    dataset_id: Text
    variants: tuple[FeatureAblationVariant, ...]
    execution_permission: Literal["none"] = "none"


def run_feature_ablation_study(
    bundle: FrozenDatasetBundle | None = None,
    *,
    cost_bps: float = 4.0,
) -> AblationStudyResult:
    """Compare full feature set vs lag-drop and volatility-drop ablations on identical frozen splits."""
    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    configs: tuple[tuple[str, tuple[str, ...], tuple[int, ...]], ...] = (
        ("full_features", ("lag_return_1", "lag_return_2", "rolling_vol_4"), (0, 1, 2)),
        ("drop_lag_1_ablation", ("lag_return_2", "rolling_vol_4"), (1, 2)),
        ("drop_volatility_ablation", ("lag_return_1", "lag_return_2"), (0, 1)),
        ("lag_1_only_baseline", ("lag_return_1",), (0,)),
    )
    variants: list[FeatureAblationVariant] = []
    for name, labels, indices in configs:
        study = run_baseline_vs_tree_study(
            active_bundle,
            purge_bars=1,
            embargo_bars=1,
            cost_bps=cost_bps,
            active_feature_indices=indices,
        )
        rep = study.overall_report
        variants.append(
            FeatureAblationVariant(
                variant_name=name,
                active_features=labels,
                mae=rep.mae,
                naive_mae=rep.naive_mae,
                expected_net_return=rep.expected_net_return,
                directional_accuracy=rep.directional_accuracy,
            )
        )
    return AblationStudyResult(
        study_id=f"ablation:{active_bundle.track}:v1",
        track=active_bundle.track,
        dataset_id=active_bundle.manifest.dataset_id,
        variants=tuple(variants),
    )
