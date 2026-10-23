"""Optimal execution trajectory subsystem (`src/atlas/execution`).

Also hosts the paper-only founder execution layer (`paper/` simulator, `adapters/` paper-only,
off by default). There is no live adapter; live trading is disabled at build level."""
from atlas.execution.tactics.optimal import (
    AlmgrenChrissSchedule,
    AlmgrenChrissStep,
    compute_almgren_chriss_trajectory,
)

__all__ = [
    "AlmgrenChrissSchedule",
    "AlmgrenChrissStep",
    "compute_almgren_chriss_trajectory",
]

