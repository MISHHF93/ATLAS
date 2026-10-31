"""15-minute BUY / SELL / HOLD signal model (milestone d). Research and paper shadow only.

What it is
  * Candidates are the existing price-action setups (dual_band_breakout, orb_retest, prior_day_range_reversal,
    wick_reversal) detected on REAL closed 15m bars. Each setup is one row, detected at a bar END ``T`` that lies on the 900 s
    decision clock (``dataset.build_rows`` reads the detection-time features from bars with end <= T).
  * Label = triple barrier from the conservative OHLC replay: upper = target, lower = stop, vertical = ``hold_bars``
    (the horizons chosen by ``horizon_tune.SELECTED_FOR_D``, never fewer than the 3-bar entry window). Meta label
    y = 1 iff the realized AFTER-COST R multiple > 0. Costs are the venue table in ``costs.py`` (crypto 124 bp round trip;
    US equity 4 bp + $0.01/share) and are inside the label, not added afterwards.
  * Features = the existing causal bar features + the ``multires`` layers that have real coverage for the group
    (``usable_layers``). Fast layers (1s / 1m / flow) have hours or weeks of history, not years, so they are excluded from
    training until coverage reaches ``MIN_LAYER_COVER`` and are logged by the live tick so that history accumulates.
    Direction-signed copies (``*_x_dir``) let a confirming flow raise and a contradicting flow lower the same setup.
  * Model = the existing meta-labeler (``train.fit_meta``: calibrated gradient boosting + split-conformal take rule), trained
    and scored with purged walk-forward folds (``cv.walk_forward_splits``: a training label whose exit overlaps the test
    window is dropped, plus a 1 day embargo). ``train.GATES`` is used as is. This module never edits a gate.
  * Action: BUY = a long setup the meta-model takes (EV_R > 0 after cost AND conformal set {1}); SELL = a short setup it takes
    (on spot crypto a bearish signal, not a position the venue allows); HOLD = everything else, including "no setup at T".

What it is not: an order, a size, a recommendation or a profitability claim. ``execution_permission`` is always ``none``.
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from atlas.ai.ml import multires as MR
from atlas.ai.ml import registry as REG
from atlas.ai.ml import train as TR
from atlas.ai.ml.dataset import FEATURES as BASE_FEATURES
from atlas.ai.ml.dataset import SeriesData, build_rows
from atlas.features.price_action.bars import Bar

SCHEMA = "atlas-signal15-v1"
LABEL = "Predicted signal, not advice"
EXECUTION_PERMISSION = "none"
MODE = "paper_shadow_only"
GATES = TR.GATES                      # the same object: never copied, never edited here
MIN_ENTRY_WINDOW = 3                  # replay entry_window; a shorter vertical barrier cannot be tested
MIN_LAYER_COVER = 0.60                # share of setup rows with at least one real value in a layer
# vertical barrier (15m bars) per asset class: horizon_tune selection, floored at the entry window, plus the
# pre-existing session/day barrier as the reference. 4 bars = 1 h, 26 = one RTH session, 32 = 8 h, 96 = 24 h.
HOLD_BARS = {"crypto": (32, 96), "equity": (4, 26), "gold": (4, 26)}
MR_SIGNED = ("m15_ret1", "m15_ret4", "m15_vwapdev16", "h1_ret1", "h1_ret6", "m5_ret1", "m1_ret15", "m1_vwapdev15",
             "f_ofi5", "f_ofi15", "f_vwapdev15", "s1_ret60", "s1_ofi60")
ROOT = Path("var/ml/signal15")


def load_sd(store, instrument: str, interval: str, provider: str, asset_class: str, start: int | None, end: int | None) -> SeriesData:
    """Confirmed real bars of ONE provider as a replay series (never mixes providers)."""
    fb = store.bars(instrument, interval, start, end, provider=provider, confirmed_only=True)
    dur = MR.BAR_S[interval]
    bars, last = [], None
    for b in fb:
        if last is not None and b.event_time <= last:
            continue
        try:
            bars.append(Bar(int(b.event_time), dur, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = b.event_time
    return SeriesData(instrument, interval, asset_class, bars, [provider])


def setup_frame(sd: SeriesData, inp: MR.Inputs, hold_bars: int, include_open: bool = False) -> pd.DataFrame:
    """Setup rows (triple-barrier labelled) with the multires features at each detection time T."""
    if hold_bars < MIN_ENTRY_WINDOW:
        raise ValueError(f"hold_bars {hold_bars} < entry window {MIN_ENTRY_WINDOW}")
    df = build_rows(sd, include_open=include_open, hold_bars=hold_bars)
    if df is None or len(df) == 0:
        return pd.DataFrame()
    cache: dict[int, dict[str, float]] = {}
    rows = []
    for t in df.t.to_numpy(np.int64):
        t = int(t)
        if t not in cache:
            cache[t] = MR.features_at(inp, t)
        rows.append(cache[t])
    mr = pd.DataFrame(rows, index=df.index, columns=list(MR.FEATURE_NAMES))
    df = pd.concat([df, mr], axis=1)
    d = np.where(df["dir_long"].to_numpy(float) > 0, 1.0, -1.0)
    for n in MR_SIGNED:
        df[f"{n}_x_dir"] = df[n].to_numpy(float) * d
    df["hold_bars"] = int(hold_bars)
    df["provider"] = sd.providers[0] if sd.providers else ""
    return df


def usable_layers(df: pd.DataFrame, min_cover: float = MIN_LAYER_COVER) -> dict[str, float]:
    """Layers with real values on at least ``min_cover`` of the rows (honest coverage; others are excluded from training)."""
    av = MR.availability(df[list(MR.FEATURE_NAMES)]) if len(df) else {g: 0.0 for g in MR.GROUP_FEATURES}
    return {g: v for g, v in av.items() if v >= min_cover}


def model_features(layers: Iterable[str]) -> tuple[str, ...]:
    mr = [n for g in layers for n in MR.GROUP_FEATURES[g]]
    sg = [f"{n}_x_dir" for n in MR_SIGNED if n in mr]
    return tuple(BASE_FEATURES) + tuple(mr) + tuple(sg)


def walk_forward(data: pd.DataFrame, features: Sequence[str], groups: list[tuple[str, str]] | None = None, n_folds: int = 5) -> dict[str, Any]:
    """Purged walk-forward run through the existing trainer. The returned dict has no DataFrames (JSON friendly)."""
    res = TR.run_training(data, groups=groups, n_folds=n_folds, features=tuple(features))
    for g in res["groups"].values():
        g.pop("_oos", None)
    return res


def decide_actions(mm: TR.MetaModel, X: pd.DataFrame) -> pd.DataFrame:
    """BUY / SELL / HOLD for setup rows. HOLD is the default; no size or order is produced."""
    if len(X) == 0:
        return pd.DataFrame(columns=["action", "p_win_after_cost", "ev_r", "conformal_take", "take"])
    d = mm.decide(X)
    take = np.asarray(d["take"], bool)
    long_ = X["dir_long"].to_numpy(float) > 0
    act = np.where(take & long_, "BUY", np.where(take & ~long_, "SELL", "HOLD"))
    return pd.DataFrame({"action": act, "p_win_after_cost": np.asarray(d["p"], float), "ev_r": np.asarray(d["ev_r"], float),
                         "conformal_take": mm.conformal.take_mask(np.asarray(d["p"], float)), "take": take}, index=X.index)


def rank_opportunities(frame: pd.DataFrame) -> pd.DataFrame:
    """BUY/SELL first, by after-cost expected R; HOLD last. Ordering only, not a recommendation."""
    f = frame.copy()
    f["_a"] = (f["action"] != "HOLD").astype(int)
    return f.sort_values(["_a", "ev_r"], ascending=[False, False]).drop(columns="_a")


def status_from_gates(gates: list[dict[str, Any]]) -> str:
    return "eligible" if REG.is_eligible(gates) else "not_eligible"


def save_model(root: Path, key: str, mm: TR.MetaModel, manifest: dict[str, Any]) -> Path:
    d = Path(root) / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.pkl").write_bytes(pickle.dumps(mm))
    man = dict(manifest) | {"schema": SCHEMA, "label": LABEL, "execution_permission": EXECUTION_PERMISSION, "mode": MODE,
                            "features": list(mm.features), "saved_at": int(time.time())}
    (d / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return d


def load_model(root: Path, key: str) -> tuple[TR.MetaModel, dict[str, Any]] | None:
    d = Path(root) / key
    if not (d / "model.pkl").exists() or not (d / "manifest.json").exists():
        return None
    return pickle.loads((d / "model.pkl").read_bytes()), json.loads((d / "manifest.json").read_text())
