"""One serving path for every model store.

Stores (unchanged, not duplicated):
  * ``atlas.ml.registry``            on-disk versioned manifests (var/ml/registry); ``eligible`` only when all gates pass
  * ``atlas.models.quant.registry``  champion/challenger stores per kind (var/models/<kind>)
  * ``atlas.models.predict``         the in-memory serving registry behind the one prediction contract ``predict()``

``catalog()`` lists all three side by side. ``load_quant_champion`` / ``atlas.ml.registry.load_eligible`` are the
only ways a stored model reaches the serving registry. ``serve()`` is the single decision path:
predict() -> evaluate_candidate() -> drift -> conflicting-evidence -> one status:

  TRADE_CANDIDATE       calibrated, in scope, edge after costs, no drift alarm, no conflict (still only a PROPOSAL:
                        the deterministic control plane approves/sizes; execution_permission stays "none")
  LOW_CONFIDENCE        uncalibrated / uncertainty too wide / edge below threshold / moderate drift
  CONFLICTING_EVIDENCE  higher-timeframe bias or an opposing same-bar candidate disagrees
  INSUFFICIENT_DATA     stale / missing / future-leaking features, data-quality flags, too few drift samples
  UNFAVORABLE_COSTS     costs consume the gross edge
  NO_TRADE              no validated model, unknown model, scope/horizon/semantics/geometry failure, significant drift
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from atlas.models import opportunity as opp
from atlas.models.predict import DEFAULT_REGISTRY, ModelRegistry, RegisteredModel

STATUSES = ("TRADE_CANDIDATE", "LOW_CONFIDENCE", "CONFLICTING_EVIDENCE", "INSUFFICIENT_DATA",
            "UNFAVORABLE_COSTS", "NO_TRADE")

_INSUFFICIENT = {"stale_data", "missing_features", "feature_from_future", "data_quality", "drift_insufficient_data"}
_NO_TRADE = {"no_validated_model", "unknown_model", "horizon_mismatch", "instrument_out_of_scope",
             "calibration_unsupported", opp.PROB_SEMANTICS, opp.BAD_GEOMETRY, "drift_significant"}
_COSTS = {opp.COSTS}
_LOW = {"uncalibrated", "uncertainty_unavailable", "uncertainty_too_wide", opp.INSUFFICIENT_EDGE, "drift_moderate"}
_CONFLICT = {"htf_bias_conflict", "opposing_candidate_same_bar"}
_ORDER = (("INSUFFICIENT_DATA", _INSUFFICIENT), ("NO_TRADE", _NO_TRADE), ("CONFLICTING_EVIDENCE", _CONFLICT),
          ("UNFAVORABLE_COSTS", _COSTS), ("LOW_CONFIDENCE", _LOW))


def classify(reasons: Iterable[str]) -> str:
    """Map reason codes to exactly one status (most restrictive first). Unknown codes fail closed to NO_TRADE."""
    rs = set(reasons)
    if not rs:
        return "TRADE_CANDIDATE"
    for status, codes in _ORDER:
        if rs & codes:
            return status
    return "NO_TRADE"


# --------------------------------------------------------------------------------------------- drift
@dataclass
class DriftGuard:
    """PSI of recent live feature rows vs the training reference (atlas.ml.drift), plus ADWIN on resolved errors."""
    reference: dict
    min_n: int = 50
    window: int = 200
    rows: list[dict[str, float]] = field(default_factory=list)
    errors: list[float] = field(default_factory=list)

    def observe(self, values: dict[str, Any]) -> None:
        self.rows = (self.rows + [{k: v for k, v in values.items() if isinstance(v, (int, float))}])[-self.window:]

    def resolve(self, probability: float, success: bool) -> None:
        self.errors.append(abs(float(success) - probability))

    def report(self) -> dict[str, Any]:
        import pandas as pd

        from atlas.ml.drift import adwin_report, feature_psi
        psi = feature_psi(self.reference, pd.DataFrame(self.rows), min_n=self.min_n) if self.rows else \
            {"status": "insufficient_data", "n_current": 0, "features": [], "max_psi": None}
        ad = adwin_report(self.errors) if len(self.errors) >= 20 else {"detected": False, "n": len(self.errors)}
        return {"psi": psi, "adwin": ad}

    def reasons(self) -> list[str]:
        rep = self.report()
        st = rep["psi"]["status"]
        out = []
        if st == "significant" or rep["adwin"].get("detected"):
            out.append("drift_significant")
        elif st == "moderate":
            out.append("drift_moderate")
        elif st == "insufficient_data":
            out.append("drift_insufficient_data")
        return out


def conflict_reasons(candidate: Any, *, htf_bias: str | None = None,
                     same_bar: Sequence[Any] = ()) -> list[str]:
    out = []
    d = getattr(candidate, "direction", None)
    if htf_bias in ("long", "short") and d in ("long", "short") and htf_bias != d:
        out.append("htf_bias_conflict")
    if any(o is not candidate and o.instrument == candidate.instrument and o.detected_at == candidate.detected_at
           and o.direction != d for o in same_bar):
        out.append("opposing_candidate_same_bar")
    return out


# --------------------------------------------------------------------------------------------- serve
@dataclass
class ServingDecision:
    candidate_id: str
    instrument: str
    status: str
    reasons: list[str]
    model_version: str | None
    probability: float | None
    expected_value_r: float | None
    calibration_status: str
    drift: dict[str, Any] | None = None
    correlation_id: str | None = None
    execution_permission: str = "none"
    note: str = "proposal status only; the deterministic control plane approves and sizes"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def serve(candidate: Any, *, model_version: str | None = None, registry: ModelRegistry | None = None,
          cost_per_unit: float = 0.0, drift: DriftGuard | None = None, htf_bias: str | None = None,
          same_bar: Sequence[Any] = (), require_drift: bool = False, **kw: Any):
    """Returns (prediction, evaluation, ServingDecision). Never routes or sizes anything."""
    from atlas.features.price_action.proposals import candidate_snapshot, evaluate
    from atlas.ops.correlation import current
    pred, ev = evaluate(candidate, model_version=model_version, registry=registry, cost_per_unit=cost_per_unit, **kw)
    reasons = list(dict.fromkeys(ev.abstention_reason))
    drep = None
    if drift is not None:
        drift.observe(dict(candidate_snapshot(candidate).values))
        drep = drift.report()
        dr = drift.reasons()
        if dr == ["drift_insufficient_data"] and not require_drift:
            dr = []
        reasons += dr
    elif require_drift:
        reasons.append("drift_insufficient_data")
    reasons += conflict_reasons(candidate, htf_bias=htf_bias, same_bar=same_bar)
    cid = current()
    dec = ServingDecision(candidate.candidate_id, candidate.instrument, classify(reasons), reasons,
                          getattr(pred, "model_version", None), ev.probability, ev.expected_value_r,
                          getattr(pred, "calibration_status", "none"), drep, None if cid == "-" else cid)
    return pred, ev, dec


# --------------------------------------------------------------------------------------------- catalog
def load_quant_champion(root: str | Path, kind: str, registry: ModelRegistry | None = None) -> str | None:
    """Expose a quant-store CHAMPION through predict(). Only champions (promotion gates passed) load; the target is
    the quant trade-filter label, so setup proposals see probability_semantics_mismatch -> NO_TRADE (by design)."""
    import pandas as pd

    from atlas.models.quant.registry import ModelRegistry as QuantRegistry
    q = QuantRegistry(Path(root), kind=kind)
    mid = q.champion
    reg = registry or DEFAULT_REGISTRY
    if not mid or mid in reg.versions():
        return None
    m = q.load(mid)
    feats = tuple(m.features)

    def score(vals, m=m, feats=feats):
        return float(m.p_hit(pd.DataFrame([{k: vals[k] for k in feats}]))[0])
    reg.register(RegisteredModel(model_version=f"quant:{kind}:{mid}", data_version=q.idx["models"][mid].get("data_hash") or "",
                                 horizon=f"quant_{kind}", target="trade_filter_hit", required_features=feats,
                                 score_fn=score, calibrator=None, validated_outputs=frozenset({"probability_positive"})))
    return f"quant:{kind}:{mid}"


def catalog(*, ml_root: str | Path | None = None, quant_root: str | Path | None = None,
            serving: ModelRegistry | None = None) -> dict[str, Any]:
    from atlas.ml import registry as mlreg
    from atlas.models.quant.registry import ModelRegistry as QuantRegistry
    reg = serving or DEFAULT_REGISTRY
    live = set(reg.versions())
    rows: list[dict[str, Any]] = []
    for m in mlreg.list_models(ml_root):
        rows.append({"store": "ml", "model_version": m.get("version"), "status": m.get("status"),
                     "eligible": m.get("status") == "eligible", "served": m.get("version") in live,
                     "target": mlreg.TARGET, "horizon": mlreg.HORIZON, "created_at": m.get("created_at")})
    qr = Path(quant_root) if quant_root else None
    if qr and qr.exists():
        for d in sorted(p for p in qr.iterdir() if (p / "index.json").exists()):
            q = QuantRegistry(d, kind=d.name)
            for mid, m in q.idx["models"].items():
                rows.append({"store": "quant", "kind": d.name, "model_version": f"quant:{d.name}:{mid}",
                             "status": m.get("stage"), "eligible": m.get("stage") == "champion",
                             "served": f"quant:{d.name}:{mid}" in live, "target": "trade_filter_hit",
                             "horizon": f"quant_{d.name}", "created_at": m.get("created")})
    for v in sorted(live):
        if not any(r["model_version"] == v for r in rows):
            rm = reg._m[v]
            rows.append({"store": "serving", "model_version": v, "status": "registered_in_memory", "eligible": True,
                         "served": True, "target": rm.target, "horizon": rm.horizon, "created_at": None})
    return {"models": rows, "n_served": len(live), "statuses": list(STATUSES),
            "default_behaviour": "abstain(no_validated_model) when nothing is served", "execution_permission": "none"}
