"""Strategy registry: every detection technique with an explicit enable/disable toggle.

Toggles only control which detectors RUN and which candidates the selector may rank. They grant no execution
permission: candidates still go through proposals.evaluate -> ActionableControlPlaneEngine. New strategies default to
disabled; legacy detectors keep their current default (enabled) so existing behaviour does not change.
Persistence: JSON at ``$ATLAS_STRATEGY_REGISTRY`` (default var/strategy_registry.json, never committed).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategySpec:
    id: str
    family: str
    detectors: tuple[str, ...]
    scope: str                 # "all" or a restriction such as "gold futures (GC, MGC)"
    default_enabled: bool
    status: str                # implemented | reserved
    description: str


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec("dual_band_breakout", "breakout", ("dual_band_breakout",), "all", True, "implemented", "Dual Bollinger band breakout (legacy)"),
    StrategySpec("wick_reversal", "zone_rejection", ("wick_reversal",), "all", True, "implemented", "Wick reversal (legacy)"),
    StrategySpec("orb_retest", "snapback", ("orb_retest",), "all with a session", True, "implemented", "Opening-range retest (legacy, 1h range)"),
    StrategySpec("prior_day_range_reversal", "zone_rejection", ("prior_day_range_reversal",), "all with a session", True, "implemented", "Prior-day range reversal (legacy)"),
    StrategySpec("sfp", "sfp", ("sfp_reversal",), "all", False, "implemented", "Swing failure pattern at potential liquidity reference levels"),
    StrategySpec("gold_snapback", "snapback", ("gold_snapback",), "gold futures (GC, MGC)", False, "implemented", "Gold opening-box breakout -> retest -> continuation"),
    StrategySpec("gold_orb_breakout", "orb", ("gold_orb_breakout",), "gold futures (GC, MGC)", False, "implemented", "Gold opening-box accepted breakout"),
    StrategySpec("four_box", "box", (), "all", False, "reserved", "Four-Box levels (not implemented: no definition/data in repo)"),
)
BY_ID = {s.id: s for s in STRATEGIES}


def _path() -> Path:
    return Path(os.environ.get("ATLAS_STRATEGY_REGISTRY", "var/strategy_registry.json"))


class StrategyRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _path()
        self._over: dict[str, bool] = {}
        if self.path.exists():
            self._over = {k: bool(v) for k, v in json.loads(self.path.read_text()).items() if k in BY_ID}

    def enabled(self, sid: str) -> bool:
        s = BY_ID[sid]
        return s.status == "implemented" and self._over.get(sid, s.default_enabled)

    def set(self, sid: str, on: bool) -> None:
        if sid not in BY_ID:
            raise KeyError(sid)
        if on and BY_ID[sid].status != "implemented":
            raise ValueError(f"{sid} is reserved (not implemented)")
        self._over[sid] = bool(on)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._over, indent=1, sort_keys=True))

    def enabled_detectors(self) -> set[str]:
        return {d for s in STRATEGIES if self.enabled(s.id) for d in s.detectors}

    def listing(self) -> list[dict[str, Any]]:
        return [{**asdict(s), "enabled": self.enabled(s.id), "execution_permission": "none"} for s in STRATEGIES]
