"""evo-20: rolling walk-forward retraining of the 1m / 5m horizon bundles on new real bars (research only, execution_permission none).

A challenger is trained on the newest real bars (``horizons.train_pool``: chronological fit / calibration / hold-out with an embargo), then compared with
the incumbent ONLY on real bars that arrived after the incumbent's last training bar plus a purge gap, and that the challenger itself never saw (its
hold-out block). Both models therefore score on bars neither trained on: no leakage in the comparison.  The challenger is promoted when its pinball loss
is no worse; otherwise the incumbent stays and the decision is logged.  The previous bundle is kept as ``.prev`` for rollback.
Nothing here writes to the bar store; no keyed FRED data is used (the context columns come from the same keyless sources as the trainer)."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from atlas.ai.prediction import horizons as HZ

PURGE_ROWS = 5               # extra purge on top of the 2-row embargo between the incumbent's last training bar and the comparison window
MIN_EVAL_ROWS = 200          # fewer unseen rows than this and the incumbent stays (no decision on noise)
MAX_AGE_S = {"1m": 6 * 3600, "5m": 12 * 3600}
MIN_NEW_ROWS = {"1m": 1200, "5m": 400}       # new pooled rows since the incumbent's data_end before a retrain is worth running
LOG = "roll.jsonl"


def cell_dir(pool: str, h: str, root=None) -> Path:
    return HZ.root_path(root) / f"{pool}-{h}"


def _bundle_pin(bundle: dict, rows: pd.DataFrame, model: str) -> tuple[float | None, int]:
    feats = bundle.get("features") or []
    if model not in bundle.get("models", {}) or any(f not in rows.columns for f in feats):
        return None, 0
    X = rows[feats].to_numpy(float)
    sig, y = rows["__sigma"].to_numpy(float), rows["__y"].to_numpy(float)
    q = HZ._pred(bundle["models"][model], X) * sig[:, None]
    return HZ.pinball_mean(y, q), int(len(y))


def compare(incumbent: dict | None, challenger: dict, rows: pd.DataFrame, data_end: int | None, test_slice: slice) -> dict[str, Any]:
    """Pinball (bps) of both bundles on the challenger's hold-out rows that are also strictly after the incumbent's data (+ purge). Leak-free by construction."""
    held = rows.iloc[test_slice]
    if incumbent is not None and data_end is not None:
        held = held[held["__t"] > data_end]
        held = held.iloc[PURGE_ROWS:] if len(held) > PURGE_ROWS else held.iloc[0:0]
    out: dict[str, Any] = {"n_eval": int(len(held)), "model": None, "incumbent_pin_bps": None, "challenger_pin_bps": None}
    if len(held) == 0:
        return out
    for model in ("lgbm", "xgb"):
        c, n = _bundle_pin(challenger, held, model)
        if c is None:
            continue
        out.update(model=model, challenger_pin_bps=round(c * 1e4, 4))
        if incumbent is not None:
            i, _ = _bundle_pin(incumbent, held, model)
            out["incumbent_pin_bps"] = None if i is None else round(i * 1e4, 4)
        break
    return out


def decide(cmp: dict, inc_exists: bool, age_s: float | None, max_age_s: float) -> tuple[str, str]:
    if not inc_exists:
        return "promote", "no incumbent bundle"
    if cmp["challenger_pin_bps"] is None:
        return "keep", "challenger has no comparable model"
    if cmp["incumbent_pin_bps"] is None:
        return "promote", "incumbent features/model not comparable (feature set changed)"
    if cmp["n_eval"] < MIN_EVAL_ROWS:
        return "keep", f"only {cmp['n_eval']} unseen rows (need {MIN_EVAL_ROWS}); incumbent stays"
    if cmp["challenger_pin_bps"] <= cmp["incumbent_pin_bps"]:
        return "promote", f"challenger pinball {cmp['challenger_pin_bps']} <= incumbent {cmp['incumbent_pin_bps']} bps on {cmp['n_eval']} unseen real bars"
    return "keep", f"challenger pinball {cmp['challenger_pin_bps']} > incumbent {cmp['incumbent_pin_bps']} bps on {cmp['n_eval']} unseen real bars"


def build_rows(feed, pool: str, h: str, max_bars: int, ref_loader: Callable | None, events, extra, symbols: list[str]) -> tuple[pd.DataFrame | None, list[str]]:
    iv = HZ.HORIZONS[h][0]
    frames, used = [], []
    for ins in symbols:
        try:
            bars = HZ.load_bars(feed, ins, iv)[-max_bars:]
            f = HZ.make_xy(bars, iv, pool, ins, ref_loader, events, extra)
        except Exception:  # noqa: BLE001
            continue
        if f is not None and len(f):
            frames.append(f)
            used.append(ins)
    return (pd.concat(frames, ignore_index=True) if frames else None), used


def retrain_cell(pool: str, h: str, rows: pd.DataFrame, used: list[str], now: float | None = None, root=None, force: bool = False) -> dict[str, Any]:
    """Train a challenger from ``rows`` and promote it only if it beats the incumbent on unseen real bars. ``rows`` is a pooled ``make_xy`` frame."""
    now = float(time.time() if now is None else now)
    d = cell_dir(pool, h, root)
    man, inc = HZ.load_bundle(pool, h, root)
    res: dict[str, Any] = {"pool": pool, "horizon": h, "at": int(now), "execution_permission": "none"}
    de = (man or {}).get("data_end") or (man or {}).get("created_at")     # a pre-evo-20 manifest has no data_end: its creation time is a safe upper bound
    if man is not None and not force:
        new_rows = int((rows["__t"] > (de or 0)).sum())
        age = now - float(man.get("created_at") or 0)
        if new_rows < MIN_NEW_ROWS[h] and age < MAX_AGE_S[h]:
            return {**res, "decision": "skip", "reason": f"{new_rows} new rows since data_end (< {MIN_NEW_ROWS[h]}) and bundle is {age / 3600:.1f} h old"}
    cand_root = d.parent / ".cand"
    r = HZ.train_pool(rows, pool, h, root=cand_root, instruments=used)
    if r.get("status") != "ok":
        return {**res, "decision": "keep", "reason": f"challenger not trained: {r.get('status')}", "detail": {k: r.get(k) for k in ("rows", "need")}}
    _, chal = HZ.load_bundle(pool, h, cand_root)
    n = len(rows.sort_values("__t", kind="stable"))
    srt = rows.sort_values("__t", kind="stable").reset_index(drop=True)
    cmp = compare(inc, chal, srt, de, HZ.split_slices(n)["test"])
    decision, why = decide(cmp, man is not None, (now - float(man["created_at"])) if man else None, MAX_AGE_S[h])
    if decision == "promote":
        cdir = cand_root / f"{pool}-{h}"
        if d.exists():
            prev = d.with_name(d.name + ".prev")
            if prev.exists():
                shutil.rmtree(prev)
            shutil.move(str(d), str(prev))
        shutil.move(str(cdir), str(d))
        HZ._CACHE.pop(str(d), None)
    else:
        shutil.rmtree(cand_root / f"{pool}-{h}", ignore_errors=True)
    out = {**res, "decision": decision, "reason": why, "compare": cmp, "data_end": r.get("data_end"), "n_rows": r.get("n_rows"), "instruments": len(used)}
    log = HZ.root_path(root) / LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        fh.write(json.dumps(out) + "\n")
    return out


def roll_status(root=None, tail: int = 50) -> dict[str, Any]:
    log = HZ.root_path(root) / LOG
    rows = []
    if log.exists():
        for ln in log.read_text().splitlines()[-tail:]:
            try:
                rows.append(json.loads(ln))
            except ValueError:
                continue
    cells = {}
    for pool in ("crypto",):
        for h in ("1m", "5m"):
            man, _ = HZ.load_bundle(pool, h, root)
            last = next((r for r in reversed(rows) if r.get("pool") == pool and r.get("horizon") == h), None)
            cells[f"{pool}-{h}"] = {"trained_at": (man or {}).get("created_at"), "data_end": (man or {}).get("data_end"), "last_decision": last}
    return {"cells": cells, "recent": rows[-10:], "rule": f"promote only if pinball <= incumbent on >= {MIN_EVAL_ROWS} real bars neither model trained on; "
            f"previous bundle kept as .prev", "execution_permission": "none", "label": HZ.LABEL}
