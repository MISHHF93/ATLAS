"""ML filter stage in the decision pipeline. Filters/ranks rule candidates only:
output is a SUBSET of the input with qty <= input qty. Model failure => policy fallback
(rules_only_half_size or halt)."""
from __future__ import annotations

import numpy as np
import pandas as pd


class MLFilterStage:
    def __init__(self, model, cfg, audit=None):
        self.model, self.cfg, self.audit = model, cfg, audit

    def apply(self, candidates: list[tuple[object, pd.DataFrame]]) -> list[dict]:
        """candidates: [(OrderIntent, 1-row feature frame)] -> [{intent, p_hit, shap_top, fallback}] sorted by p_hit."""
        if not self.cfg.enabled:
            return [{"intent": i, "p_hit": None, "shap_top": [], "fallback": "ml_disabled"} for i, _ in candidates]
        try:
            if self.model is None:
                raise RuntimeError("no champion model")
            X = pd.concat([x for _, x in candidates]) if candidates else None
            p = self.model.p_hit(X) if X is not None else np.array([])
            expl = self.model.explain(X) if X is not None else []
            if not np.all(np.isfinite(p)):
                raise ValueError("non-finite scores")
        except Exception as e:  # noqa: BLE001
            if self.audit:
                self.audit.append("ml.fallback", {"error": str(e), "mode": self.cfg.fallback})
            if self.cfg.fallback == "halt":
                return []
            return [{"intent": i.model_copy(update={"qty": i.qty * 0.5}), "p_hit": None, "shap_top": [],
                     "fallback": "rules_only_half_size"} for i, _ in candidates]
        out = [{"intent": i, "p_hit": float(pi), "shap_top": ex, "fallback": None}
               for (i, _), pi, ex in zip(candidates, p, expl) if pi >= self.cfg.min_p_hit]
        return sorted(out, key=lambda r: -r["p_hit"])
