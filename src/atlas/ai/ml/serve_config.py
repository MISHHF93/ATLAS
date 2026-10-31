"""Serve-time switches. Defaults keep the pre-declared split-conformal path.

``ATLAS_ML_ACI=1`` is the only way adaptive conformal changes a live take. Nothing here
writes that variable. Evaluation is ``scripts/ml_aci_eval.py``.
"""
from __future__ import annotations

import os

ACI_ENV = "ATLAS_ML_ACI"


def aci_enabled(env: dict | None = None) -> bool:
    src = os.environ if env is None else env
    return str(src.get(ACI_ENV, "")).strip().lower() in {"1", "true", "on", "yes"}
