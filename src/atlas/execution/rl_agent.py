"""WF-08: Reinforcement Learning Execution Policy Surrogate (`src/atlas/execution/rl_agent.py`).

Implements a deterministic policy pi*(a | s) over state s = (OFI, Spread_bps, Inventory_fraction, VPIN)
maximizing expected cumulative reward:
    R = -Slippage_bps - lambda_inv * Inventory^2
All outputs carry `execution_permission = "none"` and serve solely as execution tactic advisories.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Probability, Record


class RlExecutionPolicyAdvisory(Record):
    """Advisory emitted by the WF-08 RL Execution Policy over state (OFI, Spread, Inventory, VPIN)."""

    state_ofi: FiniteFloat
    state_spread_bps: FiniteFloat = Field(gt=0)
    state_inventory_fraction: FiniteFloat
    state_vpin: Probability = 0.25
    recommended_action: Literal[
        "passive_post_only_limit",
        "almgren_chriss_twap_slice",
        "pegged_to_midpoint_limit",
        "pause_adverse_selection",
    ]
    recommended_slice_participation: Probability
    expected_slippage_bps: FiniteFloat = Field(ge=0)
    inventory_penalty_bps: FiniteFloat = Field(ge=0)
    expected_reward: FiniteFloat
    execution_permission: Literal["none"] = "none"


def evaluate_rl_execution_policy(
    *,
    ofi_normalized: float,
    spread_bps: float,
    inventory_fraction: float,
    vpin: float = 0.25,
    inventory_penalty_coeff: float = 4.5,
) -> RlExecutionPolicyAdvisory:
    """Evaluate pi*(a | s) maximizing R = -Slippage - Penalty(Inventory)."""
    if spread_bps <= 0:
        raise ValueError("spread_bps must be strictly positive")

    clean_vpin = max(0.0, min(1.0, float(vpin)))
    slippage_bps = round(0.45 * float(spread_bps) + 1.60 * abs(float(ofi_normalized)) + 2.0 * clean_vpin, 4)
    inv_pen_bps = round(float(inventory_penalty_coeff) * (float(inventory_fraction) ** 2), 4)
    reward = round(-(slippage_bps + inv_pen_bps), 4)

    if clean_vpin >= 0.70:
        action: Literal[
            "passive_post_only_limit",
            "almgren_chriss_twap_slice",
            "pegged_to_midpoint_limit",
            "pause_adverse_selection",
        ] = "pause_adverse_selection"
        slice_part = 0.0
    elif abs(inventory_fraction) >= 0.55:
        action = "almgren_chriss_twap_slice"
        slice_part = min(1.0, round(0.25 + 0.35 * abs(inventory_fraction), 4))
    elif abs(ofi_normalized) >= 0.65 and spread_bps <= 2.5:
        action = "pegged_to_midpoint_limit"
        slice_part = 0.35
    else:
        action = "passive_post_only_limit"
        slice_part = 0.20

    return RlExecutionPolicyAdvisory(
        state_ofi=round(float(ofi_normalized), 6),
        state_spread_bps=round(float(spread_bps), 6),
        state_inventory_fraction=round(float(inventory_fraction), 6),
        state_vpin=round(clean_vpin, 6),
        recommended_action=action,
        recommended_slice_participation=slice_part,
        expected_slippage_bps=slippage_bps,
        inventory_penalty_bps=inv_pen_bps,
        expected_reward=reward,
    )

