"""Challenger harness: trial logging + Deflated Sharpe + registry registration (challenger only)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from atlas.models.quant.metrics import deflated_sharpe
from atlas.models.quant.stack2 import all_trial_srs, log_trial

# Items whose output is a deterministic carry/cost/tax saving or a report, not a forecast. Their trials go
# to a SEPARATE pool (root/_nonalpha/<kind>/trials.jsonl, outside the alpha glob) so near-zero-variance
# savings streams can't inflate E[max SR] and wrongly deflate the alpha challengers. Their DSR is still
# computed (within the non-alpha pool) and logged; the promotion gate treats them like other non-alpha
# kinds, and promotion still needs >= 4 shadow weeks + owner sign-off.
NON_ALPHA_STRATS = {"strat_cash_yield", "strat_fx_cost", "strat_interlisted", "strat_tlh", "strat_tax_location", "strat_timing_auction"}
DSR_MIN = 0.95


@dataclass
class StratModel:
    """Registry artefact for a rule-based challenger: its parameters (digest-checked on load)."""
    name: str
    params: dict = field(default_factory=dict)

    def save(self, d) -> None:
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        (d / "strat.json").write_text(json.dumps({"name": self.name, "params": self.params}, sort_keys=True, default=str))

    @classmethod
    def load(cls, d) -> "StratModel":
        j = json.loads((Path(d) / "strat.json").read_text())
        return cls(j["name"], j["params"])


def _register_kind(kind: str) -> None:
    from atlas.models.quant import zoo
    from atlas.models.quant.stack2 import NON_ALPHA_KINDS
    zoo.register_kind(kind, StratModel)
    if kind in NON_ALPHA_STRATS:
        NON_ALPHA_KINDS.add(kind)


def evaluate_challenger(root, name: str, returns, params: dict, note: str = "", register: bool = True) -> dict:
    """Log one experiment, deflate its Sharpe by EVERY trial under `root`, and (optionally) register it
    as a challenger. Returns {"kind","sr","dsr","gate_dsr","model_id"}."""
    kind = f"strat_{name}"
    r = np.asarray(returns, float)
    r = r[np.isfinite(r)]
    non_alpha = kind in NON_ALPHA_STRATS
    pool = Path(root) / "_nonalpha" if non_alpha else Path(root)
    log_trial(pool, kind, params, r, note)
    dsr = deflated_sharpe(r, all_trial_srs(pool))
    out = {"kind": kind, "sr_annual": dsr["sr_annual"], "dsr": dsr["dsr"], "n_trials": dsr["n_trials"],
           "gate_dsr": bool(non_alpha or dsr["dsr"] > DSR_MIN), "non_alpha": non_alpha, "model_id": None}
    if register:
        _register_kind(kind)
        from atlas.models.quant.registry import ModelRegistry
        reg = ModelRegistry(Path(root) / kind, model_cls=StratModel, kind=kind)
        mid = reg.register(StratModel(name, params), {"validation": {"dsr": dsr["dsr"], "n_trials": dsr["n_trials"],
                                                                     "sr_annual": dsr["sr_annual"]},
                                                      "feature_importance_stability_spearman": 1.0}, actor="learning_loop")
        reg.make_challenger(mid, actor="learning_loop")  # challenger = shadow only; promotion needs owner + gates
        out["model_id"] = mid
    return out


def strat_registry(root, name: str):
    from atlas.models.quant.registry import ModelRegistry
    kind = f"strat_{name}"
    _register_kind(kind)
    return ModelRegistry(Path(root) / kind, model_cls=StratModel, kind=kind)
