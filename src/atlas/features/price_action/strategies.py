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
    status: str                # implemented | reserved | research (toggleable; research/ML labelling only, not run by the live suite)
    description: str
    variant: str | None = None  # research.setup_variants.SetupVariant id (ATR stop / target / cost filter / hold)
    intervals: tuple[str, ...] = ()   # research variants: timeframes they are evaluated on


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec("dual_band_breakout", "breakout", ("dual_band_breakout",), "all", True, "implemented", "Dual Bollinger band breakout (legacy)"),
    StrategySpec("wick_reversal", "zone_rejection", ("wick_reversal",), "all", True, "implemented", "Wick reversal (legacy)"),
    StrategySpec("orb_retest", "snapback", ("orb_retest",), "all with a session", True, "implemented", "Opening-range retest (legacy, 1h range)"),
    StrategySpec("prior_day_range_reversal", "zone_rejection", ("prior_day_range_reversal",), "all with a session", True, "implemented", "Prior-day range reversal (legacy)"),
    StrategySpec("sfp", "sfp", ("sfp_reversal",), "all", False, "implemented", "Swing failure pattern at potential liquidity reference levels"),
    StrategySpec("gold_snapback", "snapback", ("gold_snapback",), "gold futures (GC, MGC)", False, "implemented", "Gold opening-box breakout -> retest -> continuation"),
    StrategySpec("gold_orb_breakout", "orb", ("gold_orb_breakout",), "gold futures (GC, MGC)", False, "implemented", "Gold opening-box accepted breakout"),
    StrategySpec("four_box", "box", ("orb_retest", "dual_bollinger", "wick_reversal"), "all", False, "reserved",
                 "Four-Box research view (atlas.intel.fourbox): Opening=orb_retest, Breakout=dual_bollinger, Anchor=wick_reversal; Event box disabled (no verified event calendar). Not a suite toggle."),
)
# evo6 research variants (docs/research/evo6-setup-variants.md). Off by default, toggleable, never run by the live
# suite (enabled_detectors ignores them) and grant no execution permission. The legacy specs above are unchanged.
_EVO6 = (("atr2_rr2", "stop 2 ATR(14), target 2R, 2-day hold"),
         ("atr2_rr2_cf15", "stop 2 ATR(14), target 2R, skip when cost/R > 0.15, 2-day hold"),
         ("atr3_rr1.5_cf15", "stop 3 ATR(14), target 1.5R, skip when cost/R > 0.15, 2-day hold"),
         ("base_cf15", "legacy stop/target, skip when cost/R > 0.15"))
STRATEGIES = STRATEGIES + tuple(
    StrategySpec(f"{det}__{vid}", "research_variant", (det,), "all" if det in ("dual_band_breakout", "wick_reversal") else "all with a session",
                 False, "research", f"{det} research variant: {desc} (evo6)", variant=vid,
                 intervals=("15m", "1h", "4h") if det != "orb_retest" else ("15m", "1h"))
    for det in ("dual_band_breakout", "orb_retest", "prior_day_range_reversal", "wick_reversal") for vid, desc in _EVO6)
BY_ID = {s.id: s for s in STRATEGIES}

# Research retirements: (strategy id, interval) -> reason. Reversible: StrategyRegistry.set_retired(sid, iv, False)
# re-enables it, and nothing is deleted. Only research consumers (variant evaluation, ML labelling) read this today.
RESEARCH_RETIRED: dict[tuple[str, str], str] = {
    ("orb_retest", "15m"): ("evo6 evidence (docs/research/evo6-setup-variants.md): legacy orb_retest on 15m has the worst "
                            "gross R of every setup (-0.32 R before costs, n=1187) and a median cost of 0.66 R, so net -1.27 R; "
                            "no wider-stop variant is positive before costs either. Retired for research by default, reversible."),
}


def _path() -> Path:
    return Path(os.environ.get("ATLAS_STRATEGY_REGISTRY", "var/strategy_registry.json"))


class StrategyRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _path()
        self._over: dict[str, bool] = {}
        if self.path.exists():
            self._over = {k: bool(v) for k, v in json.loads(self.path.read_text()).items() if k.split("@")[0] in BY_ID}

    def enabled(self, sid: str) -> bool:
        s = BY_ID[sid]
        return s.status in ("implemented", "research") and self._over.get(sid, s.default_enabled)

    def retired(self, sid: str, interval: str) -> bool:
        return self._over.get(f"{sid}@{interval}", (sid, interval) in RESEARCH_RETIRED)

    def _retired_intervals(self, sid: str) -> list[str]:
        ivs = {iv for (x, iv) in RESEARCH_RETIRED if x == sid} | {k.split("@")[1] for k in self._over if k.startswith(sid + "@")}
        return sorted(iv for iv in ivs if self.retired(sid, iv))

    def set_retired(self, sid: str, interval: str, on: bool) -> None:
        if sid not in BY_ID:
            raise KeyError(sid)
        self._over[f"{sid}@{interval}"] = bool(on)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._over, indent=1, sort_keys=True))

    def set(self, sid: str, on: bool) -> None:
        if sid not in BY_ID:
            raise KeyError(sid)
        if on and BY_ID[sid].status not in ("implemented", "research"):
            raise ValueError(f"{sid} is reserved (not implemented)")
        self._over[sid] = bool(on)
        self._save()

    def enabled_detectors(self, interval: str | None = None) -> set[str]:
        """Detectors the live suite runs: implemented specs only (research variants never change the live path).
        With ``interval``, research-retired (strategy, interval) pairs are excluded as well."""
        return {d for s in STRATEGIES if s.status == "implemented" and self.enabled(s.id)
                and not (interval and self.retired(s.id, interval)) for d in s.detectors}

    def listing(self) -> list[dict[str, Any]]:
        return [{**asdict(s), "enabled": self.enabled(s.id), "execution_permission": "none",
                 "research_retired": {iv: RESEARCH_RETIRED.get((s.id, iv), "retired by toggle") for iv in self._retired_intervals(s.id)}}
                for s in STRATEGIES]
