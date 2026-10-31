"""Versioned on-disk model registry (var/ml/registry, git-ignored).

Each version directory holds ``manifest.json`` (data hash, per-series hashes, feature list, code sha, metrics,
gates, status), ``model.pkl`` and ``model_card.md``. ``status`` is ``eligible`` only when EVERY pre-declared gate
passed; otherwise ``not_eligible`` with the real numbers. Only eligible versions are ever loaded into
``atlas.models.predict`` registries (``load_eligible``). Versions are immutable: re-registering the same
(data hash, code sha, group) is a no-op.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_ROOT = "var/ml/registry"
HORIZON = "1d_triple_barrier"
TARGET = "meta_label_after_cost_r_positive"


def root(path: str | os.PathLike | None = None) -> Path:
    return Path(path or os.environ.get("ATLAS_ML_REGISTRY", DEFAULT_ROOT))


def repo_root() -> Path:
    """Directory that contains ``pyproject.toml`` and ``src/atlas``. Git commands must run here.

    ``code_sha`` used to use the package directory as cwd and then asked git for
    ``src/atlas/ai/ml``, a path that does not exist relative to that directory, so a dirty
    tree was reported clean and the next refresh reused the previous version id.
    """
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").is_file() and (p / "src" / "atlas").is_dir():
            return p
    return here.parents[4]


def code_sha() -> str:
    try:
        cwd = repo_root()
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, cwd=cwd).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src/atlas/ai/ml"], capture_output=True, text=True,
                               timeout=5, cwd=cwd).stdout.strip()
        return (sha or "unknown") + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def version_token(sha: str) -> str:
    """Short code id for a registry directory. A dirty tree does not reuse the clean commit's directory."""
    dirty = sha.endswith("-dirty")
    head = sha[: -len("-dirty")] if dirty else sha
    short = (head or "unknown")[:7]
    return f"{short}-dirty" if dirty else short


def _provider_cell(raw) -> str:
    names = [str(p) for p in (raw or []) if p]
    return "+".join(names) if names else "none"


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def is_eligible(gates: list[dict]) -> bool:
    return bool(gates) and all(g["passed"] for g in gates)


def model_card(man: dict[str, Any]) -> str:
    s = man["metrics"].get("primary") or {}
    lines = [f"# Model card: {man['version']}", "",
             f"- **Status:** {man['status']} (eligible for predict() only if every gate passed)",
             f"- **Group:** {man['group']}  |  **Target:** {man['target']}  |  **Horizon:** {man['horizon']}",
             f"- **Created (UTC):** {man['created_at']}  |  **Code sha:** {man['code_sha']}",
             f"- **Data hash:** {man['data_hash']} (feed `as_of` = {man.get('as_of')})",
             f"- **Model:** {man['model_kind']} meta-labeler over the price-action setup library; calibrator {man.get('calibrator')}; "
             f"conformal alpha {man.get('alpha')} (qhat {man.get('qhat')})",
             f"- **Intended use:** shadow-mode take/skip + size *proposal input* for detected setups. Never an order; "
             "the control plane and Safe stop keep final authority.", "",
             "## Out-of-sample (purged walk-forward, after costs)", "",
             "| metric | value |", "|---|---|"]
    for k in ("n_oos", "base_rate_oos", "brier", "brier_baseline", "brier_skill", "logloss", "logloss_baseline", "ece", "auc",
              "n_taken", "coverage", "mean_r_taken", "total_r_taken", "mean_r_all", "total_r_all"):
        lines.append(f"| {k} | {s.get(k)} |")
    lines.append(f"| DSR | {(s.get('dsr') or {}).get('dsr')} |")
    lines.append(f"| PBO | {(man['metrics'].get('pbo') or {}).get('pbo')} |")
    lines += ["", "## Gates", "", "| gate | passed | value | threshold |", "|---|---|---|---|"]
    lines += [f"| {g['gate']} | {g['passed']} | {g['value']} | {g['threshold']} |" for g in man["gates"]]
    lines += ["", "## Data", "", "| instrument | tf | providers | bars | rows | sha256[:12] |", "|---|---|---|---|---|---|"]
    lines += [f"| {x['instrument']} | {x['interval']} | {_provider_cell(x.get('providers'))} | {x['n_bars']} | {x['n_rows']} | {x['sha256'][:12]} |"
              for x in man["series"]]
    lines += ["", "## Limitations", "", "- Bar-level conservative fill model; costs are assumptions, not measured fills.",
              "- Equity 15m history is ~60 days (provider limit); equity results are weak evidence.",
              "- See docs/ml/limitations.md."]
    return "\n".join(lines) + "\n"


def register(group: str, out: dict[str, Any], meta: dict[str, Any], model: Any, path=None, now: datetime | None = None) -> dict[str, Any]:
    from atlas.ai.ml.dataset import FEATURES
    from atlas.ai.ml.train import ALPHA, PRIMARY
    r = root(path)
    sha = code_sha()
    series = []
    for s in meta["series"]:
        if f"{s['asset_class']}-{s['interval']}" != group:
            continue
        row = dict(s)
        row["providers"] = [p for p in (s.get("providers") or []) if p]
        series.append(row)
    import hashlib
    gh = hashlib.sha256("".join(s["sha256"] for s in series).encode()).hexdigest()
    version = f"atlas-meta-{group}-{gh[:10]}-{version_token(sha)}"
    d = r / version
    if (d / "manifest.json").exists():
        return json.loads((d / "manifest.json").read_text())
    gates = out.get("gates") or []
    man = {"version": version, "group": group, "status": "eligible" if is_eligible(gates) else "not_eligible",
           "created_at": (now or datetime.now(timezone.utc)).isoformat(), "code_sha": sha, "data_hash": gh,
           "as_of": meta.get("as_of"), "series": series, "features": list(FEATURES), "target": TARGET, "horizon": HORIZON,
           "model_kind": PRIMARY, "alpha": ALPHA,
           "calibrator": getattr(getattr(model, "calibrator", None), "kind", None),
           "qhat": getattr(getattr(model, "conformal", None), "qhat", None),
           "fitted_through": getattr(getattr(model, "calibrator", None), "fitted_through", None),
           "gates": gates,
           "metrics": {"primary": (out.get("variants") or {}).get(PRIMARY), "variants": out.get("variants"),
                       "take_all": out.get("take_all"), "pbo": out.get("pbo"), "per_instrument": out.get("per_instrument"),
                       "per_detector": out.get("per_detector"), "reliability": out.get("reliability"),
                       "folds": out.get("folds"), "n_rows": out.get("n_rows")}}
    man = _clean(man)
    d.mkdir(parents=True, exist_ok=True)
    if model is not None:
        (d / "model.pkl").write_bytes(pickle.dumps(model))
    (d / "model_card.md").write_text(model_card(man))
    (d / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True))
    return man


def list_models(path=None) -> list[dict[str, Any]]:
    r = root(path)
    if not r.exists():
        return []
    out = []
    for m in sorted(r.glob("*/manifest.json")):
        try:
            out.append(json.loads(m.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda m: m["created_at"], reverse=True)


def get(version: str, path=None) -> dict[str, Any] | None:
    if "/" in version or ".." in version:
        return None
    f = root(path) / version / "manifest.json"
    return json.loads(f.read_text()) if f.exists() else None


def load_model(version: str, path=None):
    f = root(path) / version / "model.pkl"
    return pickle.loads(f.read_bytes()) if f.exists() else None


def reconcile_refresh(report: dict[str, Any], path=None) -> dict[str, Any]:
    """Mark refresh groups whose version directory is not on disk.

    ``last_refresh.json`` can name versions that were deleted (the 2026-10-30 cleanup removed
    Binance-trained ``atlas-meta-crypto-*`` directories and left the report). A missing artifact
    is not eligible. Gate thresholds are not changed and nothing is promoted.
    """
    if not isinstance(report, dict):
        return {"status": "unreadable", "execution_permission": "none"}
    out = dict(report)
    groups: dict[str, Any] = {}
    reg = root(path)
    for key, g in (report.get("groups") or {}).items():
        if not isinstance(g, dict):
            groups[str(key)] = g
            continue
        g = dict(g)
        ver = g.get("version")
        if ver:
            safe = "/" not in str(ver) and ".." not in str(ver)
            if not safe or not (reg / str(ver) / "manifest.json").is_file():
                g["artifact"] = "missing"
                if g.get("status") == "eligible":
                    g["status"] = "not_eligible"
                g["artifact_note"] = "refresh names a version that is not in the registry; it cannot be loaded and is not eligible"
            else:
                g["artifact"] = "present"
        prov = g.get("providers")
        if isinstance(prov, list) and not [p for p in prov if p]:
            g["provider_status"] = "none"
            g.setdefault("provider_note", "no provider recorded on the stored bars for this group")
        groups[str(key)] = g
    out["groups"] = groups
    out["reconciled"] = True
    out["execution_permission"] = "none"
    return out


def load_eligible(registry=None, path=None) -> list[str]:
    """Register every *eligible* version into a predict() ModelRegistry. not_eligible versions are never loaded."""
    import pandas as pd

    from atlas.ai.models.predict import DEFAULT_REGISTRY, RegisteredModel
    reg = registry or DEFAULT_REGISTRY
    loaded = []
    for man in list_models(path):
        if man.get("status") != "eligible" or man["version"] in reg.versions():
            continue
        mm = load_model(man["version"], path)
        if mm is None:
            continue
        feats = tuple(man["features"])

        def score(vals, mm=mm, feats=feats):
            return float(mm.raw(pd.DataFrame([{k: vals[k] for k in feats}]))[0])
        reg.register(RegisteredModel(model_version=man["version"], data_version=man["data_hash"], horizon=HORIZON, target=TARGET,
                                     required_features=feats, score_fn=score, calibrator=mm.calibrator,
                                     validated_outputs=frozenset({"probability_positive"})))
        loaded.append(man["version"])
    return loaded
