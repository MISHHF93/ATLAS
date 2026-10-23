"""Autopilot settings (config/autopilot.yaml, optional). Not part of the signed risk policy: every value here can
only make the bot MORE conservative than the policy, and the risk engine re-checks every order anyway. Values that
could add risk are clamped in code (Kelly fraction <= 0.5, vol target <= 20 %/yr, cadence >= 5 min)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class UniverseItem(BaseModel):
    symbol: str
    venue: str                      # schedule.yaml venue key: XTSE, XNYS_XNAS, crypto, ...
    currency: str = "CAD"
    sleeve: str = "core"
    asset_class: str = "index_etf"
    broker: str = "ibkr"
    sector: str | None = None
    s0: float = 50.0                # replay feed only: synthetic starting price
    vol: float = 0.18               # replay feed only: synthetic annual volatility


DEFAULT_UNIVERSE = [
    UniverseItem(symbol="XIC.TO", venue="XTSE", s0=34.5), UniverseItem(symbol="VFV.TO", venue="XTSE", s0=144.0),
    UniverseItem(symbol="ZAG.TO", venue="XTSE", s0=13.9, vol=0.06), UniverseItem(symbol="CASH.TO", venue="XTSE", s0=50.0, vol=0.01),
    UniverseItem(symbol="SHOP.TO", venue="XTSE", sleeve="active", asset_class="equity", sector="Technology", s0=99.0, vol=0.45),
    UniverseItem(symbol="RY.TO", venue="XTSE", sleeve="active", asset_class="equity", sector="Financials", s0=170.0, vol=0.2),
    UniverseItem(symbol="SPY", venue="XNYS_XNAS", currency="USD", s0=560.0, vol=0.16),
    UniverseItem(symbol="BTC-USD", venue="crypto", currency="USD", sleeve="high_risk", asset_class="crypto_spot", broker="kraken", s0=65000, vol=0.6),
    UniverseItem(symbol="ETH-USD", venue="crypto", currency="USD", sleeve="high_risk", asset_class="crypto_spot", broker="kraken", s0=3100, vol=0.7),
]


class AutopilotCfg(BaseModel):
    cycle_minutes: dict[str, int] = Field(default_factory=lambda: {"crypto": 15, "default": 30})
    vol_target_annual_pct: float = 12.0
    kelly_fraction: float = 0.25    # quarter Kelly
    kelly_min_obs: int = 20         # fewer return observations => neutral "warming up" budget
    warmup_exposure: float = 0.5    # fraction of bot capital allowed while warming up
    feed_max_age_s: dict[str, int] = Field(default_factory=lambda: {"bars": 3 * 86400, "quotes": 900, "news": 86400, "fundamentals": 7 * 86400})
    pause_on: list[str] = Field(default_factory=lambda: ["watchdog", "daily_halt", "loss_limits", "feeds_stale", "broker_disconnected", "drift", "anomaly"])
    max_decisions_kept: int = 30
    universe: list[UniverseItem] = Field(default_factory=lambda: list(DEFAULT_UNIVERSE))

    @field_validator("kelly_fraction")
    @classmethod
    def _kelly(cls, v: float) -> float:
        return max(0.0, min(0.5, v))

    @field_validator("vol_target_annual_pct")
    @classmethod
    def _vt(cls, v: float) -> float:
        return max(1.0, min(20.0, v))

    @field_validator("warmup_exposure")
    @classmethod
    def _wu(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("cycle_minutes")
    @classmethod
    def _cad(cls, v: dict[str, int]) -> dict[str, int]:
        return {k: max(5, int(x)) for k, x in v.items()}

    def cadence_s(self, venue: str) -> int:
        return 60 * self.cycle_minutes.get(venue, self.cycle_minutes.get("default", 30))


def load_autopilot_cfg(config_dir: str | Path = "config/founder") -> AutopilotCfg:
    p = Path(config_dir) / "autopilot.yaml"
    if not p.exists():
        return AutopilotCfg()
    return AutopilotCfg(**(yaml.safe_load(p.read_text()) or {}))
