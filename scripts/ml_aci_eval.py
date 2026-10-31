#!/usr/bin/env python
"""Compare split conformal with adaptive conformal on a scored stream. Does not enable ACI.

  PYTHONPATH=src python scripts/ml_aci_eval.py --demo
  PYTHONPATH=src python scripts/ml_aci_eval.py --csv scores.csv --out var/ml/aci_eval.json

The CSV needs columns t, exit_at, p, y. ``--demo`` uses a synthetic exchangeable stream and does not train.
``enable_aci`` in the report is always false. Set ATLAS_ML_ACI=1 yourself after you accept the coverage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from atlas.ai.ml.aci_eval import evaluate_aci_vs_split


def demo_stream(n: int = 400, seed: int = 0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 900 + 1_700_000_000
    exit_at = t + 3600
    p = np.clip(rng.normal(0.45, 0.08, n), 0.05, 0.95)
    y = (rng.random(n) < p).astype(int)
    return t, exit_at, p, y


def from_csv(path: Path):
    import pandas as pd
    df = pd.read_csv(path)
    return df["t"].to_numpy(), df["exit_at"].to_numpy(), df["p"].to_numpy(), df["y"].to_numpy()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if not a.demo and a.csv is None:
        ap.print_help()
        return 0
    t, e, p, y = demo_stream() if a.demo or a.csv is None else from_csv(a.csv)
    rep = evaluate_aci_vs_split(t, e, p, y)
    text = json.dumps(rep, indent=1)
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
