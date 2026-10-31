"""Live 15m signal service (milestone e): one tick scores the CURRENT decision bar, logs it, and exposes read-only payloads.

Paper / shadow only. Every record and payload carries ``execution_permission: none`` and the label
"Predicted signal, not advice". Nothing here sizes, places or recommends an order.

A tick, for each instrument of the pre-declared universe:
  1. reads REAL confirmed 15m / 1h bars of ONE provider (never nowcast, gap-fill or any predicted value),
  2. checks freshness: a last real bar that is more than two bars old makes the answer HOLD (``stale_data``; stocks are T+1),
  3. takes the newest filled, still-open setup detected within the entry window, using the model own hold; none is HOLD (``no_fresh_setup``),
  4. attaches the multires features at T (end <= T only) and scores with the persisted shadow model,
  5. appends one JSON line per (instrument, T, model) to ``signals.jsonl`` (never rewritten) and refreshes ``latest.json``.
``resolve_signals`` later joins every logged setup to its REAL barrier outcome (``build_rows`` on bars that have since arrived),
so the shadow Brier and the shadow weeks are measured, not assumed. Gates are ``train.GATES`` unchanged.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from atlas.ai.ml import multires as MR
from atlas.ai.ml import signal15 as S
from atlas.ai.ml.dataset import build_rows

SCHEMA = "atlas-signal15-live-v1"
BAR = 900
MAX_AGE_BARS = 2                     # last real bar older than this many bars -> stale -> HOLD
LOOKBACK_S = 12 * 86400              # 1150 bars of 15m: enough for the detectors (>= 200) and the 24 h / 1 h layers
UNIVERSE: dict[str, tuple[str, tuple[str, ...]]] = {
    "crypto": ("coinbase", ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")),
    "equity": ("polygon", ("SPY", "QQQ", "AAPL", "NVDA", "MSFT")),
}
MODEL_KEYS = {"crypto": "crypto_h96", "equity": "equity_h26"}      # pre-declared in milestone d, not picked on test results
HOLD_BARS = {"crypto": 96, "equity": 26}


def root() -> Path:
    return Path(os.environ.get("ATLAS_SIGNAL15_ROOT", S.ROOT))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str, sort_keys=True) + "\n")


def _atomic_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _base(instrument: str, asset_class: str, provider: str, key: str, manifest: dict[str, Any] | None, now: int) -> dict[str, Any]:
    return {"schema": SCHEMA, "label": S.LABEL, "predicted": True, "advice": False, "execution_permission": S.EXECUTION_PERMISSION,
            "mode": S.MODE, "instrument": instrument, "asset_class": asset_class, "provider": provider, "model_key": key,
            "model_status": (manifest or {}).get("status", "no_model"), "hold_bars": HOLD_BARS[asset_class], "issued_at": int(now)}


def _hold(row: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return row | {"action": "HOLD", "reasons": [reason], "p_win_after_cost": None, "ev_r": None, "conformal_take": None,
                  "decision_t": extra.pop("decision_t", None), "setup": None, **extra}


def _fresh_open_setup(sd, asset_class: str, last_end: int) -> dict[str, Any] | None:
    """Newest FILLED, still-open setup (barrier of the model own hold) that was detected within the entry window.

    Everything used is already in the real bars at last_end (detection, fill, no outcome yet). A setup older than the
    entry window is not a new decision and gives HOLD. The model own hold is used, not the default hold of latest_open_setup."""
    df = build_rows(sd, include_open=True, hold_bars=HOLD_BARS[asset_class])
    if df is None or len(df) == 0 or "y" not in df.columns:
        return None
    op = df.loc[(df["y"] < 0) & (df["t"] >= last_end - S.MIN_ENTRY_WINDOW * BAR) & (df["t"] <= last_end)]
    if len(op) == 0:
        return None
    return op.sort_values(["t", "candidate_id"]).iloc[-1].to_dict()


def score_instrument(store, instrument: str, asset_class: str, provider: str, mm, manifest: dict[str, Any] | None, now: int) -> dict[str, Any]:
    key = MODEL_KEYS[asset_class]
    base = _base(instrument, asset_class, provider, key, manifest, now)
    if mm is None:
        return _hold(base, "no_model")
    sd = S.load_sd(store, instrument, "15m", provider, asset_class, now - LOOKBACK_S, now)
    if not sd.bars:
        return _hold(base, "no_real_bars")
    last_end = int(sd.bars[-1].start + BAR)
    age = int(now) - last_end
    fresh = {"last_real_bar_end": last_end, "age_s": age, "max_age_s": MAX_AGE_BARS * BAR}
    if age > MAX_AGE_BARS * BAR:
        return _hold(base, f"stale_data: last real 15m bar ended {age // 60} min ago (provider lag or T+1 feed)", decision_t=last_end, data=fresh)
    row = _fresh_open_setup(sd, asset_class, last_end)
    if row is None:
        return _hold(base, "no_fresh_setup", decision_t=last_end, data=fresh)
    T = int(row["t"])                                   # detection bar end (features are causal at T); the entry fill is already in the real bars
    inp = MR.load_inputs(store, instrument, provider=provider, start=now - LOOKBACK_S, end=now, intervals=("15m", "1h"))
    f = MR.features_at(inp, T)
    d = 1.0 if float(row["dir_long"]) > 0 else -1.0
    rec = dict(row) | f | {f"{n}_x_dir": f.get(n, float("nan")) * d for n in S.MR_SIGNED}
    X = pd.DataFrame([{c: rec.get(c, float("nan")) for c in mm.features} | {"dir_long": row["dir_long"]}])
    got = S.decide_actions(mm, X).iloc[0]
    reasons = [] if got["action"] != "HOLD" else ["model_does_not_take_this_setup"]
    if base["model_status"] != "eligible":
        reasons.append("model_not_eligible: shadow only (gates incl. 4 shadow weeks not passed)")
    setup = {"detector": row["detector"], "candidate_id": row["candidate_id"], "detected_t": T, "age_bars": (last_end - T) // BAR, "direction": "long" if d > 0 else "short",
             "entry": _num(row["entry"]), "stop": _num(row["stop"]), "target": _num(row["target"]), "risk_bps": _num(row["risk_bps"]),
             "cost_bps": _num(row["cost_r"] * row["risk_bps"])}
    return base | {"action": str(got["action"]), "reasons": reasons, "decision_t": last_end, "data": fresh, "setup": setup,
                   "p_win_after_cost": _num(got["p_win_after_cost"]), "ev_r": _num(got["ev_r"]), "conformal_take": bool(got["conformal_take"]),
                   "uncertainty": {"kind": "split_conformal", "alpha": S.TR.ALPHA, "note": "p is calibrated on past real outcomes; a set {1} is needed to take"},
                   "layers_with_real_values": MR.availability(pd.DataFrame([f]))}


def _key(r: dict[str, Any]) -> tuple:
    """One row per (instrument, model, setup) or per decision bar for HOLD; a setup seen again on a later tick is not logged twice."""
    s = r.get("setup")
    return (r.get("instrument"), r.get("model_key"), s["candidate_id"] if s else r.get("decision_t"))


def tick_once(store, now: int | None = None, rt: Path | None = None, classes: tuple[str, ...] = ("crypto", "equity")) -> dict[str, Any]:
    """Score every instrument once and append new (instrument, T, model) rows. Returns the tick summary."""
    now = int(now if now is not None else time.time())
    rt = Path(rt) if rt else root()
    log = rt / "signals.jsonl"
    seen = {_key(r) for r in _read_jsonl(log) if r.get("decision_t") is not None}
    out, new = [], []
    for cls in classes:
        provider, names = UNIVERSE[cls]
        loaded = S.load_model(rt / "models", MODEL_KEYS[cls])
        mm, man = (loaded if loaded else (None, None))
        for inst in names:
            try:
                r = score_instrument(store, inst, cls, provider, mm, man, now)
            except Exception as exc:                                    # one bad instrument must not stop the tick
                r = _hold(_base(inst, cls, provider, MODEL_KEYS[cls], man, now), f"error: {type(exc).__name__}: {exc}")
            out.append(r)
            k = _key(r)
            if r.get("decision_t") is not None and k not in seen:     # only real decision bars are logged, once
                new.append(r)
                seen.add(k)
    _append_jsonl(log, new)
    n_act = sum(r["action"] != "HOLD" for r in out)
    summary = {"schema": SCHEMA, "label": S.LABEL, "execution_permission": S.EXECUTION_PERMISSION, "mode": S.MODE, "issued_at": now,
               "n_instruments": len(out), "n_actionable": n_act, "n_logged_new": len(new), "signals": out}
    _atomic_json(rt / "latest.json", summary)
    return summary


def resolve_signals(store, now: int | None = None, rt: Path | None = None) -> int:
    """Join logged setups to their REAL outcome once the vertical barrier has passed. Returns the number newly resolved."""
    now = int(now if now is not None else time.time())
    rt = Path(rt) if rt else root()
    done = {(r["instrument"], r["decision_t"], r["candidate_id"], r["model_key"]) for r in _read_jsonl(rt / "resolved.jsonl")}
    todo: dict[tuple[str, str, str], list[dict]] = {}
    for r in _read_jsonl(rt / "signals.jsonl"):
        s = r.get("setup")
        if not s or (r["instrument"], r["decision_t"], s["candidate_id"], r["model_key"]) in done:
            continue
        if now < int(s["detected_t"]) + (S.MIN_ENTRY_WINDOW + int(r["hold_bars"]) + 1) * BAR:
            continue
        todo.setdefault((r["instrument"], r["asset_class"], r["provider"]), []).append(r)
    out = []
    for (inst, cls, provider), rows in todo.items():
        t0 = min(int(r["setup"]["detected_t"]) for r in rows) - LOOKBACK_S
        sd = S.load_sd(store, inst, "15m", provider, cls, t0, now)
        for hb in {int(r["hold_bars"]) for r in rows}:
            df = build_rows(sd, include_open=False, hold_bars=hb)
            if df is None or len(df) == 0:
                continue
            idx = {(int(t), c): i for i, (t, c) in enumerate(zip(df["t"], df["candidate_id"]))}
            for r in rows:
                if int(r["hold_bars"]) != hb:
                    continue
                i = idx.get((int(r["setup"]["detected_t"]), r["setup"]["candidate_id"]))
                if i is None:
                    continue                                              # unfilled, or the real bars are not complete yet
                x = df.iloc[i]
                out.append({"instrument": inst, "decision_t": int(r["decision_t"]), "candidate_id": r["setup"]["candidate_id"], "model_key": r["model_key"],
                            "action": r["action"], "p_win_after_cost": r["p_win_after_cost"], "ev_r": r["ev_r"], "y": int(x["y"]), "r": _num(x["r"]),
                            "outcome": str(x["outcome"]), "exit_at": int(x["exit_at"]), "resolved_at": now})
    _append_jsonl(rt / "resolved.jsonl", out)
    return len(out)


def shadow_summary(rt: Path | None = None) -> dict[str, Any]:
    rt = Path(rt) if rt else root()
    logged = [r for r in _read_jsonl(rt / "signals.jsonl")]
    res = _read_jsonl(rt / "resolved.jsonl")
    setups = [r for r in logged if r.get("setup")]
    out: dict[str, Any] = {"n_logged": len(logged), "n_setups": len(setups), "n_resolved": len(res),
                           "n_buy": sum(r["action"] == "BUY" for r in logged), "n_sell": sum(r["action"] == "SELL" for r in logged)}
    ts = [int(r["decision_t"]) for r in logged if r.get("decision_t") is not None]
    weeks = (max(ts) - min(ts)) / (7 * 86400) if len(ts) > 1 else 0.0
    out["shadow_weeks"] = round(weeks, 3)
    out["gates"] = dict(S.GATES)
    out["gate_shadow_weeks_met"] = weeks >= S.GATES["min_shadow_weeks"]
    out["live_gate_pass"] = False if not res else None            # promotion is decided by train.gates on a retrain, never by this summary
    if res:
        p = np.array([r["p_win_after_cost"] for r in res if r.get("p_win_after_cost") is not None], float)
        y = np.array([r["y"] for r in res if r.get("p_win_after_cost") is not None], float)
        if len(p):
            base = float(y.mean())
            out["brier"] = float(np.mean((p - y) ** 2))
            out["brier_baseline"] = float(np.mean((base - y) ** 2))
            out["brier_skill"] = 1.0 - out["brier"] / out["brier_baseline"] if out["brier_baseline"] > 0 else None
        taken = [r for r in res if r["action"] != "HOLD" and r.get("r") is not None]
        out["n_taken_resolved"] = len(taken)
        out["mean_r_taken"] = float(np.mean([r["r"] for r in taken])) if taken else None
    return out


def _models(rt: Path) -> list[dict[str, Any]]:
    out = []
    for cls, key in MODEL_KEYS.items():
        m = S.load_model(rt / "models", key)
        if m is None:
            out.append({"model_key": key, "asset_class": cls, "status": "no_model"})
            continue
        man = m[1]
        out.append({"model_key": key, "asset_class": cls, "status": man.get("status"), "hold_bars": man.get("hold_bars"), "provider": man.get("provider"),
                    "layers": man.get("layers"), "n_rows": man.get("n_rows"), "trained_through": man.get("trained_through"),
                    "shadow_weeks": man.get("shadow_weeks"), "failed_gates": [g["gate"] for g in man.get("gates", []) if not g.get("passed")]})
    return out


def signals_payload(rt: Path | None = None, limit: int = 50) -> dict[str, Any]:
    from atlas.ai.ml.contract_v1 import _envelope
    rt = Path(rt) if rt else root()
    latest = {}
    f = rt / "latest.json"
    if f.exists():
        try:
            latest = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            latest = {}
    hb = {}
    h = rt / "heartbeat.json"
    if h.exists():
        try:
            hb = json.loads(h.read_text(encoding="utf-8"))
        except ValueError:
            hb = {}
    if hb.get("last_tick_at") is not None and hb.get("state") == "running" and int(time.time()) - int(hb["last_tick_at"]) > 2 * BAR + 120:
        hb = hb | {"state": "stale", "note": "no tick for over two clock intervals; the process may have stopped (check the PID)"}
    recent = sorted(_read_jsonl(rt / "signals.jsonl"), key=lambda r: -int(r.get("decision_t") or 0))[: max(1, min(int(limit), 500))]
    return _envelope(label=S.LABEL, predicted=True, advice=False, mode=S.MODE, signal_schema=S.SCHEMA, clock_seconds=BAR,
                     gates=dict(S.GATES), models=_models(rt), latest=latest.get("signals", []), latest_at=latest.get("issued_at"),
                     tick=hb or {"state": "never_run"}, shadow=shadow_summary(rt), recent=recent,
                     note="Predicted from real closed bars only. BUY/SELL is a model flag for paper tracking, not an instruction. HOLD is the default.")


def nowcast_payload(ledger_path: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Predicted stock / FX windows from the nowcast ledger with scores against real bars (read-only)."""
    from atlas.ai.ml import nowcast_xgb as N
    from atlas.ai.ml.contract_v1 import _envelope
    path = ledger_path or N.default_ledger_path()
    rows: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    if path != ":memory:" and Path(path).exists():
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            cur = c.execute("SELECT i.group_name,i.target,i.window_end,i.model_id,i.made_at,i.anchor,i.q10,i.q50,i.q90,i.lo,i.hi,i.status,"
                            "s.actual,s.covered FROM issued i LEFT JOIN scored s USING(group_name,target,window_end,model_id) "
                            "ORDER BY i.window_end DESC LIMIT ?", (max(1, min(int(limit), 500)),))
            for g, t, we, mid, made, anchor, q10, q50, q90, lo, hi, st, act, cov in cur:
                rows.append({"predicted": True, "label": N.LABEL, "group": g, "target": t, "window_end": we, "model_id": mid, "made_at": made,
                             "anchor_close": anchor, "est_return": q50, "interval80_return": [lo, hi], "q10": q10, "q90": q90, "status": st,
                             "actual_return": act, "covered": None if cov is None else bool(cov)})
            gs = [r[0] for r in c.execute("SELECT DISTINCT group_name FROM issued")]
        finally:
            c.close()
        led = N.Ledger(path)
        try:
            groups = [led.summary(g) for g in gs]
        finally:
            led.close()
    bundles = []
    for g in N.GROUPS:
        b = N.load_bundle(g)
        bundles.append({"group": g, "model_id": (b or {}).get("model_id"), "gate_pass": (b or {}).get("gate_pass"), "reasons": (b or {}).get("reasons", [])} if b
                       else {"group": g, "model_id": None, "gate_pass": False, "reasons": ["no trained model"]})
    return _envelope(label=N.LABEL, predicted=True, advice=False, bundles=bundles, groups=groups, recent=rows,
                     note="Predicted values stored apart from real bars; never used as labels. Each is scored against the real bar when it arrives.")


def gapfill_payload(path: str | None = None) -> dict[str, Any]:
    """Calibration of the missing-second fill for crypto 1s (predicted, uses a later real bar, never a feature or label)."""
    from atlas.ai.ml import gapfill1s as G
    from atlas.ai.ml.contract_v1 import _envelope
    p = path or G.default_path()
    cal: dict[str, Any] = {}
    n_pred = 0
    if p != ":memory:" and Path(p).exists():
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        try:
            for v, b, n, q, mb, mc in c.execute("SELECT venue,bucket,n,q80_abs,mae_bridge,mae_carry FROM calib ORDER BY venue,bucket"):
                cal.setdefault(v, {})[b] = {"n": n, "q80_abs": q, "mae_bridge": mb, "mae_carry": mc}
            n_pred = int(c.execute("SELECT COUNT(*) FROM pred_1s").fetchone()[0])
        finally:
            c.close()
    return _envelope(label=G.LABEL, predicted=True, uses_future=True, method=G.METHOD, max_gap_s=G.MAX_GAP, n_predicted_seconds=n_pred, calibration=cal,
                     note="Predicted seconds fill gaps between two real bars. They are not market data, not features and not labels.")

