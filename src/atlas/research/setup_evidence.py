"""Walk-forward, purged evaluation of price-action detectors on cached real bars (research only).

Labels are triple-barrier outcomes from the conservative replay (``price_action.replay``):
upper/lower barrier = proposed target/stop, vertical barrier = ``max_hold_bars``; y = 1 only if the
target is hit first (timeouts are 0). Per detector, a one-feature pre-registered score is Platt-calibrated
on each expanding training window only (trades whose exit is at/after the test start are purged, plus an
embargo) and scored on the next unseen fold. The baseline is the training-window base rate.
Nothing here trades; outputs are evidence for the registry gates."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.replay import ReplayConfig, replay, trade_cost
from atlas.features.price_action.sessions import US_EQUITY_RTH, SessionSpec
from atlas.models.predict import fit_platt
from atlas.models.quant.metrics import deflated_sharpe
from atlas.models.quant.validation import pbo_cscv

UTC_DAY = SessionSpec("utc_day", "UTC", datetime.min.time(), datetime.min.time(), weekdays=(0, 1, 2, 3, 4, 5, 6))
COSTS_BPS = {"equity": 4.0, "crypto": 24.0}   # round trip: equity 1bp spread+1bp slip per side; crypto 10bp taker+2bp slip per side
COST_PER_SHARE = {"equity": 0.01, "crypto": 0.0}
EPS = 1e-6


def load_bars(path: Path) -> tuple[list[Bar], dict[str, Any]]:
    d = json.loads(path.read_text())
    dur = 3600 if d["interval"] == "1h" else 86400
    fetched = datetime.fromisoformat(d["fetched_at"]).timestamp()
    bars, last = [], None
    for t, o, h, l, c, v in d["bars"]:
        if t + dur > fetched or (last is not None and t <= last):   # drop in-progress / duplicate bars
            continue
        bars.append(Bar(int(t), dur, float(o), float(h), float(l), float(c), float(v or 0)))
        last = t
    meta = {k: d[k] for k in ("source", "url", "symbol", "interval", "fetched_at")}
    meta |= {"n_bars": len(bars), "first_bar_utc": _iso(bars[0].start), "last_bar_utc": _iso(bars[-1].start)}
    return bars, meta


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def reliability(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for i in range(bins):
        m = (p >= i / bins) & ((p < (i + 1) / bins) if i < bins - 1 else (p <= 1))
        if m.any():
            out.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}", "n": int(m.sum()),
                        "mean_p": round(float(p[m].mean()), 4), "hit_rate": round(float(y[m].mean()), 4)})
    return out


@dataclass
class Resolved:
    detected_at: int
    exit_at: int
    score: float
    y: int
    r: float
    g_r: float        # target distance in R (gross)
    c_r: float        # cost in R


def resolved_trades(trades, cfg: ReplayConfig) -> dict[str, list[Resolved]]:
    by: dict[str, list[Resolved]] = {}
    for t in trades:
        if t.outcome not in ("target", "stop", "timeout") or t.r_multiple is None:
            continue
        risk = abs(t.entry - t.stop)
        s = t.features.get("score")
        by.setdefault(t.detector, []).append(Resolved(
            t.detected_at, t.exit_at, float(s) if s is not None and math.isfinite(s) else 0.0, int(t.outcome == "target"),
            float(t.r_multiple), abs(t.target - t.entry) / risk, trade_cost(t, cfg) / risk))
    return by


def walk_forward(rs: list[Resolved], n_folds: int = 5, embargo: int = 86400, min_train: int = 50) -> dict[str, Any]:
    rs = sorted(rs, key=lambda r: r.detected_at)
    n = len(rs)
    edges = [int(n * k / (n_folds + 1)) for k in range(1, n_folds + 2)]
    oos: list[dict] = []
    folds = []
    for k in range(n_folds):
        lo, hi = edges[k], edges[k + 1]
        test = rs[lo:hi]
        if not test:
            continue
        t0 = test[0].detected_at
        train = [r for r in rs[:lo] if r.exit_at < t0 - embargo]          # purge + embargo
        if len(train) < min_train:
            folds.append({"fold": k, "skipped": "insufficient_train", "n_train": len(train)})
            continue
        cal = fit_platt([r.score for r in train], [r.y for r in train], fitted_through=train[-1].exit_at)
        base = float(np.mean([r.y for r in train]))
        for r in test:
            p = 1.0 / (1.0 + math.exp(cal.slope_a * r.score + cal.intercept_b))
            oos.append({"t": r.detected_at, "p": p, "base": base, "y": r.y, "r": r.r, "g": r.g_r, "c": r.c_r})
        folds.append({"fold": k, "n_train": len(train), "n_test": len(test), "test_from": _iso(t0),
                      "test_to": _iso(test[-1].detected_at), "platt_A": round(cal.slope_a, 4), "platt_B": round(cal.intercept_b, 4),
                      "train_base_rate": round(base, 4)})
    if not oos:
        return {"n_resolved": n, "n_oos": 0, "folds": folds}
    p = np.array([o["p"] for o in oos]); b = np.array([o["base"] for o in oos]); y = np.array([o["y"] for o in oos])
    bs, bb = float(((p - y) ** 2).mean()), float(((b - y) ** 2).mean())
    # EV-after-cost gate in R units: EV = p*G - (1-p)*1 - C ; take trade only when EV > 0
    take = np.array([o["p"] * o["g"] - (1 - o["p"]) - o["c"] > 0 for o in oos])
    r_all = np.array([o["r"] for o in oos])
    return {"n_resolved": n, "n_oos": len(oos), "folds": folds, "oos_base_rate": round(float(y.mean()), 4),
            "brier_model": round(bs, 5), "brier_baseline": round(bb, 5), "brier_skill": round(1 - bs / bb, 5) if bb > 0 else None,
            "logloss_model": round(_logloss(p, y), 5), "logloss_baseline": round(_logloss(b, y), 5),
            "reliability": reliability(p, y), "mean_r_all_after_cost": round(float(r_all.mean()), 4),
            "n_taken_ev_gate": int(take.sum()),
            "mean_r_ev_gate_after_cost": round(float(r_all[take].mean()), 4) if take.any() else None,
            "_series": {"t": [o["t"] for o in oos], "r_all": r_all.tolist(), "r_gate": np.where(take, r_all, 0.0).tolist()}}


def run(cache: Path, max_hold: dict[str, int] | None = None) -> dict[str, Any]:
    max_hold = max_hold or {"1h": 8, "1d": 10}
    datasets, configs = [], []
    for f in sorted(cache.glob("*.json")):
        bars, meta = load_bars(f)
        asset = "crypto" if meta["source"].startswith("binance") else "equity"
        session = (UTC_DAY if asset == "crypto" else US_EQUITY_RTH) if meta["interval"] == "1h" else None
        cfg = ReplayConfig(entry_window=3, max_hold_bars=max_hold[meta["interval"]], cost_per_unit=COST_PER_SHARE[asset],
                           cost_bps=COSTS_BPS[asset], zone_rule="zone_entry_v1")
        res = replay(meta["symbol"], bars[0].duration, bars, engine_cfg=EngineConfig(session=session), cfg=cfg,
                     data_label=f"real:{meta['source']}")
        meta |= {"asset_class": asset, "session": session.name if session else None, "replay_summary": res.summary}
        datasets.append(meta)
        for det, rs in resolved_trades(res.trades, cfg).items():
            wf = walk_forward(rs)
            configs.append({"instrument": meta["symbol"], "interval": meta["interval"], "detector": det, **wf})
    # trial set: every (instrument, interval, detector) x {take_all, ev_gate} tried here
    trials = []
    for c in configs:
        s = c.get("_series")
        if s:
            for variant in ("r_all", "r_gate"):
                r = np.asarray(s[variant])
                trials.append((c, variant, float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0))
    trial_srs = [t[2] for t in trials]
    for c, variant, _ in trials:
        d = deflated_sharpe(c["_series"][variant], trial_srs)
        c.setdefault("dsr", {})[variant] = {k: round(v, 5) if isinstance(v, float) else v for k, v in d.items()}
    pbo = {}
    for interval, bucket in (("1h", 7 * 86400), ("1d", 30 * 86400)):
        cols = [(c, v) for c, v, _ in trials if c["interval"] == interval]
        if len(cols) < 2:
            continue
        ts = [t for c, v in cols for t in c["_series"]["t"]]
        t0, t1 = min(ts), max(ts)
        T = (t1 - t0) // bucket + 1
        M = np.zeros((T, len(cols)))
        for j, (c, v) in enumerate(cols):
            for t, r in zip(c["_series"]["t"], c["_series"][v]):
                M[(t - t0) // bucket, j] += r
        pbo[interval] = {**pbo_cscv(M, n_blocks=16), "bucket_seconds": bucket, "n_buckets": int(T),
                         "configs": [f"{c['instrument']}:{c['detector']}:{v}" for c, v in cols]}
    for c in configs:
        c.pop("_series", None)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "n_trials": len(trials), "datasets": datasets,
            "configs": configs, "pbo": pbo,
            "method": {"labels": "triple_barrier via conservative_ohlc_v1 replay (target/stop/max_hold_bars)",
                       "cv": "expanding walk-forward, 5 test folds, purged by exit time, 1-day embargo",
                       "calibration": "Platt per detector per instrument, fitted on training window only",
                       "baseline": "training-window base rate", "costs_bps_round_trip": COSTS_BPS,
                       "cost_per_share": COST_PER_SHARE, "max_hold_bars": max_hold,
                       "scores": {"orb_retest": "breakout_strength_atr", "dual_band_breakout": "breakout_strength_atr",
                                  "wick_reversal": "rejection wick ratio"}}}


def registry_gates(c: dict, pbo: dict, min_dsr: float = 0.95, max_pbo: float = 0.5, min_oos: int = 200) -> list[dict]:
    """Offline subset of ``models.quant.registry`` gates (DSR, PBO) plus calibration-quality gates.
    Shadow-week gates cannot be satisfied offline and are listed as not met."""
    d = (c.get("dsr") or {}).get("r_gate", {}).get("dsr", 0.0)
    p = (pbo.get(c["interval"]) or {}).get("pbo")
    return [
        {"gate": "n_oos", "passed": c.get("n_oos", 0) >= min_oos, "value": c.get("n_oos", 0), "threshold": f">= {min_oos}"},
        {"gate": "brier_beats_base_rate", "passed": c.get("brier_skill") is not None and c["brier_skill"] > 0,
         "value": c.get("brier_skill"), "threshold": "> 0"},
        {"gate": "logloss_beats_base_rate", "passed": c.get("n_oos", 0) > 0 and c["logloss_model"] < c["logloss_baseline"],
         "value": [c.get("logloss_model"), c.get("logloss_baseline")], "threshold": "model < baseline"},
        {"gate": "deflated_sharpe", "passed": d > min_dsr, "value": d, "threshold": f"> {min_dsr}"},
        {"gate": "pbo", "passed": p is not None and p < max_pbo, "value": p, "threshold": f"< {max_pbo}"},
        {"gate": "shadow_weeks", "passed": False, "value": 0, "threshold": "registry min_shadow_weeks (not satisfiable offline)"},
    ]
