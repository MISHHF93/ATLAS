"""Model registry: candidate -> challenger (shadow/paper) -> champion -> archived.

* Models can NEVER promote themselves: promotion requires actor in {"owner", "learning_loop"}
  and, at autonomy level >= owner_signoff_at_level_ge, actor == "owner" with step-up.
* Gates (all must pass): >= min_shadow_weeks distinct ISO weeks of shadow results AND >= 7*weeks
  days elapsed since entering challenger; after-cost lift >= min_lift_bps vs champion (or rules-only);
  Brier not worse than champion by > max_brier_worsening; shadow drawdown <= max_drawdown_pct;
  feature-importance stability >= 0.3.
* Rollback to the previous champion is one call (owner)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from atlas.ai.models.quant.model import TradeFilterModel

STAGES = ("candidate", "challenger", "champion", "archived")
ALLOWED_PROMOTERS = {"owner", "learning_loop"}


class PromotionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    value: object
    threshold: object


def dir_digest(d: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file() and p.name not in ("model_card.md", "model_card.json", "reference.json")):
        h.update(f.relative_to(d).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()


DEMOTERS = {"owner", "learning_loop", "drift_monitor", "autonomy_evaluator"}


class ModelRegistry:
    def __init__(self, root: str | Path, audit=None, clock=lambda: datetime.now(timezone.utc), model_cls=None, kind: str = "trade_filter"):
        self.model_cls = model_cls or TradeFilterModel
        self.kind = kind
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit, self.clock = audit, clock
        self.idx_path = self.root / "index.json"
        self.idx = json.loads(self.idx_path.read_text()) if self.idx_path.exists() else {"models": {}, "history": []}

    def _save(self) -> None:
        tmp = self.idx_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.idx, indent=1, default=str))
        tmp.replace(self.idx_path)

    def _log(self, event: str, payload: dict, actor: str) -> None:
        self.idx["history"].append({"ts": self.clock().isoformat(), "event": event, "actor": actor, **payload})
        if self.audit:
            self.audit.append(f"ml.{event}", payload, actor=actor)

    # ---------------------------------------------------------------- lifecycle
    def register(self, model, metrics: dict, data_hash: str = "", actor: str = "learning_loop", card=None,
                 reference=None) -> str:
        """card: ModelCard (written as model_card.md/json); reference: DataFrame sample for drift (PSI)."""
        import shutil
        n = len(self.idx["models"]) + 1
        tmp = self.root / "_staging"
        if tmp.exists():
            shutil.rmtree(tmp)
        model.save(tmp)
        digest = dir_digest(tmp)
        mid = f"m{n:04d}-{digest[:8]}"
        if reference is not None:
            from atlas.ai.models.quant.drift import reference_stats
            (tmp / "reference.json").write_text(json.dumps(reference_stats(reference)))
        tmp.rename(self.root / mid)
        if card is not None:
            card.write(self.root / mid, model_id=mid, metrics=_jsonable(metrics), data_hash=data_hash)
        self.idx["models"][mid] = {"stage": "candidate", "created": self.clock().isoformat(), "digest": digest, "kind": self.kind,
                                   "data_hash": data_hash, "metrics": _jsonable(metrics), "shadow": {}, "challenger_since": None,
                                   "has_card": card is not None}
        self._log("register", {"model_id": mid}, actor)
        self._save()
        return mid

    def stage(self, mid: str) -> str:
        return self.idx["models"][mid]["stage"]

    def by_stage(self, stage: str) -> list[str]:
        return [k for k, v in self.idx["models"].items() if v["stage"] == stage]

    @property
    def champion(self) -> str | None:
        c = self.by_stage("champion")
        return c[0] if c else None

    @property
    def challenger(self) -> str | None:
        c = self.by_stage("challenger")
        return c[0] if c else None

    def load(self, mid: str):
        """Integrity-checked load: the on-disk artefacts must match the registered digest."""
        d = self.root / mid
        if dir_digest(d) != self.idx["models"][mid]["digest"]:
            raise PermissionError(f"model {mid} artefacts changed since registration (refusing to load)")
        return self.model_cls.load(d)

    def reference(self, mid: str) -> dict | None:
        p = self.root / mid / "reference.json"
        return json.loads(p.read_text()) if p.exists() else None

    def demote(self, actor: str, reason: str) -> str | None:
        """Risk-reducing: retire the champion and restore the previous champion (or none => fallback).
        Allowed for automated monitors; promotion is NOT."""
        if actor not in DEMOTERS:
            raise PromotionDenied(f"{actor!r} cannot demote")
        cur = self.champion
        if cur is None:
            return None
        self.idx["models"][cur]["stage"] = "archived"
        self.idx["models"][cur]["demoted"] = reason
        prev = self.idx.get("previous_champion")
        restored = None
        if prev and prev in self.idx["models"] and self.idx["models"][prev]["stage"] == "archived" and not self.idx["models"][prev].get("demoted"):
            self.idx["models"][prev]["stage"] = "champion"
            restored = prev
        self.idx["previous_champion"] = None
        self._log("demote", {"model_id": cur, "restored": restored, "reason": reason}, actor)
        self._save()
        return restored

    def summary(self) -> dict:
        ms = self.idx["models"]
        last = max((v["created"] for v in ms.values()), default=None)
        drift = [h for h in self.idx["history"] if h["event"] in ("drift_check", "demote")]
        return {"kind": self.kind, "champion": self.champion, "challenger": self.challenger, "n_models": len(ms),
                "last_retrain": last, "last_drift": drift[-1] if drift else None}

    def make_challenger(self, mid: str, actor: str = "learning_loop") -> None:
        if actor not in ALLOWED_PROMOTERS:
            raise PromotionDenied(f"{actor!r} cannot change model stages")
        if self.stage(mid) != "candidate":
            raise ValueError("only a candidate can become challenger")
        for old in self.by_stage("challenger"):
            self.idx["models"][old]["stage"] = "archived"
            self._log("archive", {"model_id": old, "reason": "replaced by new challenger"}, actor)
        self.idx["models"][mid] |= {"stage": "challenger", "challenger_since": self.clock().isoformat()}
        self._log("challenger", {"model_id": mid}, actor)
        self._save()

    def record_shadow_week(self, mid: str, week: str, result: dict) -> None:
        """result: {lift_bps, brier, champion_brier, drawdown_pct, n} for one ISO week (e.g. '2026-W42')."""
        self.idx["models"][mid]["shadow"][week] = _jsonable(result)
        self._save()

    # ---------------------------------------------------------------- gates
    def gates(self, mid: str, cfg) -> list[Gate]:
        m = self.idx["models"][mid]
        sh = m["shadow"]
        weeks = len(sh)
        since = m.get("challenger_since")
        days = (self.clock() - datetime.fromisoformat(since)).days if since else 0
        lift = sum(w["lift_bps"] * w.get("n", 1) for w in sh.values()) / max(1, sum(w.get("n", 1) for w in sh.values())) if sh else float("-inf")
        brier_d = max((w["brier"] - w["champion_brier"]) for w in sh.values()) if sh else float("inf")
        dd = max((w["drawdown_pct"] for w in sh.values()), default=float("inf"))
        stab = m["metrics"].get("feature_importance_stability_spearman", 0.0)
        stab = 0.0 if stab != stab else stab  # NaN
        val = m["metrics"].get("validation") or {}
        dsr = float(val.get("dsr", 0.0))
        pbo = val.get("pbo")
        min_dsr, max_pbo = getattr(cfg, "min_dsr", 0.95), getattr(cfg, "max_pbo", 0.5)
        from atlas.ai.models.quant.stack2 import NON_ALPHA_KINDS
        non_alpha = self.kind in NON_ALPHA_KINDS          # decided by registry kind, never by the model's metrics
        return [
            Gate("deflated_sharpe", non_alpha or dsr > min_dsr, "n/a (non-alpha kind)" if non_alpha else round(dsr, 4),
                 f"> {min_dsr} (n_trials={val.get('n_trials', 0)})"),
            Gate("pbo", non_alpha or pbo is None or pbo < max_pbo, pbo, f"< {max_pbo}"),
            Gate("stage_is_challenger", m["stage"] == "challenger", m["stage"], "challenger"),
            Gate("shadow_weeks", weeks >= cfg.min_shadow_weeks, weeks, cfg.min_shadow_weeks),
            Gate("shadow_days_elapsed", days >= 7 * cfg.min_shadow_weeks, days, 7 * cfg.min_shadow_weeks),
            Gate("after_cost_lift_bps", lift > cfg.min_lift_bps, round(lift, 3), f"> {cfg.min_lift_bps}"),
            Gate("brier_not_worse", brier_d <= cfg.max_brier_worsening, round(brier_d, 5), f"<= {cfg.max_brier_worsening}"),
            Gate("shadow_drawdown_pct", dd <= cfg.max_drawdown_pct, round(dd, 3), f"<= {cfg.max_drawdown_pct}"),
            Gate("feature_stability", stab >= 0.3, round(stab, 3), ">= 0.3"),
        ]

    def promote(self, mid: str, cfg, actor: str, autonomy_level: int, step_up_verified: bool = False) -> list[Gate]:
        if actor not in ALLOWED_PROMOTERS:
            self._log("promotion_denied", {"model_id": mid, "reason": f"actor {actor!r} not allowed"}, actor)
            self._save()
            raise PromotionDenied(f"{actor!r} cannot promote models (models never promote themselves)")
        if autonomy_level >= cfg.owner_signoff_at_level_ge and not (actor == "owner" and step_up_verified):
            raise PromotionDenied(f"owner sign-off with step-up required at autonomy level >= {cfg.owner_signoff_at_level_ge}")
        g = self.gates(mid, cfg)
        failed = [x.name for x in g if not x.passed]
        if failed:
            self._log("promotion_denied", {"model_id": mid, "failed": failed}, actor)
            self._save()
            raise PromotionDenied(f"promotion gates failed: {failed}")
        old = self.champion
        if old:
            self.idx["models"][old]["stage"] = "archived"
            self.idx["models"][old]["was_champion"] = True
        self.idx["models"][mid]["stage"] = "champion"
        self.idx["previous_champion"] = old
        self._log("promote", {"model_id": mid, "previous": old, "gates": [x.__dict__ for x in g]}, actor)
        self._save()
        return g

    def rollback(self, actor: str, step_up_verified: bool) -> str:
        if actor != "owner" or not step_up_verified:
            raise PromotionDenied("rollback is owner-only with step-up")
        prev = self.idx.get("previous_champion")
        if not prev:
            raise ValueError("no previous champion")
        cur = self.champion
        if cur:
            self.idx["models"][cur]["stage"] = "archived"
        self.idx["models"][prev]["stage"] = "champion"
        self.idx["previous_champion"] = cur
        self._log("rollback", {"to": prev, "from": cur}, actor)
        self._save()
        return prev


def _jsonable(d):
    return json.loads(json.dumps({k: v for k, v in d.items() if k != "final_model"}, default=str))
