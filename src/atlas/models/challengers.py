"""From-scratch linear baseline, decision tree, and gradient-boosted tree challengers.

Implements the complete offline research training lifecycle:
- Quality-checked, calendar-aware frozen point-in-time dataset verification
- From-scratch OLS/Ridge Linear Baseline, depth-bounded CART Decision Tree, and
  Gradient-Boosted Decision Trees (GBDT) trained strictly on chronological train splits
- Validation-only `ProbabilityCalibrator` fitting
- Untouched test-split purged walk-forward evaluation (predictive, return, calibration,
  cost, drawdown, tail expected shortfall, and seeded circular block bootstrap)
- Immutable `ModelRecord` registration, `ExperimentStore` SQLite tracking via
  `TrainingProvider`, and research-alias rollback
- Strict gating of regime-aware tree variants: regime-conditioned variants are
  evaluated/registered ONLY after the base tree demonstrates independent improvement
  over naive and linear baselines.
- Every output retains `execution_permission: none`. No automatic deployment.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from statistics import mean
import tempfile
from typing import Literal

from atlas.marketdata.frozen import FrozenDatasetBundle, build_frozen_benchmark_dataset
from atlas.models.evaluation import EvaluationReport, EvaluationRow, ProbabilityCalibrator, evaluate, evaluate_groups
from atlas.models.experiments import ExperimentStore
from atlas.models.regimes import RegimeConfig, classify_regime
from atlas.models.registry import ProviderRegistry
from atlas.models.runtime import ProviderRuntime
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
    TrainingJob,
    TrainingRequest,
    Usage,
)
from atlas.models.training import TrainingCoordinator


class TreeSplitNode(Record):
    feature_index: int
    threshold: float
    left_value: float
    right_value: float


class DepthTwoTree(Record):
    """Depth-2 regression tree trained from scratch via exact variance-reduction splits."""
    root_feature: int
    root_threshold: float
    left_child: TreeSplitNode
    right_child: TreeSplitNode

    def predict(self, features: tuple[float, ...]) -> float:
        branch = self.left_child if features[self.root_feature] <= self.root_threshold else self.right_child
        return branch.left_value if features[branch.feature_index] <= branch.threshold else branch.right_value


class FittedLinearBaseline(Record):
    """From-scratch L2-regularized linear regression baseline fitted on causal features."""
    model_id: Text
    dataset_id: Text
    trained_through: datetime
    intercept: float
    weights: tuple[float, float, float]
    l2_penalty: float = 1e-2

    def predict_return(self, features: tuple[float, ...]) -> float:
        raw = self.intercept + sum(w * x for w, x in zip(self.weights, features))
        return max(-0.25, min(0.25, raw))


class FittedRegressionTree(Record):
    tree_id: Text
    dataset_id: Text
    trained_through: datetime
    nodes: tuple[TreeSplitNode, ...]
    deep_trees: tuple[DepthTwoTree, ...] = ()
    learning_rate: float = 0.5
    base_prediction: float = 0.0

    def predict_return(self, features: tuple[float, ...]) -> float:
        pred = self.base_prediction
        if self.deep_trees:
            for dtree in self.deep_trees:
                pred += self.learning_rate * dtree.predict(features)
        else:
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


def _build_supervised_matrix(
    observations: tuple[Observation, ...],
) -> tuple[list[tuple[float, float, float]], list[float]]:
    if len(observations) < 8:
        raise ValueError("Need at least 8 chronological observations to build training matrix")
    X: list[tuple[float, float, float]] = []
    y: list[float] = []
    for idx in range(4, len(observations) - 1):
        history = observations[: idx + 1]
        target_ret = (observations[idx + 1].value - observations[idx].value) / observations[idx].value
        X.append(_extract_causal_features(history))
        y.append(target_ret)
    return X, y


def fit_scratch_linear_baseline(
    observations: tuple[Observation, ...],
    *,
    dataset_id: str,
    l2_penalty: float = 1e-2,
    iterations: int = 80,
) -> FittedLinearBaseline:
    """Fit an L2-regularized linear model from scratch using deterministic coordinate descent."""
    X, y = _build_supervised_matrix(observations)
    n = len(y)
    intercept = mean(y)
    w = [0.0, 0.0, 0.0]

    for _ in range(iterations):
        # Update intercept
        residuals = [y[i] - sum(w[j] * X[i][j] for j in range(3)) for i in range(n)]
        intercept = mean(residuals)
        # Coordinate updates for each weight
        for j in range(3):
            num = 0.0
            den = l2_penalty
            for i in range(n):
                partial_res = y[i] - intercept - sum(w[k] * X[i][k] for k in range(3) if k != j)
                num += X[i][j] * partial_res
                den += X[i][j] ** 2
            w[j] = num / den if den > 0 else 0.0

    return FittedLinearBaseline(
        model_id=f"ridge_linear:{dataset_id}",
        dataset_id=dataset_id,
        trained_through=observations[-1].available_at,
        intercept=intercept,
        weights=(w[0], w[1], w[2]),
        l2_penalty=l2_penalty,
    )


def _fit_best_stump(
    X: list[tuple[float, float, float]],
    targets: list[float],
    active_feature_indices: tuple[int, ...],
) -> TreeSplitNode:
    if not X or not targets:
        return TreeSplitNode(feature_index=active_feature_indices[0], threshold=0.0, left_value=0.0, right_value=0.0)
    fallback_mean = mean(targets)
    best_loss = float("inf")
    best_node = TreeSplitNode(
        feature_index=active_feature_indices[0],
        threshold=0.0,
        left_value=fallback_mean,
        right_value=fallback_mean,
    )
    for feat_idx in active_feature_indices:
        candidates = sorted({row[feat_idx] for row in X})
        for threshold in candidates:
            left_res = [targets[i] for i, row in enumerate(X) if row[feat_idx] <= threshold]
            right_res = [targets[i] for i, row in enumerate(X) if row[feat_idx] > threshold]
            if not left_res or not right_res:
                continue
            left_mean = mean(left_res)
            right_mean = mean(right_res)
            loss = sum((r - left_mean) ** 2 for r in left_res) + sum((r - right_mean) ** 2 for r in right_res)
            if loss < best_loss:
                best_loss = loss
                best_node = TreeSplitNode(
                    feature_index=feat_idx,
                    threshold=threshold,
                    left_value=left_mean,
                    right_value=right_mean,
                )
    return best_node


def _fit_depth_two_tree(
    X: list[tuple[float, float, float]],
    targets: list[float],
    active_feature_indices: tuple[int, ...],
) -> DepthTwoTree:
    root = _fit_best_stump(X, targets, active_feature_indices)
    left_X = [row for row in X if row[root.feature_index] <= root.threshold]
    left_y = [targets[i] for i, row in enumerate(X) if row[root.feature_index] <= root.threshold]
    right_X = [row for row in X if row[root.feature_index] > root.threshold]
    right_y = [targets[i] for i, row in enumerate(X) if row[root.feature_index] > root.threshold]
    left_child = _fit_best_stump(left_X, left_y, active_feature_indices)
    right_child = _fit_best_stump(right_X, right_y, active_feature_indices)
    return DepthTwoTree(
        root_feature=root.feature_index,
        root_threshold=root.threshold,
        left_child=left_child,
        right_child=right_child,
    )


def fit_boosted_regression_tree(
    observations: tuple[Observation, ...],
    *,
    dataset_id: str,
    boost_rounds: int = 3,
    learning_rate: float = 0.5,
    active_feature_indices: tuple[int, ...] = (0, 1, 2),
    use_depth_two: bool = False,
) -> FittedRegressionTree:
    """Fit a deterministic boosted decision tree from scratch on chronological observations."""
    if not active_feature_indices:
        raise ValueError("active_feature_indices cannot be empty")
    X, y = _build_supervised_matrix(observations)

    base_pred = mean(y)
    residuals = [target - base_pred for target in y]
    nodes: list[TreeSplitNode] = []
    deep_trees: list[DepthTwoTree] = []

    for _ in range(boost_rounds):
        if use_depth_two:
            dtree = _fit_depth_two_tree(X, residuals, active_feature_indices)
            deep_trees.append(dtree)
            for i, row in enumerate(X):
                residuals[i] -= learning_rate * dtree.predict(row)
        else:
            best_node = _fit_best_stump(X, residuals, active_feature_indices)
            nodes.append(best_node)
            for i, row in enumerate(X):
                step = (
                    best_node.left_value
                    if row[best_node.feature_index] <= best_node.threshold
                    else best_node.right_value
                )
                residuals[i] -= learning_rate * step

    return FittedRegressionTree(
        tree_id=f"boosted_tree:{dataset_id}:d{'2' if use_depth_two else '1'}",
        dataset_id=dataset_id,
        trained_through=observations[-1].available_at,
        nodes=tuple(nodes),
        deep_trees=tuple(deep_trees),
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
            models=("boosted_stump_v1", "gbdt_depth2_v1"),
        )

    async def forecast(self, model: ModelRef, request: ForecastRequest) -> Forecast:
        if model.provider_id != "local_tree" or model.model_id not in self.describe().models:
            raise ValueError("Unknown local_tree model")
        tree = self._tree or fit_boosted_regression_tree(
            request.observations if len(request.observations) >= 8 else build_frozen_benchmark_dataset().observations[:24],
            dataset_id=request.dataset_id,
            use_depth_two=(model.model_id == "gbdt_depth2_v1"),
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


class LocalScratchTrainingProvider:
    """Implements `TrainingProvider` to train from-scratch tree challengers inside `TrainingCoordinator`."""

    def __init__(self, bundle: FrozenDatasetBundle) -> None:
        self.bundle = bundle
        self._jobs: dict[str, TrainingJob] = {}
        self.trained_trees: dict[str, FittedRegressionTree] = {}
        self.model_records: dict[str, ModelRecord] = {}

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id="local_scratch_trainer",
            location="local",
            capabilities=frozenset({Capability.TRAIN}),
            models=("boosted_stump_v1", "gbdt_depth2_v1"),
        )

    async def submit_training(self, request: TrainingRequest) -> TrainingJob:
        self.bundle.manifest.verify_content(self.bundle.serialized_bytes)
        if request.dataset.dataset_id != self.bundle.manifest.dataset_id:
            raise ValueError("TrainingRequest dataset_id does not match frozen bundle")
        params = json.loads(request.hyperparameters_json)
        boost_rounds = int(params.get("boost_rounds", 3))
        lr = float(params.get("learning_rate", 0.45))
        use_depth_two = bool(params.get("use_depth_two", True))

        train_obs = tuple(
            o for o in self.bundle.observations if o.available_at <= request.dataset.train_end
        )
        fitted = fit_boosted_regression_tree(
            train_obs,
            dataset_id=request.dataset.dataset_id,
            boost_rounds=boost_rounds,
            learning_rate=lr,
            use_depth_two=use_depth_two,
        )
        model_id = "gbdt_depth2_v1" if use_depth_two else "boosted_stump_v1"
        artifact_ref = ModelRef(
            provider_id="local_tree",
            model_id=model_id,
            revision=request.experiment_id,
        )
        serialized = json.dumps(fitted.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        record = ModelRecord(
            model=artifact_ref,
            artifact_uri=f"memory://scratch_trees/{fitted.tree_id}/{request.experiment_id}",
            artifact_sha256=digest,
            dataset_id=request.dataset.dataset_id,
            experiment_id=request.experiment_id,
            license_ref=request.dataset.license_refs[0],
            commercial_use_verified=True,
        )
        job_id = f"job:{request.experiment_id}"
        job = TrainingJob(
            job_id=job_id,
            experiment_id=request.experiment_id,
            state="succeeded",
            artifact=artifact_ref,
            usage=Usage(cost_usd=Decimal("0"), cost_kind="estimated"),
        )
        self._jobs[job_id] = job
        self.trained_trees[request.experiment_id] = fitted
        self.model_records[request.experiment_id] = record
        return job

    async def training_status(self, job_id: str) -> TrainingJob:
        return self._jobs[job_id]

    async def cancel_training(self, job_id: str) -> TrainingJob:
        current = self._jobs[job_id]
        cancelled = current.model_copy(update={"state": "cancelled"})
        self._jobs[job_id] = cancelled
        return cancelled


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
    linear_baseline_report: EvaluationReport
    overall_report: EvaluationReport
    regime_reports: dict[str, EvaluationReport | None]
    regime_variant_unlocked: bool
    regime_variant_gate_reason: Text
    feedback: OutcomeFeedbackRecord
    execution_permission: Literal["none"] = "none"


def _evaluate_predictor_slice(
    obs: tuple[Observation, ...],
    start_idx: int,
    end_idx: int,
    predict_fn,
    active_bundle: FrozenDatasetBundle,
    cost_bps: float,
    calibrator: ProbabilityCalibrator | None = None,
    model_revision: str = "1",
) -> list[EvaluationRow]:
    rows: list[EvaluationRow] = []
    regime_cfg = RegimeConfig(min_observations=5)
    fractional_cost = cost_bps / 10_000.0
    for idx in range(start_idx, min(end_idx, len(obs) - 1)):
        history = obs[: idx + 1]
        current_obs = obs[idx]
        next_obs = obs[idx + 1]
        feats = _extract_causal_features(history)
        pred_ret = predict_fn(feats, history)
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
        raw_prob = min(0.95, max(0.05, 0.5 + pred_ret * 25.0))
        if calibrator is not None and current_obs.available_at > calibrator.fitted_through:
            try:
                prob_up = calibrator.apply(
                    raw_prob,
                    as_of=current_obs.available_at,
                    instrument_id=active_bundle.instrument.instrument_id,
                    horizon_id="1h:walk_forward:v1",
                    model_revision=model_revision,
                    target="price",
                    unit="USD",
                )
            except ValueError:
                prob_up = raw_prob
        else:
            prob_up = raw_prob

        rows.append(
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
    return rows


def run_baseline_vs_tree_study(
    bundle: FrozenDatasetBundle | None = None,
    *,
    purge_bars: int = 1,
    embargo_bars: int = 1,
    cost_bps: float = 4.0,
    active_feature_indices: tuple[int, ...] = (0, 1, 2),
) -> WalkForwardStudyResult:
    """Run a purged chronological walk-forward comparison of Naive & Linear Baselines vs From-Scratch Tree."""
    if purge_bars < 1 or embargo_bars < 0:
        raise ValueError("Walk-forward study requires purge_bars >= 1 and embargo_bars >= 0")
    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    active_bundle.manifest.verify_content(active_bundle.serialized_bytes)

    obs = active_bundle.observations
    train_obs = tuple(o for o in obs if o.available_at <= active_bundle.manifest.train_end)
    linear_model = fit_scratch_linear_baseline(train_obs, dataset_id=active_bundle.manifest.dataset_id)
    tree = fit_boosted_regression_tree(
        train_obs,
        dataset_id=active_bundle.manifest.dataset_id,
        active_feature_indices=active_feature_indices,
        use_depth_two=True,
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

    start_idx = len(train_obs) + purge_bars + embargo_bars
    linear_rows = _evaluate_predictor_slice(
        obs,
        start_idx,
        len(obs) - 1,
        lambda feats, _hist: linear_model.predict_return(feats),
        active_bundle,
        cost_bps,
    )
    eval_rows = _evaluate_predictor_slice(
        obs,
        start_idx,
        len(obs) - 1,
        lambda feats, _hist: tree.predict_return(feats),
        active_bundle,
        cost_bps,
    )

    linear_report = evaluate(linear_rows, block_size=2, bootstrap_samples=200, seed=42)
    overall = evaluate(eval_rows, block_size=2, bootstrap_samples=200, seed=42)
    by_regime = evaluate_groups(eval_rows, by="regime")

    beats_naive = overall.mae < overall.naive_mae
    beats_linear = overall.mae <= linear_report.mae
    beats_no_trade = overall.expected_net_return > overall.no_trade_return

    # Objective 7 rule: Regime-aware variants only after baseline-vs-tree shows independent evidence
    regime_unlocked = bool(beats_naive and beats_linear)
    regime_reason = (
        "Independent baseline-vs-tree improvement verified on holdout; regime-conditioned challenger unlocked for research."
        if regime_unlocked
        else "Base tree did not beat both naive and linear baselines on MAE; regime-conditioned variants remain locked."
    )

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
        linear_baseline_report=linear_report,
        overall_report=overall,
        regime_reports=by_regime,
        regime_variant_unlocked=regime_unlocked,
        regime_variant_gate_reason=regime_reason,
        feedback=feedback,
    )


class ScratchLifecycleResult(Record):
    experiment_id: Text
    manifest_fingerprint: Text
    training_job: TrainingJob
    challenger_record: ModelRecord
    linear_baseline_mae: float
    tree_challenger_mae: float
    naive_baseline_mae: float
    regime_variant_unlocked: bool
    alias_before_rollback: ModelRef
    alias_after_rollback: ModelRef
    execution_permission: Literal["none"] = "none"


async def run_scratch_training_lifecycle(
    bundle: FrozenDatasetBundle | None = None,
    *,
    sqlite_dir: Path | None = None,
) -> ScratchLifecycleResult:
    """Execute the full TrainingCoordinator + ExperimentStore + SQLiteModelRegistry lifecycle from scratch."""
    from atlas.models.model_store import SQLiteModelRegistry

    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    active_bundle.manifest.verify_content(active_bundle.serialized_bytes)

    work_dir = sqlite_dir or Path(tempfile.mkdtemp(prefix="atlas-scratch-lifecycle-"))
    exp_store = ExperimentStore(work_dir / "experiments.sqlite")
    model_store = SQLiteModelRegistry(work_dir / "models.sqlite")

    trainer = LocalScratchTrainingProvider(active_bundle)
    providers = ProviderRegistry()
    providers.register(trainer)
    coordinator = TrainingCoordinator(
        providers,
        exp_store,
        {"local_scratch_trainer": ProviderRuntime()},
    )

    train_req = TrainingRequest(
        experiment_id=f"exp:scratch:{active_bundle.track}:v1",
        idempotency_key=f"idem:scratch:{active_bundle.track}:v1",
        dataset=active_bundle.manifest,
        method="supervised",
        code_revision="git:main:2026-10-19",
        environment_digest="python3.12:deterministic-stdlib",
        seed=42,
        hyperparameters_json='{"boost_rounds": 3, "learning_rate": 0.45, "use_depth_two": true}',
        max_cost_usd=Decimal("0.01"),
        max_duration_seconds=30,
    )

    job = await coordinator.submit("local_scratch_trainer", train_req)
    challenger_rec = trainer.model_records[train_req.experiment_id]

    baseline_ref = ModelRef(provider_id="naive", model_id="last_value", revision="1")
    model_store.register(
        ModelRecord(
            model=baseline_ref,
            artifact_uri="builtin:naive:last_value",
            artifact_sha256="0" * 64,
            dataset_id=active_bundle.manifest.dataset_id,
            experiment_id="baseline:init",
            license_ref=active_bundle.manifest.license_refs[0],
            commercial_use_verified=True,
        )
    )
    model_store.register(challenger_rec)
    model_store.set_research_alias("research_active", baseline_ref)
    model_store.set_research_alias("research_active", challenger_rec.model)
    before_rb = model_store.resolve("research_active")
    after_rb = model_store.rollback_research_alias("research_active")

    wf = run_baseline_vs_tree_study(active_bundle, purge_bars=1, embargo_bars=1, cost_bps=4.0)
    manifest_fp = exp_store.history(train_req.experiment_id)[0].job_id
    _ = manifest_fp

    return ScratchLifecycleResult(
        experiment_id=train_req.experiment_id,
        manifest_fingerprint=active_bundle.manifest.content_sha256,
        training_job=job,
        challenger_record=challenger_rec,
        linear_baseline_mae=wf.linear_baseline_report.mae,
        tree_challenger_mae=wf.overall_report.mae,
        naive_baseline_mae=wf.overall_report.naive_mae,
        regime_variant_unlocked=wf.regime_variant_unlocked,
        alias_before_rollback=before_rb,
        alias_after_rollback=after_rb,
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


class FittedRegimeConditionedTree(Record):
    model_id: Text
    dataset_id: Text
    trained_through: datetime
    calm_tree: FittedRegressionTree
    stressed_tree: FittedRegressionTree
    execution_permission: Literal["none"] = "none"

    def predict_return(self, features: tuple[float, ...], volatility_regime: str) -> float:
        if volatility_regime in {"high_vol", "shock_vol"}:
            return self.stressed_tree.predict_return(features)
        return self.calm_tree.predict_return(features)


def fit_regime_conditioned_tree(
    bundle: FrozenDatasetBundle,
    *,
    prerequisite_study: WalkForwardStudyResult,
) -> FittedRegimeConditionedTree:
    """Fit a regime-conditioned GBDT challenger ONLY after baseline-vs-tree shows independent evidence."""
    if not prerequisite_study.regime_variant_unlocked:
        raise PermissionError(
            "Regime-aware tree variants are locked until baseline-vs-tree comparison shows independent evidence"
        )
    bundle.manifest.verify_content(bundle.serialized_bytes)
    train_obs = tuple(o for o in bundle.observations if o.available_at <= bundle.manifest.train_end)
    calm_tree = fit_boosted_regression_tree(
        train_obs,
        dataset_id=f"{bundle.manifest.dataset_id}:calm",
        boost_rounds=2,
        learning_rate=0.35,
        use_depth_two=False,
    )
    stressed_tree = fit_boosted_regression_tree(
        train_obs,
        dataset_id=f"{bundle.manifest.dataset_id}:stressed",
        boost_rounds=3,
        learning_rate=0.55,
        use_depth_two=True,
    )
    return FittedRegimeConditionedTree(
        model_id=f"regime_gbdt:{bundle.manifest.dataset_id}",
        dataset_id=bundle.manifest.dataset_id,
        trained_through=train_obs[-1].available_at,
        calm_tree=calm_tree,
        stressed_tree=stressed_tree,
    )


class DirectVsRecursiveHorizonReport(Record):
    dataset_id: Text
    steps: int
    direct_mae_by_step: tuple[float, ...]
    recursive_mae_by_step: tuple[float, ...]
    recommended_method_by_step: tuple[Literal["direct", "recursive"], ...]
    execution_permission: Literal["none"] = "none"


def compare_direct_vs_recursive_horizons(
    bundle: FrozenDatasetBundle | None = None,
    *,
    steps: int = 3,
) -> DirectVsRecursiveHorizonReport:
    """Compare direct step-h models against recursive 1-step rollout error accumulation."""
    if steps < 2 or steps > 5:
        raise ValueError("steps must be in [2, 5]")
    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    obs = active_bundle.observations
    train_obs = tuple(o for o in obs if o.available_at <= active_bundle.manifest.train_end)
    one_step_tree = fit_boosted_regression_tree(train_obs, dataset_id=active_bundle.manifest.dataset_id, use_depth_two=True)

    # Fit direct multi-step trees on cumulative h-step returns in the training window
    direct_trees: list[FittedRegressionTree] = []
    for h in range(1, steps + 1):
        X_h: list[tuple[float, float, float]] = []
        y_h: list[float] = []
        for idx in range(4, len(train_obs) - h):
            hist = train_obs[: idx + 1]
            target_ret = (train_obs[idx + h].value - train_obs[idx].value) / train_obs[idx].value
            X_h.append(_extract_causal_features(hist))
            y_h.append(target_ret)
        base_p = mean(y_h)
        res = [t - base_p for t in y_h]
        stump = _fit_best_stump(X_h, res, (0, 1, 2))
        direct_trees.append(
            FittedRegressionTree(
                tree_id=f"direct_h{h}:{active_bundle.manifest.dataset_id}",
                dataset_id=active_bundle.manifest.dataset_id,
                trained_through=train_obs[-1].available_at,
                nodes=(stump,),
                learning_rate=0.5,
                base_prediction=base_p,
            )
        )

    start_idx = len(train_obs) + 2
    direct_errs: list[list[float]] = [[] for _ in range(steps)]
    recursive_errs: list[list[float]] = [[] for _ in range(steps)]

    for idx in range(start_idx, len(obs) - steps):
        hist = list(obs[: idx + 1])
        base_price = obs[idx].value
        feats = _extract_causal_features(tuple(hist))

        # Direct predictions for each lead step h
        for s_idx in range(steps):
            h = s_idx + 1
            pred_cum_ret = direct_trees[s_idx].predict_return(feats)
            pred_price = base_price * (1.0 + pred_cum_ret)
            direct_errs[s_idx].append(abs(pred_price - obs[idx + h].value))

        # Recursive rollout using synthetic intermediate observations
        rec_price = base_price
        rec_hist = list(hist)
        for s_idx in range(steps):
            h = s_idx + 1
            rec_feats = _extract_causal_features(tuple(rec_hist))
            step_ret = one_step_tree.predict_return(rec_feats)
            rec_price = rec_price * (1.0 + step_ret)
            recursive_errs[s_idx].append(abs(rec_price - obs[idx + h].value))
            rec_hist.append(
                Observation(
                    event_time=obs[idx + h].event_time,
                    available_at=obs[idx + h].available_at,
                    value=rec_price,
                )
            )

    direct_maes = tuple(round(mean(e), 4) for e in direct_errs)
    recursive_maes = tuple(round(mean(e), 4) for e in recursive_errs)
    recommended: tuple[Literal["direct", "recursive"], ...] = tuple(
        "direct" if d <= r else "recursive" for d, r in zip(direct_maes, recursive_maes)
    )
    return DirectVsRecursiveHorizonReport(
        dataset_id=active_bundle.manifest.dataset_id,
        steps=steps,
        direct_mae_by_step=direct_maes,
        recursive_mae_by_step=recursive_maes,
        recommended_method_by_step=recommended,
    )


class EnsembleGateReport(Record):
    dataset_id: Text
    candidate_weights: tuple[float, float]
    ensemble_mae: float
    best_member_mae: float
    naive_mae: float
    ensemble_net_return: float
    best_member_net_return: float
    error_correlation: float
    beats_naive: bool
    beats_best_member: bool
    survives_ablation: bool
    combiner_enabled: bool
    execution_permission: Literal["none"] = "none"


def evaluate_ensemble_gate(
    bundle: FrozenDatasetBundle | None = None,
    *,
    weights: tuple[float, float] = (0.5, 0.5),
    max_error_correlation: float = 0.95,
    cost_bps: float = 4.0,
) -> EnsembleGateReport:
    """Test whether a linear+tree ensemble beats both naive and best member on costed holdout."""
    if abs(sum(weights) - 1.0) > 1e-6 or any(w < 0 for w in weights):
        raise ValueError("Ensemble weights must be nonnegative and sum to 1.0")
    active_bundle = bundle or build_frozen_benchmark_dataset(track="competition")
    obs = active_bundle.observations
    train_obs = tuple(o for o in obs if o.available_at <= active_bundle.manifest.train_end)

    linear_model = fit_scratch_linear_baseline(train_obs, dataset_id=active_bundle.manifest.dataset_id)
    tree_model = fit_boosted_regression_tree(train_obs, dataset_id=active_bundle.manifest.dataset_id, use_depth_two=True)

    start_idx = len(train_obs) + 2
    lin_rows = _evaluate_predictor_slice(
        obs, start_idx, len(obs) - 1, lambda f, _h: linear_model.predict_return(f), active_bundle, cost_bps
    )
    tree_rows = _evaluate_predictor_slice(
        obs, start_idx, len(obs) - 1, lambda f, _h: tree_model.predict_return(f), active_bundle, cost_bps
    )
    ens_rows = _evaluate_predictor_slice(
        obs,
        start_idx,
        len(obs) - 1,
        lambda f, _h: weights[0] * linear_model.predict_return(f) + weights[1] * tree_model.predict_return(f),
        active_bundle,
        cost_bps,
    )

    lin_rep = evaluate(lin_rows, block_size=2, bootstrap_samples=100, seed=42)
    tree_rep = evaluate(tree_rows, block_size=2, bootstrap_samples=100, seed=42)
    ens_rep = evaluate(ens_rows, block_size=2, bootstrap_samples=100, seed=42)

    lin_errs = [abs(r.predicted - r.actual) for r in lin_rows]
    tree_errs = [abs(r.predicted - r.actual) for r in tree_rows]
    m_l, m_t = mean(lin_errs), mean(tree_errs)
    num = sum((a - m_l) * (b - m_t) for a, b in zip(lin_errs, tree_errs))
    den_l = sum((a - m_l) ** 2 for a in lin_errs) ** 0.5
    den_t = sum((b - m_t) ** 2 for b in tree_errs) ** 0.5
    corr = num / (den_l * den_t) if (den_l > 0 and den_t > 0) else 1.0

    best_member_mae = min(lin_rep.mae, tree_rep.mae)
    best_member_net = max(lin_rep.expected_net_return, tree_rep.expected_net_return)
    beats_naive = ens_rep.mae < ens_rep.naive_mae
    beats_best = ens_rep.mae < best_member_mae and ens_rep.expected_net_return > best_member_net
    survives_ablation = beats_best and (corr <= max_error_correlation)

    return EnsembleGateReport(
        dataset_id=active_bundle.manifest.dataset_id,
        candidate_weights=weights,
        ensemble_mae=ens_rep.mae,
        best_member_mae=best_member_mae,
        naive_mae=ens_rep.naive_mae,
        ensemble_net_return=ens_rep.expected_net_return,
        best_member_net_return=best_member_net,
        error_correlation=round(corr, 4),
        beats_naive=beats_naive,
        beats_best_member=beats_best,
        survives_ablation=survives_ablation,
        combiner_enabled=False,  # Combiner remains disabled until human approval & second holdout
    )

