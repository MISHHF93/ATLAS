"""Almgren-Chriss Optimal Execution Trajectory (`src/atlas/execution/tactics/optimal.py`).

Implements the discrete-time and continuous-limit Almgren-Chriss (2000) optimal liquidation
and acquisition trajectory:

    min_x E[x] + lambda_risk * Var[x]
    ==> x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T)
    where kappa = sqrt(lambda_risk * sigma^2 / eta)

All schedules produced by this module are read-only execution advisories carrying
`execution_permission = "none"`. Only `ActionableControlPlaneEngine` can authorize
live orders.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record


class AlmgrenChrissStep(Record):
    """Single discrete time step j in an Almgren-Chriss execution trajectory."""

    step_index: int = Field(ge=0)
    time_t_j: FiniteFloat = Field(ge=0)
    remaining_inventory_x_j: FiniteFloat = Field(ge=0)
    slice_trade_n_j: FiniteFloat = Field(ge=0)


class AlmgrenChrissSchedule(Record):
    """Complete Almgren-Chriss optimal execution trajectory and risk/impact decomposition."""

    initial_inventory_x0: FiniteFloat = Field(gt=0)
    total_time_T: FiniteFloat = Field(gt=0)
    num_steps: int = Field(ge=1)
    risk_aversion_lambda: FiniteFloat = Field(ge=0)
    volatility_sigma: FiniteFloat = Field(gt=0)
    temporary_impact_eta: FiniteFloat = Field(gt=0)
    permanent_impact_gamma: FiniteFloat = Field(ge=0)
    urgency_kappa: FiniteFloat = Field(ge=0)
    steps: tuple[AlmgrenChrissStep, ...]
    child_order_slices: tuple[FiniteFloat, ...]
    remaining_inventory_trajectory: tuple[FiniteFloat, ...]
    expected_shortfall_cost: FiniteFloat = Field(ge=0)
    variance_of_shortfall: FiniteFloat = Field(ge=0)
    is_strictly_monotonic: bool
    terminal_inventory_zero: bool
    execution_permission: Literal["none"] = "none"


def compute_almgren_chriss_trajectory(
    initial_inventory: float,
    num_steps: int,
    *,
    total_time_T: float = 1.0,
    risk_aversion_lambda: float = 1e-5,
    volatility_sigma: float = 0.02,
    temporary_impact_eta: float = 2.5e-6,
    permanent_impact_gamma: float = 1.0e-6,
) -> AlmgrenChrissSchedule:
    """Compute the Almgren-Chriss optimal liquidation/execution trajectory:
    x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T), with kappa = sqrt(lambda_risk * sigma^2 / eta).
    """
    if initial_inventory <= 0:
        raise ValueError("initial_inventory X must be strictly positive")
    if num_steps < 1:
        raise ValueError("num_steps N must be >= 1")
    if total_time_T <= 0:
        raise ValueError("total_time_T must be strictly positive")
    if risk_aversion_lambda < 0 or volatility_sigma <= 0 or temporary_impact_eta <= 0 or permanent_impact_gamma < 0:
        raise ValueError("Invalid Almgren-Chriss risk/volatility/impact parameters")

    tau = total_time_T / num_steps
    kappa = math.sqrt((risk_aversion_lambda * (volatility_sigma**2)) / temporary_impact_eta)
    denom = math.sinh(kappa * total_time_T) if kappa * total_time_T > 1e-8 else 0.0

    steps: list[AlmgrenChrissStep] = []
    slices: list[float] = []
    remaining_curve: list[float] = []

    prev_x = float(initial_inventory)
    steps.append(
        AlmgrenChrissStep(
            step_index=0,
            time_t_j=0.0,
            remaining_inventory_x_j=round(prev_x, 6),
            slice_trade_n_j=0.0,
        )
    )

    expected_temp_cost = 0.0
    shortfall_var = 0.0

    for j in range(1, num_steps + 1):
        t_j = j * tau
        if j == num_steps:
            x_j = 0.0
        elif denom > 1e-8:
            x_j = float(initial_inventory) * (math.sinh(kappa * (total_time_T - t_j)) / denom)
        else:
            # Risk-neutral TWAP limit as kappa -> 0
            x_j = float(initial_inventory) * (1.0 - (t_j / total_time_T))

        x_j = max(0.0, x_j)
        n_j = max(0.0, prev_x - x_j)

        expected_temp_cost += temporary_impact_eta * ((n_j**2) / tau)
        shortfall_var += tau * (volatility_sigma**2) * (x_j**2)

        steps.append(
            AlmgrenChrissStep(
                step_index=j,
                time_t_j=round(t_j, 6),
                remaining_inventory_x_j=round(x_j, 6),
                slice_trade_n_j=round(n_j, 6),
            )
        )
        slices.append(round(n_j, 6))
        remaining_curve.append(round(x_j, 6))
        prev_x = x_j

    expected_perm_cost = 0.5 * permanent_impact_gamma * (initial_inventory**2)
    total_expected_cost = expected_perm_cost + expected_temp_cost

    # Verify monotonicity x_0 >= x_1 >= ... >= x_N and terminal boundary x_N == 0
    inv_seq = [s.remaining_inventory_x_j for s in steps]
    monotonic = all(inv_seq[i] >= inv_seq[i + 1] - 1e-9 for i in range(len(inv_seq) - 1))
    terminal_zero = abs(inv_seq[-1]) <= 1e-9

    return AlmgrenChrissSchedule(
        initial_inventory_x0=round(float(initial_inventory), 6),
        total_time_T=total_time_T,
        num_steps=num_steps,
        risk_aversion_lambda=risk_aversion_lambda,
        volatility_sigma=volatility_sigma,
        temporary_impact_eta=temporary_impact_eta,
        permanent_impact_gamma=permanent_impact_gamma,
        urgency_kappa=round(kappa, 6),
        steps=tuple(steps),
        child_order_slices=tuple(slices),
        remaining_inventory_trajectory=tuple(remaining_curve),
        expected_shortfall_cost=round(total_expected_cost, 6),
        variance_of_shortfall=round(shortfall_var, 6),
        is_strictly_monotonic=monotonic,
        terminal_inventory_zero=terminal_zero,
    )
