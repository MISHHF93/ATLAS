"""Pipeline building blocks: stage names, acting/shadow model set, candidate record."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from atlas.models.quant.sleeves import SLEEVES

STAGES = ["rules", "scorer", "factor_sleeve", "meta_label", "news", "sizing", "portfolio", "cost", "risk", "execution"]
SHADOW_KINDS = ["meta_label", "conformal", "portfolio", "factor_sleeve"] + [f"scorer_{s}" for s in SLEEVES]


class ModelSet:
    """Acting model per kind = champion (or None). Shadow = challenger. use_challengers=True is a
    research-sim switch only (never used by the core loop); models still only shrink/drop."""

    KINDS = [f"scorer_{s}" for s in SLEEVES] + ["regime", "vol", "meta_label", "conformal", "portfolio", "factor_sleeve",
                                              "cost", "execution", "strat_vol_managed", "strat_trend_switch"]
    OVERLAY_KINDS = ("strat_vol_managed", "strat_trend_switch")   # exposure overlays: multiply sizing by m in [0, 1]

    def __init__(self, root=None, use_challengers: bool = False, audit=None, preloaded: dict | None = None):
        self.root, self.use_challengers = root, use_challengers
        self.acting: dict = {}
        self.shadow: dict = {}
        self.ids: dict = {}
        self.audit = audit
        if preloaded is not None:
            self.acting = dict(preloaded)
            return
        if root is None:
            return
        from atlas.models.quant.multi import registry_for
        for k in self.KINDS:
            try:
                reg = registry_for(root, k)
            except Exception:
                continue
            champ, chal = reg.champion, reg.challenger
            act = champ or (chal if use_challengers else None)
            if act:
                try:
                    self.acting[k] = reg.load(act); self.ids[k] = act
                except Exception as e:  # noqa: BLE001  integrity failure -> fallback
                    if audit:
                        audit.append("ml.load_refused", {"kind": k, "model_id": act, "error": str(e)})
            if chal and chal != act:
                try:
                    self.shadow[k] = reg.load(chal); self.ids[f"{k}:shadow"] = chal
                except Exception:
                    pass


@dataclass
class Candidate:
    symbol: str
    side: str
    sleeve: str
    instrument: object
    close: pd.Series
    volume: pd.Series
    trail: list = field(default_factory=list)
    mult: float = 1.0
    p: float | None = None
    shadow: dict = field(default_factory=dict)
    features: pd.DataFrame | None = None
    dropped: str | None = None

    def log(self, stage: str, detail: str, effect: str = "pass", **kw):
        self.trail.append({"stage": stage, "detail": detail, "effect": effect, **kw})


def _sleeve_pct(cfg, sleeve: str) -> float:
    s = cfg.risk.sleeves.get(sleeve) if isinstance(cfg.risk.sleeves, dict) else getattr(cfg.risk.sleeves, sleeve, None)
    if s is None:
        return 0.0
    return float(s.get("target_pct", 0) if isinstance(s, dict) else getattr(s, "target_pct", 0))
