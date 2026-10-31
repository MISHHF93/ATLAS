"""Read-only adaptive-conformal take for the meta-label serve path.

The score buffer and alpha live in a JSON file. A live request reads them and does not
append an outcome (the label is not known yet). ``note_resolved`` is the only writer,
and it no-ops unless ``ATLAS_ML_ACI`` is on. An empty buffer uses qhat 1.0, so the set
is {0, 1} and the ACI take is false: turning the flag on with no history abstains.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from atlas.ai.ml.directional.aci import empirical_qhat
from atlas.ai.ml.serve_config import aci_enabled

DEFAULT_STATE = "var/ml/aci_state.json"
ALPHA = 0.2
GAMMA = 0.01
WINDOW = 500


def state_path(path: str | os.PathLike | None = None) -> Path:
    return Path(path or os.environ.get("ATLAS_ML_ACI_STATE", DEFAULT_STATE))


def load_state(path: str | os.PathLike | None = None) -> dict[str, Any]:
    f = state_path(path)
    if f.exists():
        try:
            body = json.loads(f.read_text())
            if isinstance(body, dict):
                body.setdefault("scores", [])
                body.setdefault("alpha_t", body.get("alpha", ALPHA))
                return body
        except (OSError, ValueError):
            pass
    return {"alpha": ALPHA, "gamma": GAMMA, "window": WINDOW, "alpha_t": ALPHA, "scores": [], "n_resolved": 0}


def _save(body: dict[str, Any], path: str | os.PathLike | None) -> None:
    f = state_path(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body))
    os.replace(tmp, f)


def singleton_take(p: float, body: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    """True only when the ACI set is exactly {1}. Does not update alpha."""
    body = body if body is not None else load_state()
    scores = list(body.get("scores") or [])
    window = int(body.get("window") or WINDOW)
    alpha_t = float(body.get("alpha_t") if body.get("alpha_t") is not None else ALPHA)
    q = empirical_qhat(np.asarray(scores[-window:], float), alpha_t)
    s1, s0 = 1.0 - float(p), float(p)
    cset = {c for c, s in ((1, s1), (0, s0)) if s <= q}
    info = {"enabled": True, "alpha_t": alpha_t, "qhat": None if q == float("inf") else q,
            "n_scores": len(scores), "set": sorted(cset), "take": cset == {1},
            "execution_permission": "none"}
    return cset == {1}, info


def live_take(p: float, path: str | os.PathLike | None = None) -> tuple[bool, dict[str, Any]]:
    if not aci_enabled():
        return True, {"enabled": False, "execution_permission": "none"}
    return singleton_take(p, load_state(path))


def note_resolved(p: float, y: int, path: str | os.PathLike | None = None) -> dict[str, Any] | None:
    """One causal ACI update after the label exists. No-op while the flag is off."""
    if not aci_enabled():
        return None
    body = load_state(path)
    alpha = float(body.get("alpha") or ALPHA)
    gamma = float(body.get("gamma") or GAMMA)
    _, info = singleton_take(p, body)
    q = info["qhat"] if info["qhat"] is not None else float("inf")
    s_y = (1.0 - float(p)) if int(y) == 1 else float(p)
    err = 0.0 if s_y <= q else 1.0
    alpha_t = float(body.get("alpha_t") if body.get("alpha_t") is not None else alpha)
    body["alpha_t"] = alpha_t + gamma * (alpha - err)
    scores = list(body.get("scores") or [])
    scores.append(float(s_y))
    window = int(body.get("window") or WINDOW)
    body["scores"] = scores[-max(window, 1):]
    body["n_resolved"] = int(body.get("n_resolved") or 0) + 1
    body["execution_permission"] = "none"
    _save(body, path)
    return {"err": err, "alpha_t": body["alpha_t"], "n_resolved": body["n_resolved"], "execution_permission": "none"}
