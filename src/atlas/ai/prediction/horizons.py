"""evo-17 multi-horizon research forecaster: an ensemble of quantile models per (pool, horizon), scored live against real bars.

Horizons 1m / 5m / 15m / 60m / 1d, each a ONE-bar-ahead log-return forecast on the matching bar interval (60m uses 1h bars).
Members: LightGBM quantile boosters, XGBoost quantile boosters (when installed), Prophet (1d only; used only when installed and
never faster than its budget) and a no-change baseline (zero median, vol-scaled normal band). Every member gets a split-conformal
(CQR) 80% band from a held-out calibration block. Features are ``build_features`` (all layer columns; layers whose inputs are
not supplied are NaN, never invented). Members are weighted per (pool, horizon) by their rolling LIVE pinball loss.

Research only: execution_permission is always "none". Forecasts live in their own sqlite ledger, never in the bar store and never
as labels. Nothing here places or sizes an order. No profitability claim.
"""
from __future__ import annotations

import json
import math
import os
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

TAUS = (0.1, 0.5, 0.9)
HORIZONS: dict[str, tuple[str, int]] = {"1m": ("1m", 60), "5m": ("5m", 300), "15m": ("15m", 900), "60m": ("1h", 3600), "1d": ("1d", 86400)}
MODELS = ("lgbm", "xgb", "prophet", "naive")
ZQ = 1.2815515655446004          # N(0,1) 90th percentile: the naive member's 80% band is +-ZQ sigma before conformal calibration
MIN_BARS, MIN_ROWS, WARMUP = 400, 600, 300
FEATURE_H = {"1m": 60, "5m": 48, "15m": 26, "1h": 24, "1d": 10}   # bars for the horizon-aware layer columns (vol cone, conformal band), ~ one session
LEDGER_DEFAULT = "var/ml/predictions/horizons.sqlite"
ROOT_DEFAULT = "var/ml/horizons"
GATE_MIN_N, GATE_MARGIN = 100, 0.99     # the ensemble moves the dashed line only after >= 100 live scores with pinball <= 0.99 x the no-change baseline
PRIOR_NAIVE = 0.5
EXEC = "none"
LABEL = "research / below gate"

_PROPHET_REASON = "prophet is not installed on this host (adds a Stan toolchain); member disabled, weight 0"


def root_path(root=None) -> Path:
    return Path(root or os.environ.get("ATLAS_ML_HORIZONS", ROOT_DEFAULT))


def available_models() -> dict[str, dict[str, Any]]:
    """Which members can run on this host, with the reason when not."""
    out: dict[str, dict[str, Any]] = {"naive": {"available": True}}
    for name, mod in (("lgbm", "lightgbm"), ("xgb", "xgboost")):
        try:
            __import__(mod)
            out[name] = {"available": True}
        except Exception:
            out[name] = {"available": False, "reason": f"{mod} is not installed"}
    try:
        __import__("prophet")
        out["prophet"] = {"available": False, "reason": "prophet is installed but its adapter is not enabled in this build (untested); weight 0"}
    except Exception:
        out["prophet"] = {"available": False, "reason": _PROPHET_REASON}
    return out


# ----------------------------------------------------------------------------- features / dataset
def _ctx(symbol: str, interval: str, pool: str, ref_loader: Callable | None):
    from atlas.ai.ml.directional import context27 as C27, pipeline as P
    from atlas.ai.ml.directional.layers25 import CORR_ROLES
    refs: dict = {}
    corr: dict = {}
    if ref_loader is None:
        return refs, corr
    for r in P.REFS.get(pool, ()):
        if r != symbol:
            try:
                rb = list(ref_loader(r, interval))
                if rb:
                    refs[r] = (np.array([x.end for x in rb]), np.array([x.close for x in rb]))
            except Exception:
                pass
    for cands in CORR_ROLES.values():
        for r in cands:
            if r != symbol and r != "USD_PROXY":
                try:
                    rb = list(ref_loader(r, interval))
                    if len(rb) >= 300:
                        corr[r] = (np.array([x.end for x in rb]), np.array([x.close for x in rb]))
                except Exception:
                    pass
    try:
        px = C27.usd_proxy_series(lambda s: ref_loader(s, interval))
        if px is not None:
            corr[C27.USD_PROXY] = px
    except Exception:
        pass
    return refs, corr


def feature_frame(bars: Sequence, interval: str, pool: str, symbol: str, ref_loader: Callable | None = None,
                  events: Sequence[float] | None = None, extra: Mapping | None = None) -> pd.DataFrame:
    from atlas.ai.ml.directional import pipeline as P
    from atlas.ai.ml.directional.features import build_features
    refs, corr = _ctx(symbol, interval, pool, ref_loader)
    return build_features(list(bars), interval, P.family_of(pool), symbol, pool == "crypto", refs, FEATURE_H.get(interval, 24), P.cost_bps(pool),
                          corr, events, None, dict(extra) if extra else None)


def sigma_series(close: np.ndarray, span: int = 100) -> np.ndarray:
    lr = pd.Series(np.log(np.asarray(close, float))).diff()
    return lr.ewm(span=span, min_periods=20, adjust=False).std().to_numpy()


def make_xy(bars: Sequence, interval: str, pool: str, symbol: str, ref_loader=None, events=None, extra=None) -> pd.DataFrame | None:
    """One row per bar i: features (bars <= i), sigma_i, y = log(close_{i+1}/close_i) (the label never enters a feature), t_end_i."""
    if len(bars) < MIN_BARS:
        return None
    f = feature_frame(bars, interval, pool, symbol, ref_loader, events, extra)
    c = np.array([b.close for b in bars], float)
    sig = sigma_series(c)
    y = np.full(len(c), np.nan)
    y[:-1] = np.log(c[1:] / c[:-1])
    f = f.copy()
    f["__sigma"], f["__y"], f["__t"] = sig, y, [b.end for b in bars]
    f["__inst"] = symbol
    f = f.iloc[WARMUP:]
    return f[np.isfinite(f["__sigma"]) & (f["__sigma"] > 0) & np.isfinite(f["__y"])]


# ----------------------------------------------------------------------------- members
def _sorted_q(q: np.ndarray) -> np.ndarray:
    return np.sort(q, axis=1)          # no quantile crossing


def _fit_lgbm(X, ys):
    import lightgbm as lgb
    return {t: lgb.LGBMRegressor(objective="quantile", alpha=t, n_estimators=160, learning_rate=0.05, num_leaves=15, min_child_samples=60,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=2.0, random_state=17, verbose=-1, n_jobs=2).fit(X, ys)
            for t in TAUS}


def _fit_xgb(X, ys):
    import xgboost as xgb
    return {t: xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=t, n_estimators=160, learning_rate=0.05, max_depth=4, min_child_weight=20,
                                subsample=0.8, colsample_bytree=0.7, reg_lambda=2.0, random_state=17, n_jobs=2, tree_method="hist").fit(X, ys)
            for t in TAUS}


def _pred(models: Mapping[float, Any], X) -> np.ndarray:
    return _sorted_q(np.column_stack([models[t].predict(X) for t in TAUS]))


def pinball_mean(y: np.ndarray, q: np.ndarray) -> float:
    """Mean pinball loss over the three quantile levels; ``2 x`` this is the 3-point quantile-decomposition CRPS approximation."""
    tot = 0.0
    for j, t in enumerate(TAUS):
        d = y - q[:, j]
        tot += float(np.mean(np.maximum(t * d, (t - 1) * d)))
    return tot / len(TAUS)


def cqr_qhat(y: np.ndarray, q: np.ndarray, alpha: float = 0.2) -> float:
    e = np.maximum(q[:, 0] - y, y - q[:, 2])
    n = len(e)
    k = min(n, int(math.ceil((n + 1) * (1 - alpha))))
    return float(np.sort(e)[k - 1]) if n else 0.0


def _metrics(y: np.ndarray, q: np.ndarray, qhat: float) -> dict[str, Any]:
    pb = pinball_mean(y, q)
    cov = float(np.mean((y >= q[:, 0] - qhat) & (y <= q[:, 2] + qhat)))
    nz = (q[:, 1] != 0) & (y != 0)
    hit = float(np.mean(np.sign(q[:, 1][nz]) == np.sign(y[nz]))) if nz.any() else None
    return {"pinball_bps": round(pb * 1e4, 4), "crps_q3_bps": round(2 * pb * 1e4, 4), "coverage_80": round(cov, 4), "hit_rate": None if hit is None else round(hit, 4),
            "width_bps": round(float(np.mean(q[:, 2] - q[:, 0] + 2 * qhat)) * 1e4, 3), "n": int(len(y))}


def split_slices(n: int) -> dict[str, slice]:
    """Chronological fit / cal / test blocks with a 2-row embargo before each held-out block (the label is one bar ahead)."""
    a, b = int(n * 0.6), int(n * 0.8)
    return {"fit": slice(0, a), "cal": slice(a + 2, b), "test": slice(b + 2, n)}


def resolved_label_rows(t: np.ndarray, inst: np.ndarray, block: slice, next_index: int) -> np.ndarray:
    """Positions in ``block`` whose next same-instrument bar ends strictly before ``t[next_index]``.

    The label at a row is the next bar's log return on that instrument, so it is known only when
    that bar closes. A fixed 2-row embargo is enough for one series. A pooled frame interleaves
    symbols, and the labelled bar can sit inside the next block; those rows stay out of fit and
    calibration. The test block is not purged: it is the hold-out being scored.
    """
    n = len(t)
    idx = np.arange(block.start, min(block.stop, n))
    if next_index >= n or len(idx) == 0:
        return idx
    boundary = int(t[next_index])
    nxt = np.full(n, np.iinfo(np.int64).max)
    later: dict[Any, int] = {}
    for i in range(n - 1, -1, -1):
        prev = later.get(inst[i])
        if prev is not None:
            nxt[i] = int(t[prev])
        later[inst[i]] = i
    return idx[nxt[idx] < boundary]


def train_pool(rows: pd.DataFrame, pool: str, horizon: str, root=None, instruments: Sequence[str] | None = None) -> dict[str, Any]:
    """Train + conformal-calibrate every available member on a pooled frame from ``make_xy`` (chronological 60/20/20 fit/cal/test).
    OOS metrics are on the last 20% only. Always labelled research; the live ledger decides weights, not these numbers."""
    interval = HORIZONS[horizon][0]
    if len(rows) < MIN_ROWS:
        return {"status": "insufficient_rows", "rows": int(len(rows)), "need": MIN_ROWS, "pool": pool, "horizon": horizon}
    rows = rows.sort_values("__t", kind="stable").reset_index(drop=True)
    feats = [c for c in rows.columns if not c.startswith("__")]
    n = len(rows)
    X = rows[feats].to_numpy(float)
    sig, y = rows["__sigma"].to_numpy(float), rows["__y"].to_numpy(float)
    ys = y / sig
    sl = split_slices(n)   # 2-row embargo; pooled rows are purged again by instrument below
    t = rows["__t"].to_numpy()
    inst = rows["__inst"].to_numpy()
    fit_idx = resolved_label_rows(t, inst, sl["fit"], sl["cal"].start)
    cal_idx = resolved_label_rows(t, inst, sl["cal"], sl["test"].start)
    test_idx = np.arange(sl["test"].start, sl["test"].stop)
    if len(fit_idx) == 0 or len(cal_idx) == 0 or len(test_idx) == 0:
        return {"status": "insufficient_rows", "rows": int(n), "need": MIN_ROWS, "pool": pool, "horizon": horizon,
                "reason": "label purge emptied a block"}
    avail = available_models()
    bundle: dict[str, Any] = {"features": feats, "models": {}, "qhat": {}, "sigma_span": 100}
    metrics: dict[str, Any] = {}
    fits = {"lgbm": _fit_lgbm, "xgb": _fit_xgb}
    for name, fn in fits.items():
        if not avail[name]["available"]:
            metrics[name] = {"status": "unavailable", "reason": avail[name]["reason"]}
            continue
        m = fn(X[fit_idx], ys[fit_idx])
        qc = _pred(m, X[cal_idx]) * sig[cal_idx, None]
        qh = cqr_qhat(y[cal_idx], qc)
        qt = _pred(m, X[test_idx]) * sig[test_idx, None]
        bundle["models"][name], bundle["qhat"][name] = m, qh
        metrics[name] = {"status": "ok", **_metrics(y[test_idx], qt, qh), "qhat_bps": round(qh * 1e4, 3)}
    # no-change baseline: zero median, +-ZQ sigma, conformalised on the same block
    def naive_q(s):
        return np.column_stack([-ZQ * s, np.zeros_like(s), ZQ * s])
    qh_n = cqr_qhat(y[cal_idx], naive_q(sig[cal_idx]))
    bundle["qhat"]["naive"] = qh_n
    metrics["naive"] = {"status": "ok", **_metrics(y[test_idx], naive_q(sig[test_idx]), qh_n), "qhat_bps": round(qh_n * 1e4, 3)}
    metrics["prophet"] = {"status": "unavailable", "reason": avail["prophet"]["reason"]}
    nz = rows[feats].notna().mean()
    from atlas.ai.ml.directional.layers25 import LAYER_FEATURES
    lay_cov = {k: round(float(nz.reindex(list(v)).fillna(0).mean()), 3) for k, v in LAYER_FEATURES.items()}
    man = {"pool": pool, "horizon": horizon, "interval": interval, "created_at": int(time.time()), "n_rows": int(n),
           "n_fit": int(len(fit_idx)), "n_cal": int(len(cal_idx)), "n_test": int(len(test_idx)),
           "instruments": sorted(set(instruments or rows["__inst"].unique())),
           "data_start": int(rows["__t"].iloc[0]), "data_end": int(rows["__t"].iloc[-1]),
           "test_start": int(rows["__t"].iloc[sl["test"].start]) if sl["test"].start < n else None,
           "n_features": len(feats), "layers_with_any_data": sum(1 for v in lay_cov.values() if v > 0), "layers_total": len(lay_cov), "layer_coverage": lay_cov,
           "metrics_oos": metrics, "label": LABEL, "execution_permission": EXEC, "target": "log(close[i+1]/close[i]) on this interval",
           "note": "research; chronological hold-out; no profitability claim; live ledger weights decide the ensemble"}
    d = root_path(root) / f"{pool}-{horizon}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.pkl").write_bytes(pickle.dumps(bundle))
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    _CACHE.pop(str(d), None)
    return {"status": "ok", **man}


_CACHE: dict[str, tuple[float, Any]] = {}


def load_bundle(pool: str, horizon: str, root=None) -> tuple[dict | None, dict | None]:
    d = root_path(root) / f"{pool}-{horizon}"
    mp, bp = d / "manifest.json", d / "model.pkl"
    if not mp.exists() or not bp.exists():
        return None, None
    mt = bp.stat().st_mtime
    hit = _CACHE.get(str(d))
    if hit and hit[0] == mt:
        return hit[1]
    v = (json.loads(mp.read_text()), pickle.loads(bp.read_bytes()))
    _CACHE[str(d)] = (mt, v)
    return v


def resolve_bundle(symbol: str, pool: str, horizon: str, root=None):
    """(manifest, bundle, key, transfer) like the directional resolver: own pool first, then the nearest donor pool, labelled as transfer."""
    from atlas.ai.prediction.pools import TRANSFER_DONORS
    man, b = load_bundle(pool, horizon, root)
    if man and b:
        return man, b, f"{pool}-{horizon}", (None if symbol in (man.get("instruments") or []) else
                                              {"kind": "pool_member_not_trained", "note": f"{symbol} was not in the training set of {pool}-{horizon}; applied unvalidated"})
    for donor in TRANSFER_DONORS.get(pool, ()):
        man, b = load_bundle(donor, horizon, root)
        if man and b:
            return man, b, f"{donor}-{horizon}", {"kind": "cross_pool", "note": f"no {pool}-{horizon} model; {donor}-{horizon} applied (cross-asset transfer, unvalidated on this asset)"}
    return None, None, f"{pool}-{horizon}", None


# ----------------------------------------------------------------------------- inference
def members_for(bars: Sequence, interval: str, pool: str, symbol: str, horizon: str, bundle: dict | None, ref_loader=None, events=None, extra=None) -> dict[str, dict]:
    """Per-member one-bar-ahead log-return quantiles and conformal band from the latest closed bar. Missing members are simply absent."""
    c = np.array([b.close for b in bars], float)
    sig = float(sigma_series(c)[-1])
    if not np.isfinite(sig) or sig <= 0:
        return {}
    out: dict[str, dict] = {}
    qh_n = float((bundle or {}).get("qhat", {}).get("naive", 0.0))
    qn = np.array([-ZQ * sig, 0.0, ZQ * sig])
    out["naive"] = {"q": qn.tolist(), "lo": float(qn[0] - qh_n), "hi": float(qn[2] + qh_n), "calibrated": bundle is not None}
    if bundle is not None and bundle.get("models"):
        f = feature_frame(bars, interval, pool, symbol, ref_loader, events, extra).reindex(columns=bundle["features"])
        x = f.iloc[[-1]].to_numpy(float)
        for name, models in bundle["models"].items():
            try:
                q = (_pred(models, x)[0]) * sig
            except Exception:
                continue
            qh = float(bundle["qhat"].get(name, 0.0))
            out[name] = {"q": q.tolist(), "lo": float(q[0] - qh), "hi": float(q[2] + qh), "calibrated": True}
    return out


# ----------------------------------------------------------------------------- ledger
_LOCK = threading.Lock()
_MEM: dict[str, sqlite3.Connection] = {}
DDL = """
CREATE TABLE IF NOT EXISTS hz_issued(symbol TEXT, h TEXT, base_end INTEGER, target_end INTEGER, made_at REAL, base_px REAL, pool TEXT, interval TEXT,
  transfer TEXT, members TEXT, weights TEXT, e10 REAL, e50 REAL, e90 REAL, elo REAL, ehi REAL, sigma REAL, applied INTEGER, PRIMARY KEY(symbol, h, base_end));
CREATE TABLE IF NOT EXISTS hz_scored(symbol TEXT, h TEXT, base_end INTEGER, scored_at REAL, pool TEXT, actual_ret REAL, e50 REAL, elo REAL, ehi REAL,
  hit INTEGER, covered INTEGER, pin REAL, PRIMARY KEY(symbol, h, base_end));
CREATE TABLE IF NOT EXISTS hz_member(pool TEXT, h TEXT, model TEXT, symbol TEXT, base_end INTEGER, scored_at REAL, pin REAL, covered INTEGER, hit INTEGER,
  PRIMARY KEY(model, symbol, h, base_end));
CREATE TABLE IF NOT EXISTS hz_anchor(symbol TEXT, h TEXT, made_at REAL, anchor_t INTEGER, anchor_px REAL, anchor_iv TEXT, anchor_provider TEXT, anchor_source TEXT,
  mode TEXT, target_end INTEGER, mid REAL, lo REAL, hi REAL, scale REAL, PRIMARY KEY(symbol, h));
CREATE INDEX IF NOT EXISTS ix_hzm ON hz_member(pool, h, model, scored_at);
CREATE INDEX IF NOT EXISTS ix_hzs ON hz_scored(pool, h, scored_at);
"""


def path_for(path: str | None = None) -> str:
    return path or os.environ.get("ATLAS_HORIZON_LOG") or (":memory:" if "PYTEST_CURRENT_TEST" in os.environ else LEDGER_DEFAULT)


def _conn(path: str | None) -> sqlite3.Connection:
    p = path_for(path)
    with _LOCK:
        c = _MEM.get(p)
        if c is None:
            if p != ":memory:":
                Path(p).parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(p, check_same_thread=False, timeout=30)
            c.executescript(DDL)
            _MEM[p] = c
        return c


def reset(path: str | None = None) -> None:
    with _LOCK:
        c = _MEM.pop(path_for(path), None)
    if c is not None:
        c.close()


def _pin1(y: float, q10: float, q50: float, q90: float) -> float:
    return sum(max(t * (y - q), (t - 1) * (y - q)) for t, q in zip(TAUS, (q10, q50, q90))) / 3.0


def model_scores(pool: str, h: str, path: str | None = None, window: int = 400) -> dict[str, dict[str, Any]]:
    """Rolling live scores per member (and the ensemble) for one (pool, horizon). Losses are pinball and 2x pinball (3-point CRPS), in bps of return."""
    c = _conn(path)
    out: dict[str, dict[str, Any]] = {}
    with _LOCK:
        for m in MODELS:
            rows = c.execute("SELECT pin, covered, hit FROM hz_member WHERE pool=? AND h=? AND model=? ORDER BY scored_at DESC LIMIT ?", (pool, h, m, window)).fetchall()
            out[m] = _agg(rows)
        out["ensemble"] = _agg(c.execute("SELECT pin, covered, hit FROM hz_scored WHERE pool=? AND h=? ORDER BY scored_at DESC LIMIT ?", (pool, h, window)).fetchall())
    return out


def _agg(rows) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "pinball_bps": None, "crps_q3_bps": None, "coverage_80": None, "hit_rate": None, "hit_n": 0}
    hits = [r[2] for r in rows if r[2] is not None]
    pb = sum(r[0] for r in rows) / n
    return {"n": n, "pinball_bps": round(pb * 1e4, 4), "crps_q3_bps": round(2 * pb * 1e4, 4), "coverage_80": round(sum(r[1] for r in rows) / n, 4),
            "hit_rate": round(sum(hits) / len(hits), 4) if hits else None, "hit_n": len(hits)}


def weights_for(pool: str, h: str, usable: Iterable[str], path: str | None = None, min_n: int = 30, scores: dict | None = None) -> dict[str, Any]:
    """Per-(pool, horizon) member weights from rolling live pinball: w ~ loss^-2, naive floor 0.10. Below ``min_n`` live scores per member
    the prior applies (naive 0.5, the rest share 0.5), because a member with no live record has not earned more."""
    use = [m for m in MODELS if m in set(usable)]
    sc = scores or model_scores(pool, h, path)
    mem = [m for m in use if m != "naive"]
    live = [m for m in use if (sc[m]["n"] or 0) >= min_n and sc[m]["pinball_bps"]]
    if "naive" in use and (sc["naive"]["n"] or 0) >= min_n and sc["naive"]["pinball_bps"] and live:
        inv = {m: float(sc[m]["pinball_bps"]) ** -2 for m in [*live, "naive"]}
        tot = sum(inv.values())
        w = {m: inv[m] / tot for m in inv}
        if w["naive"] < 0.10:
            scale = (1 - 0.10) / (1 - w["naive"])
            w = {m: (0.10 if m == "naive" else v * scale) for m, v in w.items()}
        for m in use:
            w.setdefault(m, 0.0)
        return {"weights": {m: round(w[m], 4) for m in use}, "basis": "live_pinball", "min_n": min_n}
    if not mem:
        return {"weights": {"naive": 1.0} if "naive" in use else {}, "basis": "naive_only", "min_n": min_n}
    w = {m: (1 - PRIOR_NAIVE) / len(mem) for m in mem}
    if "naive" in use:
        w["naive"] = PRIOR_NAIVE
    return {"weights": {m: round(v, 4) for m, v in w.items()}, "basis": "prior (live record below %d)" % min_n, "min_n": min_n}


def gate(pool: str, h: str, path: str | None = None, scores: dict | None = None) -> dict[str, Any]:
    sc = scores or model_scores(pool, h, path)
    e, nv = sc["ensemble"], sc["naive"]
    ok = bool((e["n"] or 0) >= GATE_MIN_N and e["pinball_bps"] is not None and nv["pinball_bps"] is not None and e["pinball_bps"] <= GATE_MARGIN * nv["pinball_bps"])
    return {"applied": ok, "n": e["n"], "needs_n": GATE_MIN_N, "ensemble_pinball_bps": e["pinball_bps"], "naive_pinball_bps": nv["pinball_bps"],
            "rule": f"moves the dashed line only with >= {GATE_MIN_N} live scores and pinball <= {GATE_MARGIN} x the no-change baseline"}


def combine(members: Mapping[str, dict], w: Mapping[str, float]) -> dict[str, float]:
    ws = {m: w.get(m, 0.0) for m in members}
    tot = sum(ws.values()) or 1.0
    f = lambda g: sum(ws[m] * g(members[m]) for m in members) / tot
    return {"q10": f(lambda r: r["q"][0]), "q50": f(lambda r: r["q"][1]), "q90": f(lambda r: r["q"][2]), "lo": f(lambda r: r["lo"]), "hi": f(lambda r: r["hi"])}


def issue_one(symbol: str, h: str, bars: Sequence, pool: str, now: float, path: str | None = None, root=None, ref_loader=None, events=None, extra=None) -> str:
    """Forecast the next bar for one (symbol, horizon) from its closed bars and freeze it in the ledger. Returns a status string."""
    interval, dur = HORIZONS[h][0], HORIZONS[h][1]
    if len(bars) < 120:
        return "too_few_bars"
    last = bars[-1]
    base_end = int(last.start + last.duration)
    c = _conn(path)
    with _LOCK:
        if c.execute("SELECT 1 FROM hz_issued WHERE symbol=? AND h=? AND base_end=?", (symbol, h, base_end)).fetchone():
            return "already_issued"
    man, bundle, key, transfer = resolve_bundle(symbol, pool, h, root)
    mem = members_for(bars[-1500:], interval, pool, symbol, h, bundle, ref_loader, events, extra)
    if not mem:
        return "no_sigma"
    wt = weights_for(pool, h, mem.keys(), path)
    ens = combine(mem, wt["weights"])
    g = gate(pool, h, path)
    sigma = float(sigma_series(np.array([b.close for b in bars[-1500:]]))[-1])
    row = (symbol, h, base_end, base_end + dur, now, float(last.close), pool, interval, json.dumps(transfer) if transfer else None, json.dumps(mem), json.dumps(wt),
           ens["q10"], ens["q50"], ens["q90"], ens["lo"], ens["hi"], sigma, int(g["applied"]))
    with _LOCK:
        c.execute("INSERT OR IGNORE INTO hz_issued VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        c.commit()
    return "issued" if bundle is not None else "issued_naive_only"


def score_due(real_bar: Callable[[str, str, int], float | None], now: float, path: str | None = None, limit: int = 4000) -> dict[str, int]:
    """Grade every issued forecast whose target bar has closed against the real confirmed bar. Waiting rows expire after 14 days."""
    c = _conn(path)
    with _LOCK:
        due = c.execute("SELECT symbol,h,base_end,target_end,base_px,pool,interval,members,e10,e50,e90,elo,ehi FROM hz_issued WHERE target_end<=? AND "
                        "(symbol,h,base_end) NOT IN (SELECT symbol,h,base_end FROM hz_scored) ORDER BY target_end LIMIT ?", (now, limit)).fetchall()
        exp = c.execute("DELETE FROM hz_issued WHERE target_end<? AND (symbol,h,base_end) NOT IN (SELECT symbol,h,base_end FROM hz_scored)", (now - 14 * 86400,)).rowcount
        c.commit()
    scored = waiting = 0
    sc_rows, mem_rows = [], []
    for sym, h, be, te, bpx, pool, iv, mj, e10, e50, e90, elo, ehi in due:
        try:
            actual = real_bar(sym, iv, be)
        except Exception:
            actual = None
        if actual is None or not actual > 0:
            waiting += 1
            continue
        y = math.log(actual / bpx)
        hit = (int((e50 > 0) == (y > 0)) if (e50 != 0 and y != 0) else None)
        sc_rows.append((sym, h, be, now, pool, y, e50, elo, ehi, hit, int(elo <= y <= ehi), _pin1(y, e10, e50, e90)))
        for m, r in json.loads(mj).items():
            q = r["q"]
            mh = (int((q[1] > 0) == (y > 0)) if (q[1] != 0 and y != 0) else None)
            mem_rows.append((pool, h, m, sym, be, now, _pin1(y, q[0], q[1], q[2]), int(r["lo"] <= y <= r["hi"]), mh))
        scored += 1
    if sc_rows:
        with _LOCK:
            c.executemany("INSERT OR IGNORE INTO hz_scored VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", sc_rows)
            c.executemany("INSERT OR IGNORE INTO hz_member VALUES(?,?,?,?,?,?,?,?,?)", mem_rows)
            c.commit()
    return {"scored": scored, "waiting_for_real_bar": waiting, "expired": exp}


def asset_stats(symbol: str, h: str, path: str | None = None, window: int = 200) -> dict[str, Any]:
    c = _conn(path)
    with _LOCK:
        rows = c.execute("SELECT pin, covered, hit FROM hz_scored WHERE symbol=? AND h=? ORDER BY scored_at DESC LIMIT ?", (symbol, h, window)).fetchall()
    return _agg(rows)


def latest(symbol: str, now: float | None = None, path: str | None = None, pool: str | None = None) -> dict[str, Any]:
    """Latest frozen forecast per horizon for ``symbol`` with live scores beside it. Read-only; computes nothing heavy."""
    now = float(time.time() if now is None else now)
    if pool is None:
        from atlas.ai.prediction.pools import pool_for_symbol
        pool = pool_for_symbol(symbol)
    c = _conn(path)
    av = available_models()
    out = []
    for h, (iv, dur) in HORIZONS.items():
        with _LOCK:
            r = c.execute("SELECT base_end,target_end,base_px,transfer,members,weights,e10,e50,e90,elo,ehi,sigma,applied FROM hz_issued WHERE symbol=? AND h=? "
                          "ORDER BY base_end DESC LIMIT 1", (symbol, h)).fetchone()
        anc = anchored_row(symbol, h, now, path, pool) if h in ANCHOR_H else None
        if anc is not None and (not r or now - r[1] > 10 * dur):
            out.append(anc)
            continue
        if not r:
            out.append({"h": h, "interval": iv, "status": "no_bars_at_interval", "reason": f"needs {iv} bars for {symbol}; none are stored, so no model forecast is made (nothing is invented)",
                        "execution_permission": EXEC, "label": LABEL})
            continue
        be, te, bpx, tr, mj, wj, e10, e50, e90, elo, ehi, sg, ap = r
        px = lambda v: round(bpx * math.exp(v), 6 if bpx < 10 else 4)
        sc = model_scores(pool, h, path)
        g = gate(pool, h, path, sc)
        mem = json.loads(mj)
        out.append({"h": h, "interval": iv, "status": "ok" if now - te < 3 * dur + 4 * 86400 else "stale", "base_end": be, "target_end": te, "base_px": bpx,
                    "median": px(e50), "q10": px(e10), "q90": px(e90), "lo": px(elo), "hi": px(ehi), "ret_bps": round(e50 * 1e4, 3), "band_bps": [round(elo * 1e4, 3), round(ehi * 1e4, 3)],
                    "transfer": json.loads(tr) if tr else None, "weights": json.loads(wj), "members": {m: {"median": px(v["q"][1]), "lo": px(v["lo"]), "hi": px(v["hi"])} for m, v in mem.items()},
                    "live": {"asset": asset_stats(symbol, h, path), "pool": sc["ensemble"]}, "scores": sc, "gate": g,
                    "applied": bool(g["applied"]), "pool": pool, "execution_permission": EXEC, "label": LABEL + (" · transfer" if tr else "")})
    return {"symbol": symbol, "pool": pool, "horizons": out, "models": av, "execution_permission": EXEC, "label": LABEL,
            "note": "Research ensemble: one-bar-ahead return quantiles, split-conformal 80% bands, live-scored. It moves the dashed line only after the gate passes."}


def apply_to_path(nc: dict, hz: dict, now: float | None = None) -> list[str]:
    """Shift the nowcast path (mid, lo, hi together) by the interpolated ensemble drift of every horizon whose live gate passed.
    The band width is untouched. Returns the horizons applied. Never touches the anchor, never creates bars."""
    if nc.get("status") != "ok" or not nc.get("anchor") or not nc.get("path"):
        return []
    t0 = float(nc["anchor"]["t"])
    knots = [(0.0, 0.0)]
    used = []
    for r in hz.get("horizons", []):
        if r.get("status") == "ok" and r.get("applied") and abs(r["target_end"] - t0) <= 2 * HORIZONS[r["h"]][1] + 3600:
            knots.append((HORIZONS[r["h"]][1] / 60.0, math.log(r["median"] / r["base_px"])))
            used.append(r["h"])
    if not used:
        return []
    knots.sort()
    xs, ys = [k[0] for k in knots], [k[1] for k in knots]
    for p in nc["path"]:
        d = float(np.interp((p["t_end"] - t0) / 60.0, xs, ys))
        f = math.exp(d)
        p["ens_drift_bps"] = round(d * 1e4, 3)
        p["mid"], p["lo"], p["hi"] = p["mid"] * f, p["lo"] * f, p["hi"] * f
    nc["ensemble_applied"] = used
    return used


def status(path: str | None = None, root=None) -> dict[str, Any]:
    """Health-page payload: for every (pool, horizon) the live per-member scores, the weights in force, the apply-gate and the training manifest summary."""
    from atlas.ai.prediction.pools import POOLS
    cells = []
    for pool in (*POOLS, "other"):
        for h in HORIZONS:
            man, bundle = load_bundle(pool, h, root)
            sc = model_scores(pool, h, path)
            usable = ["naive", *(bundle or {}).get("models", {}).keys()]
            wt = weights_for(pool, h, usable, path, scores=sc)
            g = gate(pool, h, path, sc)
            mm = (man or {}).get("metrics_oos") or {}
            cells.append({"pool": pool, "h": h, "interval": HORIZONS[h][0], "trained": man is not None, "trained_at": (man or {}).get("created_at"),
                          "n_train": (man or {}).get("n_rows"), "n_test": (man or {}).get("n_test"), "layers_with_any_data": (man or {}).get("layers_with_any_data"),
                          "layers_total": (man or {}).get("layers_total"), "weights": wt["weights"], "weights_basis": wt["basis"], "gate": g,
                          "members": {m: {"live": sc[m], "oos": mm.get(m)} for m in MODELS}, "ensemble_live": sc["ensemble"],
                          "label": LABEL, "execution_permission": EXEC})
    return {"cells": cells, "models": available_models(), "execution_permission": EXEC, "label": LABEL, "gate_rule": f"ensemble moves the dashed line only with >= {GATE_MIN_N} live scores and pinball <= {GATE_MARGIN} x the no-change baseline",
            "note": "Research. Weights come from rolling live pinball (below 30 live scores per member the prior applies). No profitability claim."}


# ----------------------------------------------------------------------------- clock hook
_STATE: dict[str, Any] = {"cursor": 0, "last": None}


def load_bars(feed, sym: str, iv: str) -> list:
    """Real closed bars for (symbol, interval). 5m is derived from real 1m bars (never stored, never invented) when no 5m rows exist."""
    from atlas.ai.ml.dataset import load_series, resample_buckets
    if iv == "5m":
        sd = load_series(feed, sym, "1m")
        return list(resample_buckets(sd, 300, "5m").bars) if sd.bars else []
    return list(load_series(feed, sym, iv).bars)


def _real_close_with_derived(feed):
    from atlas.ai.prediction.clock import real_bar_close
    base = real_bar_close(feed)

    def f(symbol, interval, start):
        v = base(symbol, interval, start)
        if v is None and interval == "5m":
            return base(symbol, "1m", start + 240)       # the last real 1m close of the bucket
        return v
    return f


ANCHOR_H = ("1m", "5m")


def anchored_tick(feed, now: float, pairs: Sequence[tuple[str, str]], path: str | None = None, lmap: dict | None = None, budget_s: float = 8.0) -> dict[str, Any]:
    """Every minute, for each (asset, 1m|5m) with no live intraday series of its own, record the next-bar forecast anchored to the latest REAL bar from any
    source (daily, 15m, 1h, or a permitted quote). It is a zero-drift conformal-band forecast, kept as ONE latest row per (asset, horizon) - not a growing
    ledger - and it is never scored: with no real intraday print there is nothing honest to grade it against (the chip says so).
    Nothing is written to the bar store."""
    from atlas.ai.prediction import nowcast as NC, nowcast_log as NL
    from atlas.ai.prediction.pools import pool_for_symbol
    t0 = time.monotonic()
    c = _conn(path)
    done = skipped = errors = 0
    rows = []
    scale_cache: dict[tuple[str, str], float] = {}
    for sym, h in pairs:
        if time.monotonic() - t0 > budget_s:
            skipped += 1
            continue
        iv = HORIZONS[h][0]
        try:
            pool = pool_for_symbol(sym)
            sc = scale_cache.setdefault((pool, iv), NL.live_scale(pool, iv))
            nc = NC.nowcast(feed, sym, iv, now=now, horizon=1, lmap=lmap, live_scale=sc)
            if nc.get("status") != "ok" or not nc.get("path") or not nc.get("anchor"):
                continue
            tgt = next((p for p in nc["path"] if p["t_end"] > now), None)
            if tgt is None:
                continue
            a = nc["anchor"]
            rows.append((sym, h, now, a["t"], a["price"], nc.get("base_interval"), a.get("provider"), a.get("source"), nc.get("mode"), tgt["t_end"],
                         tgt["mid"], tgt["lo"], tgt["hi"], sc))
            done += 1
        except Exception:  # noqa: BLE001
            errors += 1
    if rows:
        with _LOCK:
            c.executemany("INSERT OR REPLACE INTO hz_anchor VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.commit()
    return {"anchored": done, "skipped_budget": skipped, "errors": errors}


def anchored_row(symbol: str, h: str, now: float, path: str | None = None, pool: str | None = None) -> dict[str, Any] | None:
    c = _conn(path)
    with _LOCK:
        r = c.execute("SELECT made_at,anchor_t,anchor_px,anchor_iv,anchor_provider,anchor_source,mode,target_end,mid,lo,hi,scale FROM hz_anchor WHERE symbol=? AND h=?", (symbol, h)).fetchone()
    if not r or now - r[0] > 600:           # a row the clock stopped refreshing is not shown as current
        return None
    made, at, apx, aiv, aprov, asrc, mode, te, mid, lo, hi, scale = r
    iv = HORIZONS[h][0]
    age_h = max(0.0, now - at) / 3600
    where = f"the latest real {aiv} {'quote' if asrc == 'quote' else 'bar'} ({aprov or 'unknown provider'}, {age_h:.1f} h old)"
    return {"h": h, "interval": iv, "status": "anchored", "made_at": int(made), "base_end": int(at), "target_end": int(te), "base_px": apx,
            "median": mid, "lo": lo, "hi": hi, "ret_bps": round(math.log(mid / apx) * 1e4, 3), "band_bps": [round(math.log(lo / apx) * 1e4, 3), round(math.log(hi / apx) * 1e4, 3)],
            "anchor": {"interval": aiv, "provider": aprov, "source": asrc, "mode": mode}, "applied": False, "transfer": None, "weights": None, "gate": None,
            "live": {"asset": _agg([]), "pool": _agg([])}, "pool": pool,
            "reason": (f"Anchored to {where}. No {iv} bars are stored for {symbol}, so this forecast cannot be graded against a real {iv} print "
                       f"(unscored: no intraday source). It is a zero-drift conformal band, refreshed every minute."),
            "execution_permission": EXEC, "label": "research / unscored · anchored"}


def tick(feed, now: float | None = None, symbols: list[str] | None = None, path: str | None = None, root=None, budget_s: float = 25.0,
         horizons: Sequence[str] = tuple(HORIZONS), ref_loader=None, events=None, extra=None) -> dict[str, Any]:
    """Issue the next-bar forecast for each (symbol, horizon) whose newest closed bar is fresh and not yet forecast, then score what is due.
    Resumes from a cursor when the budget runs out. Never raises."""
    from atlas.ai.prediction import nowcast as NC, service as S
    from atlas.ai.prediction.clock import real_bar_close
    from atlas.ai.prediction.pools import pool_for_symbol
    t0 = time.monotonic()
    now = float(time.time() if now is None else now)
    lmap = S.last_real_map(feed, now, fresh=True)
    ids = symbols or sorted({s for (s, _iv) in lmap})
    cur = int(_STATE.get("cursor", 0)) % max(1, len(ids)) if not symbols else 0
    order = ids[cur:] + ids[:cur]
    _STATE["cursor"] = 0
    counts: dict[str, int] = {}
    errors, sample = 0, None
    need_anchor: list[tuple[str, str]] = []
    c = _conn(path)
    for pos, sym in enumerate(order):
        if time.monotonic() - t0 > budget_s:
            counts["budget_exhausted"] = len(order) - pos
            _STATE["cursor"] = (cur + pos) % len(ids)
            break
        pool = pool_for_symbol(sym)
        for h in horizons:
            iv, dur = HORIZONS[h]
            info = lmap.get((sym, iv))
            if not info and iv == "5m" and lmap.get((sym, "1m")):
                l1 = lmap[(sym, "1m")]["last"] + 60
                info = {"last": (l1 // 300) * 300 - 300}        # newest COMPLETE 5m bucket derived from real 1m bars
            if not info:
                if h in ANCHOR_H:
                    need_anchor.append((sym, h))        # no own intraday series: anchor to the latest real bar from any source
                continue
            base_end = info["last"] + NC.DUR[iv]
            fresh_for = dur * 1.5 if iv != "1d" else 4 * 86400
            if now < base_end or now - base_end > fresh_for:
                if h in ANCHOR_H and now - base_end > fresh_for:
                    need_anchor.append((sym, h))        # the intraday series stopped arriving: same fallback, labelled
                continue
            with _LOCK:
                if c.execute("SELECT 1 FROM hz_issued WHERE symbol=? AND h=? AND base_end=?", (sym, h, base_end)).fetchone():
                    continue
            try:
                bars = [b for b in load_bars(feed, sym, iv) if b.start + b.duration <= now]
                st = issue_one(sym, h, bars, pool, now, path, root, ref_loader, events, extra)
                counts[st] = counts.get(st, 0) + 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                sample = sample or f"{sym} {h}: {type(exc).__name__}: {str(exc)[:120]}"
    res = score_due(_real_close_with_derived(feed), now, path)
    anc = anchored_tick(feed, now, need_anchor, path, lmap=lmap, budget_s=max(3.0, budget_s - (time.monotonic() - t0)))
    out = {"at": int(now), "statuses": counts, "errors": errors, "error_sample": sample, **res, "anchored": anc, "elapsed_s": round(time.monotonic() - t0, 2)}
    _STATE["last"] = out
    return out
