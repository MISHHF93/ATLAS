"""Governed re-entry: limits on how often the same level / family / instrument may produce an actionable candidate.

Rules (all deterministic, per instrument):
- at most ``per_level`` candidates per level id per trading day;
- at most ``per_day`` candidates per family per trading day;
- at least ``cooldown_s`` seconds between two candidates of the same family;
- cumulative-loss caps fed by paper trade outcomes (``record_outcome``): once a family's realized R for the trading day
  is <= -``max_loss_r_per_family_day``, or the instrument's realized R for the day is <= -``max_loss_r_per_day``, or a
  family has ``max_consecutive_losses`` losing trades in a row that day, further candidates are refused.
A refused candidate becomes NO_TRADE(REENTRY_LIMIT); nothing is silently dropped.

Tighten-only overlay: ``load_reentry_config`` reads ``config/risk_overlays/reentry_tighten.yaml`` (never
``config/founder/risk_policy.yaml``). Each overlay value is applied only when it is TIGHTER than the code default
(smaller count / loss cap, longer cooldown); a looser value is ignored and reported in ``overlay_notes``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


@dataclass
class ReentryConfig:
    per_level: int = 1
    per_day: int = 3
    cooldown_s: int = 3600
    max_loss_r_per_family_day: float | None = None   # e.g. 2.0 -> refuse once family day R <= -2.0
    max_loss_r_per_day: float | None = None          # all families of this instrument
    max_consecutive_losses: int | None = None        # per family, per trading day
    overlay_notes: tuple = field(default=(), compare=False)


# which direction is tighter for each knob: "min" -> smaller is tighter, "max" -> larger is tighter
_TIGHTER = {"per_level": "min", "per_day": "min", "cooldown_s": "max", "max_loss_r_per_family_day": "min",
            "max_loss_r_per_day": "min", "max_consecutive_losses": "min"}

DEFAULT_OVERLAY = Path(__file__).resolve().parents[4] / "config" / "risk_overlays" / "reentry_tighten.yaml"


def tighten(base: ReentryConfig, overlay: dict) -> ReentryConfig:
    """Apply only the overlay values that tighten ``base``. ``None`` in base means "no cap", so any positive cap tightens."""
    notes, upd = list(base.overlay_notes), {}
    for k, v in (overlay or {}).items():
        if k not in _TIGHTER:
            notes.append(f"{k}: unknown key ignored")
            continue
        if v is None:
            notes.append(f"{k}: null ignored (cannot remove a cap)")
            continue
        try:
            cast = type(getattr(base, k)) if getattr(base, k) is not None else (int if k == "max_consecutive_losses" else float)
            v = cast(v)
        except (TypeError, ValueError):
            notes.append(f"{k}: invalid value ignored")
            continue
        if not v > 0:
            notes.append(f"{k}: non-positive value ignored")
            continue
        cur = getattr(base, k)
        tighter = cur is None or (v < cur if _TIGHTER[k] == "min" else v > cur)
        if tighter:
            upd[k] = v
        elif v != cur:
            notes.append(f"{k}: {v} would loosen {cur}; ignored")
    return replace(base, **upd, overlay_notes=tuple(notes))


def load_reentry_config(path: str | os.PathLike | None = None, base: ReentryConfig | None = None) -> ReentryConfig:
    p = Path(path or os.environ.get("ATLAS_REENTRY_OVERLAY") or DEFAULT_OVERLAY)
    base = base or ReentryConfig()
    if not p.exists():
        return replace(base, overlay_notes=base.overlay_notes + (f"overlay {p.name} not found; code defaults only",))
    import yaml
    data = yaml.safe_load(p.read_text()) or {}
    return tighten(base, data.get("reentry", {}))


class ReentryGovernor:
    def __init__(self, cfg: ReentryConfig | None = None):
        self.cfg = cfg or ReentryConfig()
        self._lvl: dict[tuple[str, str, str], int] = {}
        self._day: dict[tuple[str, str], int] = {}
        self._last: dict[str, int] = {}
        self._loss_fam: dict[tuple[str, str], float] = {}
        self._loss_all: dict[str, float] = {}
        self._streak: dict[tuple[str, str], int] = {}
        self.outcomes = 0

    def allow(self, family: str, level_id: str, day: str, ts: int) -> tuple[bool, str]:
        c = self.cfg
        if c.max_loss_r_per_day is not None and self._loss_all.get(day, 0.0) <= -c.max_loss_r_per_day:
            return False, "daily loss cap"
        if c.max_loss_r_per_family_day is not None and self._loss_fam.get((family, day), 0.0) <= -c.max_loss_r_per_family_day:
            return False, "family loss cap"
        if c.max_consecutive_losses is not None and self._streak.get((family, day), 0) >= c.max_consecutive_losses:
            return False, "consecutive losses"
        if self._lvl.get((family, level_id, day), 0) >= c.per_level:
            return False, "per-level limit"
        if self._day.get((family, day), 0) >= c.per_day:
            return False, "per-day limit"
        if family in self._last and ts - self._last[family] < c.cooldown_s:
            return False, "cooldown"
        return True, ""

    def record(self, family: str, level_id: str, day: str, ts: int) -> None:
        self._lvl[(family, level_id, day)] = self._lvl.get((family, level_id, day), 0) + 1
        self._day[(family, day)] = self._day.get((family, day), 0) + 1
        self._last[family] = ts

    def record_outcome(self, family: str, day: str, r: float | None) -> None:
        """Feed back one resolved paper trade (after-cost R, already weighted by fill ratio). Only realized results count."""
        if r is None or r != r:
            return
        self.outcomes += 1
        self._loss_fam[(family, day)] = self._loss_fam.get((family, day), 0.0) + r
        self._loss_all[day] = self._loss_all.get(day, 0.0) + r
        self._streak[(family, day)] = self._streak.get((family, day), 0) + 1 if r < 0 else 0

    def state(self, day: str) -> dict:
        return {"day": day, "realized_r_day": self._loss_all.get(day, 0.0),
                "realized_r_by_family": {f: v for (f, d), v in self._loss_fam.items() if d == day},
                "loss_streak_by_family": {f: v for (f, d), v in self._streak.items() if d == day},
                "outcomes_recorded": self.outcomes,
                "caps": {k.name: getattr(self.cfg, k.name) for k in fields(self.cfg) if k.name != "overlay_notes"},
                "overlay_notes": list(self.cfg.overlay_notes)}
