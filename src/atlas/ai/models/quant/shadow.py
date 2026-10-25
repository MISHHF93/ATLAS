"""Champion/challenger shadow mode. The CHAMPION (or rules-only if none) drives paper
decisions; the CHALLENGER only scores and logs. Weekly roll-ups feed the registry gates."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from atlas.ai.models.quant.metrics import brier, max_drawdown_pct


@dataclass
class ShadowRunner:
    champion: object | None       # TradeFilterModel or None (=> rules-only baseline)
    challenger: object
    min_p_hit: float = 0.55
    log: list[dict] = field(default_factory=list)

    def score(self, d: date, key: str, X: pd.DataFrame) -> dict:
        ch = float(self.challenger.p_hit(X)[0])
        cp = float(self.champion.p_hit(X)[0]) if self.champion is not None else None
        rec = {"date": d, "key": key, "challenger_p": ch, "champion_p": cp,
               "challenger_take": ch >= self.min_p_hit,
               "champion_take": True if cp is None else cp >= self.min_p_hit, "outcome": None, "y": None}
        self.log.append(rec)
        return rec

    def record_outcome(self, key: str, fwd_after_cost: float) -> None:
        for r in self.log:
            if r["key"] == key and r["outcome"] is None:
                r["outcome"], r["y"] = fwd_after_cost, float(fwd_after_cost > 0)

    def weekly_rollup(self) -> dict[str, dict]:
        by = defaultdict(list)
        for r in self.log:
            if r["outcome"] is not None:
                y, w, _ = r["date"].isocalendar()
                by[f"{y}-W{w:02d}"].append(r)
        out = {}
        for wk, rs in sorted(by.items()):
            o = np.array([r["outcome"] for r in rs])
            ch_t = np.array([r["challenger_take"] for r in rs]); cp_t = np.array([r["champion_take"] for r in rs])
            ch_ret = (o * ch_t).mean(); cp_ret = (o * cp_t).mean()
            y = np.array([r["y"] for r in rs])
            cpp = np.array([r["champion_p"] if r["champion_p"] is not None else y.mean() for r in rs])
            out[wk] = {"n": len(rs), "lift_bps": float((ch_ret - cp_ret) * 1e4),
                       "brier": brier([r["challenger_p"] for r in rs], y), "champion_brier": brier(cpp, y),
                       "drawdown_pct": max_drawdown_pct(o * ch_t)}
        return out
