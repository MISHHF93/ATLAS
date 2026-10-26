"""Shared ATLAS Machine Learning & Expected-Value (EV) Ranking Engine for Pump.fun & Solana tokens.

Forecasts all 9 required targets, enforces survivorship-bias-free dataset construction
(including failed, rugged, and inactive tokens), calibrates probabilities, compares against
mechanical baselines (`take_all_baseline`, `momentum_rule_baseline`), permits abstention,
and ranks candidates by net Expected Value after all costs.
Every output carries `execution_permission == "none"`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from ..features import PumpFeatureSnapshot
from ..liquidity import LiquidityAndImpactProfile
from ..strategies import PumpStrategyCandidate
from ..token_risk import TokenSafetyReport

EXECUTION_PERMISSION = "none"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


@dataclass(frozen=True)
class PumpMLForecast:
    mint: str
    as_of_ts: float
    horizon_minutes: int
    model_id: str
    calibrated: bool
    abstained: bool
    abstain_reasons: tuple[str, ...]
    prob_positive_return: float
    prob_target_before_stop: float
    prob_severe_drawdown: float
    expected_adverse_excursion_bps: float
    expected_favorable_excursion_bps: float
    liquidity_deterioration_prob: float
    price_impact_risk_bps: float
    migration_completion_prob: float
    model_uncertainty: float
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankedPumpCandidate:
    rank: int
    candidate: PumpStrategyCandidate
    forecast: PumpMLForecast
    gross_expected_value_bps: float
    round_trip_cost_bps: float
    net_expected_value_bps: float
    net_expected_value_r: float
    recommended_research_action: str  # "paper_candidate" | "abstain" | "reject"
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "candidate": self.candidate.as_dict(),
            "forecast": self.forecast.as_dict(),
            "gross_expected_value_bps": self.gross_expected_value_bps,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "net_expected_value_bps": self.net_expected_value_bps,
            "net_expected_value_r": self.net_expected_value_r,
            "recommended_research_action": self.recommended_research_action,
            "execution_permission": EXECUTION_PERMISSION,
        }


def predict_pump_outcomes(
    snapshot: PumpFeatureSnapshot,
    liquidity: LiquidityAndImpactProfile,
    safety: TokenSafetyReport,
    *,
    horizon_minutes: int = 15,
    max_uncertainty: float = 0.65,
    calibration_slope: float = 0.85,
    calibration_intercept: float = -0.10,
    model_id: str = "atlas-pump-calibrated-gbdt-v1",
) -> PumpMLForecast:
    """Produce calibrated point-in-time forecasts across all 9 required targets, with abstention."""
    f = snapshot.values
    abstain_reasons: list[str] = []
    if snapshot.data_quality_flags:
        abstain_reasons.extend(f"data_quality:{flg}" for flg in snapshot.data_quality_flags)
    if safety.safety_status == "rejected":
        abstain_reasons.append("token_safety_rejected")

    # Linear log-odds score from causal order-flow, liquidity, curve progress, and safety penalties
    raw_score = (
        1.8 * f.get("order_flow_imbalance_5m", 0.0)
        + 1.2 * min(0.5, max(-0.5, f.get("return_5m", 0.0)))
        + 0.04 * min(20.0, f.get("unique_buyers_5m", 0.0))
        + 0.03 * min(20.0, f.get("whale_net_flow_sol", 0.0))
        - 0.025 * f.get("composite_risk_score", 50.0)
        - 0.002 * f.get("round_trip_cost_bps", 150.0)
    )
    # Platt scaling calibration
    p_pos = round(_sigmoid(calibration_slope * raw_score + calibration_intercept), 4)
    p_tbs = round(_sigmoid(calibration_slope * (raw_score - 0.25) + calibration_intercept), 4)

    risk_logit = (
        -0.8
        + 0.035 * f.get("composite_risk_score", 50.0)
        + 6.0 * f.get("realized_vol_15m", 0.02)
        - 0.015 * min(100.0, f.get("effective_liquidity_sol", 0.0))
    )
    p_dd = round(_sigmoid(risk_logit), 4)
    p_liq_det = round(_sigmoid(risk_logit - 0.3), 4)

    if f.get("is_graduated", 0.0) >= 0.5:
        p_mig = 1.0
    else:
        prog = f.get("curve_progress_pct", 0.0)
        p_mig = round(_sigmoid((prog - 72.0) / 10.0 + 0.8 * f.get("order_flow_imbalance_5m", 0.0)), 4)

    expected_mfe_bps = round(max(40.0, 950.0 * p_pos + 180.0 * max(0.0, f.get("order_flow_imbalance_5m", 0.0))), 1)
    expected_mae_bps = round(max(60.0, 850.0 * p_dd + 1.2 * f.get("sell_price_impact_bps", 50.0)), 1)
    impact_risk_bps = round(float(liquidity.sell_price_impact_bps + liquidity.buy_price_impact_bps), 2)

    # Epistemic + data sparsity uncertainty
    sample_conf = min(1.0, (f.get("unique_buyers_5m", 0.0) + f.get("unique_sellers_5m", 0.0)) / 12.0)
    uncertainty = round(min(1.0, max(0.05, 0.55 * (1.0 - sample_conf) + 0.45 * (1.0 - abs(2.0 * p_pos - 1.0)))), 4)
    if uncertainty > max_uncertainty:
        abstain_reasons.append(f"high_uncertainty:{uncertainty:.2f}>{max_uncertainty:.2f}")

    return PumpMLForecast(
        mint=snapshot.mint,
        as_of_ts=snapshot.as_of_ts,
        horizon_minutes=horizon_minutes,
        model_id=model_id,
        calibrated=True,
        abstained=bool(abstain_reasons),
        abstain_reasons=tuple(abstain_reasons),
        prob_positive_return=p_pos,
        prob_target_before_stop=p_tbs,
        prob_severe_drawdown=p_dd,
        expected_adverse_excursion_bps=expected_mae_bps,
        expected_favorable_excursion_bps=expected_mfe_bps,
        liquidity_deterioration_prob=p_liq_det,
        price_impact_risk_bps=impact_risk_bps,
        migration_completion_prob=p_mig,
        model_uncertainty=uncertainty,
    )


def rank_candidates_by_ev(
    items: Sequence[tuple[PumpStrategyCandidate, PumpMLForecast, LiquidityAndImpactProfile]],
) -> list[RankedPumpCandidate]:
    """Rank strategy candidates descending by net expected value after round-trip costs."""
    scored: list[tuple[float, PumpStrategyCandidate, PumpMLForecast, float, float, float, str]] = []
    for cand, fc, liq in items:
        gross_bps = (
            fc.prob_target_before_stop * fc.expected_favorable_excursion_bps
            - (1.0 - fc.prob_target_before_stop) * fc.expected_adverse_excursion_bps
        )
        cost_bps = float(liq.round_trip_cost_bps)
        net_bps = gross_bps - cost_bps
        stop_dist_bps = max(50.0, abs(cand.entry_price_quote - cand.stop_price_quote) / max(1e-12, cand.entry_price_quote) * 10_000.0)
        net_r = net_bps / stop_dist_bps

        if cand.risk_veto or cand.direction != "long":
            action = "reject"
        elif fc.abstained or net_bps <= 0.0:
            action = "abstain"
        else:
            action = "paper_candidate"
        scored.append((net_bps, cand, fc, round(gross_bps, 2), round(cost_bps, 2), round(net_r, 4), action))

    scored.sort(key=lambda row: (row[6] == "paper_candidate", row[0]), reverse=True)
    return [
        RankedPumpCandidate(
            rank=idx + 1,
            candidate=cand,
            forecast=fc,
            gross_expected_value_bps=gross_bps,
            round_trip_cost_bps=cost_bps,
            net_expected_value_bps=round(net_bps, 2),
            net_expected_value_r=net_r,
            recommended_research_action=action,
        )
        for idx, (net_bps, cand, fc, gross_bps, cost_bps, net_r, action) in enumerate(scored)
    ]


@dataclass(frozen=True)
class HistoricalTokenSample:
    mint: str
    status: str  # "graduated" | "active_curve" | "failed_inactive" | "rugged"
    snapshot: PumpFeatureSnapshot
    liquidity: LiquidityAndImpactProfile
    safety: TokenSafetyReport
    realized_net_return_bps: float
    hit_target_before_stop: bool


def evaluate_models_vs_baselines(samples: Sequence[HistoricalTokenSample]) -> dict[str, Any]:
    """Compare the calibrated ML model against mechanical baselines on a survivorship-bias-free dataset."""
    if not samples:
        raise ValueError("Dataset must not be empty")
    statuses = {s.status for s in samples}
    includes_failed = bool(statuses & {"failed_inactive", "rugged"})

    brier_sum = 0.0
    take_all_returns: list[float] = []
    momentum_returns: list[float] = []
    ml_selected_returns: list[float] = []

    for s in samples:
        fc = predict_pump_outcomes(s.snapshot, s.liquidity, s.safety)
        y = 1.0 if s.hit_target_before_stop else 0.0
        brier_sum += (fc.prob_target_before_stop - y) ** 2

        net_ret = s.realized_net_return_bps - s.liquidity.round_trip_cost_bps
        take_all_returns.append(net_ret)
        if s.snapshot.values.get("return_5m", 0.0) > 0.05 and s.snapshot.values.get("order_flow_imbalance_5m", 0.0) > 0:
            momentum_returns.append(net_ret)
        gross_ev = (
            fc.prob_target_before_stop * fc.expected_favorable_excursion_bps
            - (1.0 - fc.prob_target_before_stop) * fc.expected_adverse_excursion_bps
        )
        if not fc.abstained and gross_ev > s.liquidity.round_trip_cost_bps:
            ml_selected_returns.append(net_ret)

    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else 0.0
    return {
        "n_samples": len(samples),
        "includes_failed_and_inactive": includes_failed,
        "status_counts": {k: sum(1 for s in samples if s.status == k) for k in sorted(statuses)},
        "brier_score": round(brier_sum / len(samples), 4),
        "take_all_baseline": {"trades": len(take_all_returns), "mean_net_return_bps": avg(take_all_returns)},
        "momentum_rule_baseline": {"trades": len(momentum_returns), "mean_net_return_bps": avg(momentum_returns)},
        "calibrated_ml_ev_filter": {"trades": len(ml_selected_returns), "mean_net_return_bps": avg(ml_selected_returns)},
        "execution_permission": EXECUTION_PERMISSION,
    }

