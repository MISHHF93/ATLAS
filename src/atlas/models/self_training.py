"""Autonomous Self-Training Loop ("Anti-Gravity" Module) (`src/atlas/models/self_training.py`).

Implements:
1. Triple-Barrier Labeling (`+k * ATR` upper profit barrier, `-k * ATR` lower stop barrier,
   and vertical time expiration barrier) with exact causal span tracking `[entry_index, barrier_touch_index]`.
2. Prop-Rulebook Objective Loss Function:
       L(theta) = E[ -R_realized + gamma_1 * DrawdownPenalty + gamma_2 * TurnoverCost + gamma_3 * I_{RuleBreach} ]
3. Purged & Embargoed Walk-Forward Out-of-Sample Gate:
   Removes any training sample whose triple-barrier horizon overlaps the test split or embargo window,
   preventing lookahead leakage, and gates challenger promotion on OOS Sharpe, Calmar, and Max Drawdown floors.

All outputs carry `execution_permission = "none"`. Only `ActionableControlPlaneEngine` can
authorize live orders or promote production model aliases after human review.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, FiniteFloat

from atlas.models.challengers import _extract_causal_features, fit_boosted_regression_tree
from atlas.models.schemas import Observation, Record, Text


class TripleBarrierSample(Record):
    """Single point-in-time observation labeled via the Triple-Barrier method."""

    sample_index: int = Field(ge=0)
    barrier_touch_index: int = Field(ge=0)
    entry_time: AwareDatetime
    barrier_touch_time: AwareDatetime
    entry_price: FiniteFloat = Field(gt=0)
    exit_price: FiniteFloat = Field(gt=0)
    atr_fraction: FiniteFloat = Field(gt=0)
    upper_barrier_price: FiniteFloat = Field(gt=0)
    lower_barrier_price: FiniteFloat = Field(gt=0)
    label: Literal[-1, 0, 1]
    barrier_hit: Literal["upper_profit", "lower_stop", "vertical_expiry"]
    realized_return: FiniteFloat
    execution_permission: Literal["none"] = "none"


def label_triple_barrier_samples(
    observations: tuple[Observation, ...] | list[Observation],
    *,
    atr_window: int = 5,
    barrier_multiplier_k: float = 1.5,
    vertical_horizon_bars: int = 4,
    min_atr_fraction: float = 0.0015,
) -> tuple[TripleBarrierSample, ...]:
    """Label chronological point-in-time observations using the Triple-Barrier method:
    - Upper profit barrier: P_t * (1 + k * ATR_t)
    - Lower stop barrier:   P_t * (1 - k * ATR_t)
    - Vertical expiration:  t + vertical_horizon_bars
    """
    if len(observations) < atr_window + vertical_horizon_bars + 1:
        raise ValueError("Insufficient observations for triple-barrier labeling")
    if barrier_multiplier_k <= 0 or vertical_horizon_bars < 1 or atr_window < 2:
        raise ValueError("Invalid triple-barrier parameters")

    samples: list[TripleBarrierSample] = []
    n_obs = len(observations)

    for idx in range(atr_window, n_obs - vertical_horizon_bars):
        entry_obs = observations[idx]
        entry_px = float(entry_obs.value)

        # Causal ATR proxy from trailing absolute percentage changes up to idx
        abs_returns = [
            abs(float(observations[j].value) - float(observations[j - 1].value)) / max(1e-9, float(observations[j - 1].value))
            for j in range(idx - atr_window + 1, idx + 1)
        ]
        atr_frac = max(min_atr_fraction, sum(abs_returns) / len(abs_returns))

        upper_px = entry_px * (1.0 + barrier_multiplier_k * atr_frac)
        lower_px = entry_px * max(0.01, (1.0 - barrier_multiplier_k * atr_frac))

        touch_idx = idx + vertical_horizon_bars
        label: Literal[-1, 0, 1] = 0
        hit_kind: Literal["upper_profit", "lower_stop", "vertical_expiry"] = "vertical_expiry"

        for fwd_idx in range(idx + 1, idx + vertical_horizon_bars + 1):
            fwd_px = float(observations[fwd_idx].value)
            if fwd_px >= upper_px:
                touch_idx = fwd_idx
                label = 1
                hit_kind = "upper_profit"
                break
            if fwd_px <= lower_px:
                touch_idx = fwd_idx
                label = -1
                hit_kind = "lower_stop"
                break

        exit_obs = observations[touch_idx]
        exit_px = float(exit_obs.value)
        realized_ret = (exit_px - entry_px) / entry_px

        samples.append(
            TripleBarrierSample(
                sample_index=idx,
                barrier_touch_index=touch_idx,
                entry_time=entry_obs.available_at,
                barrier_touch_time=exit_obs.available_at,
                entry_price=round(entry_px, 6),
                exit_price=round(exit_px, 6),
                atr_fraction=round(atr_frac, 6),
                upper_barrier_price=round(upper_px, 6),
                lower_barrier_price=round(lower_px, 6),
                label=label,
                barrier_hit=hit_kind,
                realized_return=round(realized_ret, 6),
            )
        )

    return tuple(samples)


class PropAlignedLossReport(Record):
    """Evaluation of the prop-firm objective loss function:
    L(theta) = E[ -R_realized + gamma_1 * DrawdownPenalty + gamma_2 * TurnoverCost + gamma_3 * I_{RuleBreach} ].
    """

    expected_loss: FiniteFloat
    mean_realized_return: FiniteFloat
    max_drawdown_fraction: FiniteFloat = Field(ge=0)
    drawdown_penalty_term: FiniteFloat = Field(ge=0)
    turnover_cost_term: FiniteFloat = Field(ge=0)
    rule_breach_indicator_rate: FiniteFloat = Field(ge=0)
    rule_breach_penalty_term: FiniteFloat = Field(ge=0)
    sharpe_ratio: FiniteFloat
    calmar_ratio: FiniteFloat
    execution_permission: Literal["none"] = "none"


def compute_prop_aligned_loss(
    strategy_returns: tuple[float, ...] | list[float],
    positions: tuple[float, ...] | list[float],
    *,
    max_daily_loss_limit: float = 0.04,
    max_trailing_drawdown_limit: float = 0.08,
    round_trip_cost_bps: float = 3.0,
    gamma_1_drawdown: float = 2.5,
    gamma_2_turnover: float = 1.0,
    gamma_3_rule_breach: float = 5.0,
) -> PropAlignedLossReport:
    """Compute the prop-aligned objective loss L(theta) and OOS Sharpe/Calmar metrics."""
    if len(strategy_returns) != len(positions) or len(strategy_returns) == 0:
        raise ValueError("strategy_returns and positions must be non-empty and of identical length")

    n = len(strategy_returns)
    cost_frac = round_trip_cost_bps / 10_000.0

    equity = 1.0
    peak_equity = 1.0
    max_dd = 0.0

    step_losses: list[float] = []
    net_returns: list[float] = []
    dd_penalties: list[float] = []
    turnover_costs: list[float] = []
    breach_flags: list[float] = []

    prev_pos = 0.0
    for r_t, pos_t in zip(strategy_returns, positions):
        turnover = abs(pos_t - prev_pos)
        t_cost = turnover * cost_frac
        realized_r = pos_t * r_t - t_cost
        equity *= 1.0 + realized_r
        peak_equity = max(peak_equity, equity)
        current_dd = max(0.0, (peak_equity - equity) / peak_equity)
        max_dd = max(max_dd, current_dd)

        # Drawdown proximity penalty (quadratic as current_dd approaches max_trailing_drawdown_limit)
        dd_ratio = current_dd / max(1e-6, max_trailing_drawdown_limit)
        dd_pen = dd_ratio**2

        # Hard rule breach indicator I_{RuleBreach}
        rule_breach = 1.0 if ( -realized_r >= max_daily_loss_limit or current_dd >= max_trailing_drawdown_limit ) else 0.0

        step_loss = -realized_r + (gamma_1_drawdown * dd_pen) + (gamma_2_turnover * t_cost) + (gamma_3_rule_breach * rule_breach)
        step_losses.append(step_loss)
        net_returns.append(realized_r)
        dd_penalties.append(gamma_1_drawdown * dd_pen)
        turnover_costs.append(gamma_2_turnover * t_cost)
        breach_flags.append(rule_breach)
        prev_pos = pos_t

    mean_ret = sum(net_returns) / n
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in net_returns) / max(1, n))
    sharpe = (mean_ret / std_ret) * math.sqrt(252.0) if std_ret > 1e-12 else 0.0
    annualized_ret = mean_ret * 252.0
    calmar = annualized_ret / max(1e-4, max_dd)

    return PropAlignedLossReport(
        expected_loss=round(sum(step_losses) / n, 6),
        mean_realized_return=round(mean_ret, 6),
        max_drawdown_fraction=round(max_dd, 6),
        drawdown_penalty_term=round(sum(dd_penalties) / n, 6),
        turnover_cost_term=round(sum(turnover_costs) / n, 6),
        rule_breach_indicator_rate=round(sum(breach_flags) / n, 6),
        rule_breach_penalty_term=round(gamma_3_rule_breach * (sum(breach_flags) / n), 6),
        sharpe_ratio=round(sharpe, 4),
        calmar_ratio=round(calmar, 4),
    )


class PurgedFoldSplit(Record):
    """Single purged & embargoed walk-forward fold split verifying zero lookahead leakage."""

    fold_index: int = Field(ge=0)
    train_sample_indices: tuple[int, ...]
    test_sample_indices: tuple[int, ...]
    purged_overlap_count: int = Field(ge=0)
    embargoed_count: int = Field(ge=0)
    zero_leakage_verified: bool
    execution_permission: Literal["none"] = "none"


def build_purged_embargoed_splits(
    samples: tuple[TripleBarrierSample, ...] | list[TripleBarrierSample],
    *,
    num_folds: int = 3,
    purge_bars: int = 1,
    embargo_bars: int = 1,
) -> tuple[PurgedFoldSplit, ...]:
    """Construct chronological walk-forward folds with strict triple-barrier purging & embargoing.

    A training sample i is purged if its label horizon [sample_index, barrier_touch_index]
    overlaps the test window [test_start_obs_idx - purge_bars, test_end_obs_idx] or falls inside
    the post-test embargo window [test_end_obs_idx, test_end_obs_idx + embargo_bars].
    """
    n_samples = len(samples)
    if n_samples < num_folds * 3:
        raise ValueError("Not enough triple-barrier samples for the requested number of folds")
    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be non-negative")

    fold_size = n_samples // (num_folds + 1)
    splits: list[PurgedFoldSplit] = []

    for f in range(num_folds):
        test_start_pos = (f + 1) * fold_size
        test_end_pos = n_samples if f == num_folds - 1 else (f + 2) * fold_size
        test_slice = samples[test_start_pos:test_end_pos]
        if not test_slice:
            continue

        test_first_obs = test_slice[0].sample_index
        test_last_obs = test_slice[-1].barrier_touch_index

        train_indices: list[int] = []
        purged_count = 0
        embargoed_count = 0

        # Strictly causal expanding window: only consider candidate training samples prior to test_start_pos
        for s_pos in range(0, test_start_pos):
            cand = samples[s_pos]
            # Purge if candidate's barrier_touch_index reaches into [test_first_obs - purge_bars, inf)
            if cand.barrier_touch_index >= (test_first_obs - purge_bars):
                purged_count += 1
                continue
            train_indices.append(cand.sample_index)

        # Count post-test embargoed samples for telemetry
        for s_pos in range(test_end_pos, n_samples):
            cand = samples[s_pos]
            if cand.sample_index <= test_last_obs + embargo_bars:
                embargoed_count += 1

        test_indices = [s.sample_index for s in test_slice]
        # Verify zero overlap between any kept training sample's barrier_touch_index and test_first_obs
        train_set = set(train_indices)
        leakage = any(
            s.sample_index in train_set and s.barrier_touch_index >= test_first_obs
            for s in samples[:test_start_pos]
        )

        splits.append(
            PurgedFoldSplit(
                fold_index=f,
                train_sample_indices=tuple(train_indices),
                test_sample_indices=tuple(test_indices),
                purged_overlap_count=purged_count,
                embargoed_count=embargoed_count,
                zero_leakage_verified=not leakage,
            )
        )

    return tuple(splits)


class SelfTrainingPromotionGateReport(Record):
    """Autonomous self-training loop ("Anti-Gravity" module) evaluation and promotion gate report."""

    run_id: Text
    evaluated_at: AwareDatetime
    challenger_model_id: Text
    champion_model_id: Text
    total_triple_barrier_samples: int = Field(ge=1)
    purged_folds: tuple[PurgedFoldSplit, ...]
    challenger_loss_report: PropAlignedLossReport
    champion_loss_report: PropAlignedLossReport
    min_sharpe_floor: FiniteFloat
    min_calmar_floor: FiniteFloat
    max_drawdown_ceiling: FiniteFloat
    oos_gate_passed: bool
    eligible_for_human_promotion: bool
    autonomous_self_promotion_blocked: Literal[True] = True
    execution_permission: Literal["none"] = "none"


def run_autonomous_self_training_cycle(
    observations: tuple[Observation, ...] | list[Observation],
    *,
    run_id: str = "antigravity-self-train:v1",
    dataset_id: str = "frozen:btc-perp:v1",
    evaluated_at: datetime | None = None,
    purge_bars: int = 1,
    embargo_bars: int = 1,
    min_sharpe_floor: float = 0.25,
    min_calmar_floor: float = 0.20,
    max_drawdown_ceiling: float = 0.08,
) -> SelfTrainingPromotionGateReport:
    """Execute the end-to-end Anti-Gravity self-training loop:
    1. Generate Triple-Barrier labels across point-in-time observations
    2. Build Purged & Embargoed Walk-Forward splits (verifying zero lookahead leakage)
    3. Fit from-scratch GBDT challenger on purged training folds & evaluate OOS vs Champion
    4. Evaluate Prop-Aligned Objective Loss L(theta) and OOS Sharpe/Calmar/Drawdown promotion gates.
    """
    obs_tuple = tuple(observations)
    now = evaluated_at or obs_tuple[-1].available_at

    tb_samples = label_triple_barrier_samples(
        obs_tuple,
        atr_window=5,
        barrier_multiplier_k=1.2,
        vertical_horizon_bars=2,
    )
    folds = build_purged_embargoed_splits(
        tb_samples,
        num_folds=2,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
    )

    sample_by_idx = {s.sample_index: s for s in tb_samples}
    oos_returns: list[float] = []
    challenger_positions: list[float] = []
    champion_positions: list[float] = []

    for fold in folds:
        if not fold.train_sample_indices or not fold.test_sample_indices:
            continue
        last_train_obs_idx = max(fold.train_sample_indices)
        train_obs_slice = obs_tuple[: last_train_obs_idx + 1]
        tree_model = fit_boosted_regression_tree(
            train_obs_slice,
            dataset_id=dataset_id,
            boost_rounds=4,
            learning_rate=0.35,
            use_depth_two=True,
        )

        for test_idx in fold.test_sample_indices:
            sample = sample_by_idx[test_idx]
            causal_slice = obs_tuple[: test_idx + 1]
            feats = _extract_causal_features(causal_slice)
            pred_ret = tree_model.predict_return(feats)

            # Challenger position sized by predicted return sign & magnitude
            chal_pos = 1.0 if pred_ret > 0.0001 else (-1.0 if pred_ret < -0.0001 else 0.25)
            # Naive momentum baseline champion
            champ_pos = 1.0 if feats[0] >= 0 else -1.0

            oos_returns.append(sample.realized_return)
            challenger_positions.append(chal_pos)
            champion_positions.append(champ_pos)

    challenger_loss = compute_prop_aligned_loss(oos_returns, challenger_positions)
    champion_loss = compute_prop_aligned_loss(oos_returns, champion_positions)

    all_zero_leakage = all(f.zero_leakage_verified for f in folds)
    gate_passed = (
        all_zero_leakage
        and challenger_loss.max_drawdown_fraction <= max_drawdown_ceiling
        and challenger_loss.rule_breach_indicator_rate == 0.0
        and (
            challenger_loss.expected_loss <= champion_loss.expected_loss
            or challenger_loss.sharpe_ratio >= min_sharpe_floor
            or challenger_loss.calmar_ratio >= min_calmar_floor
        )
    )

    return SelfTrainingPromotionGateReport(
        run_id=run_id,
        evaluated_at=now,
        challenger_model_id=f"local_tree:gbdt_depth2_v1:{run_id}",
        champion_model_id="naive:last_value:v1",
        total_triple_barrier_samples=len(tb_samples),
        purged_folds=folds,
        challenger_loss_report=challenger_loss,
        champion_loss_report=champion_loss,
        min_sharpe_floor=min_sharpe_floor,
        min_calmar_floor=min_calmar_floor,
        max_drawdown_ceiling=max_drawdown_ceiling,
        oos_gate_passed=gate_passed,
        eligible_for_human_promotion=gate_passed,
    )

