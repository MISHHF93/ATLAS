"""Offline metrics over aligned, non-overlapping research samples.

Returns are simple fractional returns, positions in [-1, 1], costs fractional.
No result in this module promotes a model or claims trading profitability.
"""
import math
import random
from statistics import mean
from typing import Sequence

from pydantic import AwareDatetime, Field, model_validator

from atlas.models.schemas import FiniteFloat, Forecast, Probability, Record, Text


class EvaluationRow(Record):
    timestamp: AwareDatetime
    actual: FiniteFloat
    predicted: FiniteFloat
    naive: FiniteFloat
    actual_return: FiniteFloat = Field(gt=-1)
    predicted_return: FiniteFloat
    proposed_position: float = Field(ge=-1, le=1, allow_inf_nan=False)
    transaction_cost: float = Field(ge=0, allow_inf_nan=False)
    probability_up: Probability | None = None
    regime: Text
    instrument_id: Text
    horizon_id: Text


class EvaluationReport(Record):
    samples: int
    mae: float
    rmse: float
    naive_mae: float
    return_rmse: float
    directional_accuracy: float
    brier_score: float | None
    expected_net_return: float
    no_trade_return: float = 0
    compounded_net_return: float
    max_drawdown: float
    expected_shortfall_95: float
    paired_mae_improvement_interval: tuple[float, float]
    significance_method: str = "seeded circular block bootstrap; exploratory 95% interval"


def evaluate(rows: Sequence[EvaluationRow], *, block_size: int = 2, bootstrap_samples: int = 500, seed: int = 0) -> EvaluationReport:
    if len(rows) < 4 or not 1 <= block_size <= len(rows) or bootstrap_samples < 100:
        raise ValueError("Need >=4 rows, a valid block size and >=100 bootstrap samples")
    stamps = [row.timestamp for row in rows]
    if stamps != sorted(set(stamps)):
        raise ValueError("Evaluation timestamps must be unique and ordered")
    if len({(r.instrument_id, r.horizon_id) for r in rows}) != 1:
        raise ValueError("Evaluate each instrument/horizon independently")
    errors = [abs(r.predicted - r.actual) for r in rows]
    naive_errors = [abs(r.naive - r.actual) for r in rows]
    # Cost supplied per period includes fees, spread, slippage, funding and turnover.
    net = [r.proposed_position * r.actual_return - r.transaction_cost for r in rows]
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in net:
        if value <= -1:
            raise ValueError("Net return <= -100%; bankruptcy needs a separate simulation")
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)
    probability_rows = [r for r in rows if r.probability_up is not None]
    if probability_rows and len(probability_rows) != len(rows):
        raise ValueError("Do not silently score a subset with probability outputs")
    improvements = [n - e for n, e in zip(naive_errors, errors)]
    rng = random.Random(seed)
    boot = []
    for _ in range(bootstrap_samples):
        sample = []
        while len(sample) < len(rows):
            start = rng.randrange(len(rows))
            sample.extend(improvements[(start + j) % len(rows)] for j in range(block_size))
        boot.append(mean(sample[:len(rows)]))
    boot.sort()
    sign = lambda value: (value > 0) - (value < 0)
    tail = sorted(net)[:max(1, math.ceil(len(net) * .05))]
    return EvaluationReport(
        samples=len(rows), mae=mean(errors), rmse=math.sqrt(mean((r.predicted-r.actual)**2 for r in rows)),
        naive_mae=mean(naive_errors), return_rmse=math.sqrt(mean((r.predicted_return-r.actual_return)**2 for r in rows)),
        directional_accuracy=mean(sign(r.predicted_return) == sign(r.actual_return) for r in rows),
        brier_score=mean((r.probability_up - float(r.actual_return > 0))**2 for r in probability_rows) if probability_rows else None,
        expected_net_return=mean(net), compounded_net_return=equity-1, max_drawdown=max_drawdown,
        expected_shortfall_95=-mean(tail), paired_mae_improvement_interval=(boot[int(.025*bootstrap_samples)], boot[min(bootstrap_samples-1, int(.975*bootstrap_samples))]),
    )


def evaluate_groups(rows: Sequence[EvaluationRow], *, by: str) -> dict[str, EvaluationReport | None]:
    if by not in {"regime", "instrument_id", "horizon_id"}:
        raise ValueError("Unsupported grouping")
    groups: dict[str, list[EvaluationRow]] = {}
    for row in rows:
        # Always preserve instrument and horizon boundaries.
        key = f"{row.instrument_id}|{row.horizon_id}|{getattr(row, by)}"
        groups.setdefault(key, []).append(row)
    return {key: evaluate(group) if len(group) >= 4 else None for key, group in groups.items()}


class ProbabilityCalibrator(Record):
    calibration_id: Text
    instrument_id: Text
    horizon_id: Text
    model_revision: Text
    target: Text
    unit: Text
    fitted_through: AwareDatetime
    bin_rates: tuple[Probability, ...] = Field(min_length=2)
    bin_counts: tuple[int, ...]

    @model_validator(mode="after")
    def valid_bins(self):
        if len(self.bin_counts) != len(self.bin_rates) or any(n < 0 for n in self.bin_counts):
            raise ValueError("Calibration counts must match bins")
        return self

    @classmethod
    def fit(cls, *, probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 5, **metadata):
        if len(probabilities) != len(outcomes) or len(probabilities) < 20 or bins < 2:
            raise ValueError("Calibration needs aligned samples (>=20) and >=2 bins")
        counts, positives = [0] * bins, [0] * bins
        for probability, outcome in zip(probabilities, outcomes):
            if not math.isfinite(probability) or not 0 <= probability <= 1 or outcome not in (0, 1):
                raise ValueError("Invalid calibration sample")
            index = min(bins-1, int(probability*bins))
            counts[index] += 1
            positives[index] += outcome
        # Beta(1,1) smoothing; sparse bins are explicitly rejected at inference.
        return cls(**metadata, bin_rates=tuple((p+1)/(n+2) for p, n in zip(positives, counts)), bin_counts=tuple(counts))

    def apply(self, probability: float, *, as_of, instrument_id: str, horizon_id: str, model_revision: str, target: str, unit: str) -> float:
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Invalid probability")
        if as_of <= self.fitted_through or (instrument_id, horizon_id, model_revision, target, unit) != (self.instrument_id, self.horizon_id, self.model_revision, self.target, self.unit):
            raise ValueError("Calibration leakage or scope mismatch")
        index = min(len(self.bin_rates)-1, int(probability*len(self.bin_rates)))
        if self.bin_counts[index] < 5:
            raise ValueError("Insufficient calibration support")
        return self.bin_rates[index]


class OperationalReport(Record):
    attempts: int
    availability: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    known_inference_cost_usd: str
    unknown_cost_attempts: int
    training_cost_usd: str | None
    data_license_ref: Text
    complexity_notes: Text


def evaluate_operations(events, *, training_cost_usd=None, data_license_ref: str, complexity_notes: str) -> OperationalReport:
    from decimal import Decimal
    latencies = sorted(event.latency_ms for event in events)
    known = sum((event.usage.cost_usd or Decimal(0) for event in events), Decimal(0))
    if training_cost_usd is not None:
        training_cost_usd = Decimal(str(training_cost_usd))
        if not training_cost_usd.is_finite() or training_cost_usd < 0:
            raise ValueError("Invalid training cost")
    percentile = lambda q: latencies[max(0, math.ceil(q*len(latencies))-1)] if latencies else None
    return OperationalReport(attempts=len(events),
        availability=mean(event.outcome == "ok" for event in events) if events else None,
        p50_latency_ms=percentile(.5), p95_latency_ms=percentile(.95),
        known_inference_cost_usd=str(known), unknown_cost_attempts=sum(event.usage.cost_usd is None for event in events),
        training_cost_usd=str(training_cost_usd) if training_cost_usd is not None else None,
        data_license_ref=data_license_ref, complexity_notes=complexity_notes)


class MultiHorizonLeadReport(Record):
    steps: int
    samples: int
    mae_by_step: tuple[float, ...]
    rmse_by_step: tuple[float, ...]
    joint_interval_coverage: float | None


def score_multi_output_forecasts(
    forecasts: Sequence[Forecast],
    actual_trajectories: Sequence[tuple[float, ...]],
) -> MultiHorizonLeadReport:
    """Score each lead step separately and compute joint interval coverage across all steps."""
    if not forecasts or len(forecasts) != len(actual_trajectories):
        raise ValueError("Forecasts and actual trajectories must be non-empty and aligned")
    steps = len(forecasts[0].points)
    if steps < 1 or any(len(f.points) != steps for f in forecasts) or any(len(a) != steps for a in actual_trajectories):
        raise ValueError("Every forecast and actual trajectory must share the same step count")

    mae_steps: list[float] = []
    rmse_steps: list[float] = []
    for step_idx in range(steps):
        errs = [abs(f.points[step_idx].value - actual_trajectories[i][step_idx]) for i, f in enumerate(forecasts)]
        sq_errs = [(f.points[step_idx].value - actual_trajectories[i][step_idx]) ** 2 for i, f in enumerate(forecasts)]
        mae_steps.append(mean(errs))
        rmse_steps.append(math.sqrt(mean(sq_errs)))

    has_intervals = all(all(p.lower is not None and p.upper is not None for p in f.points) for f in forecasts)
    joint_cov: float | None = None
    if has_intervals:
        covered = [
            all(
                f.points[s].lower <= actual_trajectories[i][s] <= f.points[s].upper  # type: ignore[operator]
                for s in range(steps)
            )
            for i, f in enumerate(forecasts)
        ]
        joint_cov = mean(1.0 if ok else 0.0 for ok in covered)

    return MultiHorizonLeadReport(
        steps=steps,
        samples=len(forecasts),
        mae_by_step=tuple(mae_steps),
        rmse_by_step=tuple(rmse_steps),
        joint_interval_coverage=joint_cov,
    )


class HierarchyAggregationMap(Record):
    hierarchy_id: Text
    parent_node: Text
    child_nodes: tuple[Text, ...] = Field(min_length=2)
    weights: tuple[FiniteFloat, ...]

    @model_validator(mode="after")
    def matching_weights(self):
        if len(self.weights) != len(self.child_nodes):
            raise ValueError("Hierarchy weights must match child_nodes length")
        return self


def verify_hierarchical_coherence(
    mapping: HierarchyAggregationMap,
    node_forecasts: dict[str, tuple[float, ...]],
    *,
    tolerance: float = 1e-5,
) -> tuple[bool, float]:
    """Verify whether child forecasts aggregate coherently to the parent forecast at every step."""
    if mapping.parent_node not in node_forecasts:
        raise KeyError(f"Missing parent forecast for {mapping.parent_node}")
    parent_vals = node_forecasts[mapping.parent_node]
    steps = len(parent_vals)
    for child in mapping.child_nodes:
        if child not in node_forecasts or len(node_forecasts[child]) != steps:
            raise ValueError(f"Missing or misaligned child forecast for {child}")

    max_discrepancy = 0.0
    for step_idx in range(steps):
        agg = sum(
            weight * node_forecasts[child][step_idx]
            for child, weight in zip(mapping.child_nodes, mapping.weights)
        )
        diff = abs(parent_vals[step_idx] - agg)
        max_discrepancy = max(max_discrepancy, diff)

    return (max_discrepancy <= tolerance, max_discrepancy)
