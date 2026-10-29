"""Instrument contract specifications: multiplier, tick size, tick value, and cost assumptions.

Canonical module for futures and authentic asset contract specifications across sizing,
backtesting, risk controls, and market intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractSpec:
    instrument_id: str
    exchange: str
    multiplier: float
    tick_size: float
    cost_per_contract_rt_usd: float
    cost_source: str = "research_assumption"
    verified: bool = True

    @property
    def tick_value(self) -> float:
        return round(self.tick_size * self.multiplier, 4)


# Authoritative contract specifications for CME/COMEX futures and benchmark instruments
SPEC_BY_ID: dict[str, ContractSpec] = {
    "GC": ContractSpec(
        instrument_id="GC",
        exchange="COMEX",
        multiplier=100.0,
        tick_size=0.10,
        cost_per_contract_rt_usd=25.0,
        verified=True,
    ),
    "MGC": ContractSpec(
        instrument_id="MGC",
        exchange="COMEX",
        multiplier=10.0,
        tick_size=0.10,
        cost_per_contract_rt_usd=3.50,
        verified=True,
    ),
    "SI": ContractSpec(
        instrument_id="SI",
        exchange="COMEX",
        multiplier=5000.0,
        tick_size=0.005,
        cost_per_contract_rt_usd=125.0,
        verified=True,
    ),
    "ES": ContractSpec(
        instrument_id="ES",
        exchange="CME",
        multiplier=50.0,
        tick_size=0.25,
        cost_per_contract_rt_usd=30.0,
        verified=True,
    ),
    "NQ": ContractSpec(
        instrument_id="NQ",
        exchange="CME",
        multiplier=20.0,
        tick_size=0.25,
        cost_per_contract_rt_usd=30.0,
        verified=True,
    ),
    "MNQ": ContractSpec(
        instrument_id="MNQ",
        exchange="CME",
        multiplier=2.0,
        tick_size=0.25,
        cost_per_contract_rt_usd=3.50,
        verified=True,
    ),
    "CL": ContractSpec(
        instrument_id="CL",
        exchange="NYMEX",
        multiplier=1000.0,
        tick_size=0.01,
        cost_per_contract_rt_usd=30.0,
        verified=True,
    ),
    "ZN": ContractSpec(
        instrument_id="ZN",
        exchange="CBOT",
        multiplier=1000.0,
        tick_size=0.015625,
        cost_per_contract_rt_usd=20.0,
        verified=True,
    ),
}


def contract_for(iid: str) -> ContractSpec | None:
    return SPEC_BY_ID.get(iid.upper().strip())

