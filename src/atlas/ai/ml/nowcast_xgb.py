"""XGBoost nowcast workers for markets whose real data arrive late (milestone c / t227u).

Stocks and ETFs on the free Massive plan are T+1 (the current session is not available until the next day), and
FX / metal reference series are daily-only. These workers ESTIMATE the current state of such a market from real,
already-closed, related live inputs (crypto 15m bars) plus what is already known about the target itself.

Hard rules, enforced in code and tests:
  * every output is a PREDICTION: ``predicted=True``, label "Predicted (not market data)", with an 80% interval;
  * predictions live ONLY in their own sqlite ledger (``var/ml/nowcast_xgb/ledger.sqlite``). This module never writes
    to the feed store, and ``assert_real_labels`` refuses any training frame whose label is not a real stored bar
    from a real provider. Predicted rows are never read back as labels or features;
  * a prediction is scored against the real bar once it arrives (``score_due``); the live score is tracked;
  * promotion needs the offline gate (OOS samples >= train.GATES["min_oos"], skill over the baseline (the same XGBoost class
    trained on the target's own previous-session and calendar features only, i.e. WITHOUT the live related inputs) with a block-
    bootstrap CI above zero, interval coverage near nominal) AND the live gate (>= min_oos scored, >= min_shadow_weeks
    weeks, positive live skill). train.GATES is imported unchanged; until both pass status is "research_only";
  * knowledge time for T+1 series is explicit: a target's own session is known only from the next ET calendar day.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml.multires import Bars
from atlas.ai.ml.train import GATES

NY = ZoneInfo("America/New_York")
LABEL = "Predicted (not market data)"
SCHEMA = "atlas-nowcast-xgb-v1"
REAL_PROVIDERS = frozenset({"polygon", "ecb_fx", "boc_valet"})     # label sources; yahoo and anything unofficial is excluded
QUANTILES = (0.1, 0.5, 0.9)
ALPHA = 0.2                                                         # 80% interval
PROXY_PROVIDER = "coinbase"
PROXY_MAJOR = ("BTCUSDT", "ETHUSDT")
PROXY_ALT = ("SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT")
PRIORITY_STOCKS = ("AAPL", "SPY", "QQQ", "GLD", "NVDA", "MSFT", "TSM", "AVGO", "MU", "CRWD", "ROK", "CEG", "OKLO", "VST", "RKLB", "SOFI", "ENPH")
FX_TARGETS = (("ecb_fx", "EUR_USD"), ("boc_valet", "USD_CAD"))
FX_DECISION_UTC_HOUR = 12      # before the ECB (~14:15 UTC) and BoC (~20:30 UTC) publish that day's value
ROOT = Path(os.environ.get("ATLAS_NOWCAST_XGB_ROOT", "var/ml/nowcast_xgb"))
MIN_ROWS = {"stocks_15m": 2000, "stocks_1m": 2000, "fx_1d": 300}

GROUPS = {
    "stocks_15m": {"kind": "stock", "interval": "15m", "step": 900, "provider": "polygon", "proxy_interval": "15m", "proxy_provider": "coinbase"},
    "stocks_1m": {"kind": "stock", "interval": "1m", "step": 60, "provider": "polygon", "proxy_interval": "1m", "proxy_provider": "kraken"},
    "fx_1d": {"kind": "daily", "interval": "1d", "step": 86400, "provider": None, "proxy_interval": "15m", "proxy_provider": "coinbase"},
}


def _store(feed):
    return getattr(feed, "store", feed)


# ------------------------------------------------------------------ proxies (real, closed crypto bars only)
class ProxyLevels:
    """log-close of real crypto bars keyed by bar END; returns need both endpoints to exist (no filling)."""

    def __init__(self, feed, instruments: Sequence[str], start: int, end: int, interval="15m", provider=PROXY_PROVIDER):
        self.interval, self.dur = interval, {"1m": 60, "15m": 900}[interval]
        self.lc: dict[str, dict[int, float]] = {}
        st = _store(feed)
        for ins in instruments:
            rows = st.bars(ins, interval, start, end, provider=provider, confirmed_only=True)
            d = {int(b.event_time) + self.dur: math.log(b.close) for b in rows if b.close > 0}
            if d:
                self.lc[ins] = d

    def ret(self, ins: str, t1: int, t2: int) -> float:
        d = self.lc.get(ins)
        if not d:
            return float("nan")
        a, b = d.get(int(t1)), d.get(int(t2))
        return float("nan") if a is None or b is None else b - a

    def alt(self, t1: int, t2: int) -> float:
        v = [x for x in (self.ret(i, t1, t2) for i in PROXY_ALT) if x == x]
        return float(np.mean(v)) if len(v) >= 3 else float("nan")

    def rv(self, ins: str, T: int, n: int = 16) -> float:
        r = [self.ret(ins, T - (j + 1) * self.dur, T - j * self.dur) for j in range(n)]
        r = [x for x in r if x == x]
        return float(math.sqrt(sum(x * x for x in r))) if len(r) >= n // 2 else float("nan")

    def feats(self, T: int, Tc: int, step: int) -> dict[str, float]:
        f: dict[str, float] = {}
        for name, fn in (("btc", lambda a, b: self.ret("BTCUSDT", a, b)), ("eth", lambda a, b: self.ret("ETHUSDT", a, b)), ("alt", self.alt)):
            f[f"px_{name}_win"] = fn(T - step, T)
            f[f"px_{name}_1h"] = fn(T - 3600, T)
            f[f"px_{name}_24h"] = fn(T - 86400, T)
            f[f"px_{name}_sincec"] = fn(Tc, T)
        f["px_btc_rv16"] = self.rv("BTCUSDT", T)
        return f


PROXY_FEATURES = tuple(f"px_{n}_{w}" for n in ("btc", "eth", "alt") for w in ("win", "1h", "24h", "sincec")) + ("px_btc_rv16",)
STOCK_OWN = ("tgt_prev_ret1d", "tgt_prev_rv", "tgt_prev_range", "tgt_prev_gap")
STOCK_CAL = ("k", "mins_in", "dow")
STOCK_FEATURES = STOCK_OWN + STOCK_CAL + PROXY_FEATURES
FX_FEATURES = ("fx_prev_ret", "fx_prev_rv5", "dow") + PROXY_FEATURES


# ------------------------------------------------------------------ stock sessions (T+1 knowledge time)
def _open_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp())


def _close_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 16, 0, tzinfo=NY).timestamp())


def known_at(session_date: date) -> int:
    """T+1 rule: a stock session becomes usable only at the next ET midnight."""
    n = session_date + timedelta(days=1)
    return int(datetime(n.year, n.month, n.day, tzinfo=NY).timestamp())


@dataclass
class Session:
    date: date
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    step: int

    @property
    def last_close(self) -> float:
        return float(self.c[-1])

    @property
    def end(self) -> int:
        return int(self.ts[-1]) + self.step


def sessions(bars: Bars) -> list[Session]:
    by: dict[date, list[int]] = {}
    for i, t in enumerate(bars.ts):
        by.setdefault(datetime.fromtimestamp(int(t), NY).date(), []).append(i)
    out = []
    for d in sorted(by):
        ix = np.array(by[d])
        out.append(Session(d, bars.ts[ix], bars.o[ix], bars.h[ix], bars.l[ix], bars.c[ix], bars.dur))
    return out


def own_features(prev: Session, prev2: Session | None) -> dict[str, float]:
    """Everything the model may know about the target itself: only the PREVIOUS completed session."""
    c = prev.c
    r = np.log(c[1:] / c[:-1]) if c.shape[0] > 1 else np.array([])
    return {
        "tgt_prev_ret1d": math.log(prev.last_close / prev2.last_close) if prev2 is not None else float("nan"),
        "tgt_prev_rv": float(math.sqrt(float(np.sum(r * r)))) if r.size else float("nan"),
        "tgt_prev_range": math.log(float(prev.h.max()) / float(prev.l.min())),
        "tgt_prev_gap": math.log(float(prev.o[0]) / prev2.last_close) if prev2 is not None else float("nan"),
    }


def stock_row(T: int, prev: Session, prev2: Session | None, proxy: ProxyLevels, step: int) -> dict[str, float]:
    d = datetime.fromtimestamp(T - 1, NY)
    f = own_features(prev, prev2)
    f.update(k=(T - _open_ts(d.date())) / step, mins_in=(T - _open_ts(d.date())) / 60.0, dow=float(d.weekday()))
    f.update(proxy.feats(T, prev.end, step))
    return f


def stock_samples(feed, target: str, group: str, start: int, end: int) -> pd.DataFrame:
    g = GROUPS[group]
    st = _store(feed)
    rows = st.bars(target, g["interval"], start - 10 * 86400, end, provider=g["provider"], confirmed_only=True)
    if not rows:
        return pd.DataFrame()
    bars = Bars.from_feed(g["interval"], rows)
    sess = sessions(bars)
    proxy = _proxy(feed, group, start - 3 * 86400, end)
    out = []
    for i in range(1, len(sess)):
        s, prev = sess[i], sess[i - 1]
        if (s.date - prev.date).days > 4 or prev.ts.shape[0] < (12 if g["step"] == 900 else 120) or s.date < datetime.fromtimestamp(start, NY).date():
            continue
        prev2 = sess[i - 2] if i >= 2 and (prev.date - sess[i - 2].date).days <= 4 else None
        anchor = prev.last_close
        for j in range(s.ts.shape[0]):
            T = int(s.ts[j]) + g["step"]
            row = stock_row(T, prev, prev2, proxy, g["step"])
            if row["px_btc_win"] != row["px_btc_win"]:
                continue                                         # no real proxy input for this window: no sample
            row.update(target=target, window_end=T, date=s.date.isoformat(), anchor=anchor, y=math.log(float(s.c[j]) / anchor),
                       label_source="real_bar", provider=g["provider"])
            out.append(row)
    return pd.DataFrame(out)


def _proxy(feed, group: str, start: int, end: int) -> ProxyLevels:
    g = GROUPS[group]
    return ProxyLevels(feed, PROXY_MAJOR + PROXY_ALT, start, end, g["proxy_interval"], g["proxy_provider"])


def fx_samples(feed, group: str, start: int, end: int, targets=FX_TARGETS) -> pd.DataFrame:
    st = _store(feed)
    proxy = _proxy(feed, group, start - 3 * 86400, end)
    out = []
    for provider, target in targets:
        rows = st.bars(target, "1d", start - 10 * 86400, end, provider=provider, confirmed_only=True)
        b = Bars.from_feed("1d", rows) if rows else None
        if b is None or len(b) < 8:
            continue
        lc = np.log(b.c)
        for i in range(6, len(b)):
            if b.ts[i] < start or b.ts[i] - b.ts[i - 1] > 4 * 86400:
                continue
            T = int(b.ts[i]) + FX_DECISION_UTC_HOUR * 3600
            Tp = int(b.ts[i - 1]) + FX_DECISION_UTC_HOUR * 3600
            row = {"fx_prev_ret": float(lc[i - 1] - lc[i - 2]), "fx_prev_rv5": float(math.sqrt(float(np.sum(np.diff(lc[i - 5:i]) ** 2)))),
                   "dow": float(datetime.utcfromtimestamp(int(b.ts[i])).weekday())}
            row.update(proxy.feats(T, Tp, T - Tp))
            row["px_btc_win"] = proxy.ret("BTCUSDT", Tp, T)
            if row["px_btc_win"] != row["px_btc_win"]:
                continue
            row.update(target=target, window_end=T, date=datetime.utcfromtimestamp(int(b.ts[i])).date().isoformat(),
                       anchor=float(b.c[i - 1]), y=float(lc[i] - lc[i - 1]), label_source="real_bar", provider=provider, k=0.0)
            out.append(row)
    return pd.DataFrame(out)


def features_for(group: str) -> tuple[str, ...]:
    return FX_FEATURES if GROUPS[group]["kind"] == "daily" else STOCK_FEATURES


def own_features_for(group: str) -> tuple[str, ...]:
    """the BASELINE model sees only what is known about the target itself plus the calendar, never the live related
    inputs. Skill over it therefore measures the marginal value of the real related inputs (not mere volatility scaling)."""
    return tuple(f for f in features_for(group) if f not in PROXY_FEATURES)


def assert_real_labels(df: pd.DataFrame) -> None:
    """Training guard: labels must be real stored bars from real providers, never a prediction."""
    if len(df) == 0:
        return
    if "label_source" not in df or not (df["label_source"] == "real_bar").all():
        raise ValueError("training frame contains labels that are not real bars")
    if not df["provider"].isin(REAL_PROVIDERS).all():
        raise ValueError("training labels must come from a real provider")
    if any(c.startswith("pred") for c in df.columns):
        raise ValueError("training frame must not carry predicted columns")


# ------------------------------------------------------------------ model
def _xgb():
    import xgboost as xgb
    return xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array(QUANTILES), tree_method="hist", n_estimators=160,
                            max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=40, reg_lambda=5.0,
                            n_jobs=2, random_state=7)


def split_dates(dates: Sequence[str], test_frac=0.25, cal_frac=0.15, embargo=2) -> tuple[set, set, set]:
    """Chronological train / calibration / test by DATE with an embargo of whole sessions between blocks (purged)."""
    ds = sorted(set(dates))
    n = len(ds)
    n_test, n_cal = max(1, int(n * test_frac)), max(1, int(n * cal_frac))
    te0 = n - n_test
    ca0 = te0 - embargo - n_cal
    tr1 = ca0 - embargo
    if tr1 < 5:
        raise ValueError("not enough sessions for a purged split")
    return set(ds[:tr1]), set(ds[ca0:te0 - embargo]), set(ds[te0:])


def pinball(y: np.ndarray, q: np.ndarray) -> np.ndarray:
    """mean pinball loss over the three quantiles, per row. q: (n,3)."""
    tau = np.array(QUANTILES)
    d = y[:, None] - q
    return np.mean(np.maximum(tau * d, (tau - 1) * d), axis=1)


def cqr_margin(y: np.ndarray, q: np.ndarray) -> float:
    """split-conformal (CQR) margin so [q10 - m, q90 + m] covers >= 1-ALPHA on exchangeable data."""
    e = np.maximum(q[:, 0] - y, y - q[:, 2])
    n = len(e)
    if n < 20:
        return float("nan")
    k = min(1.0, math.ceil((n + 1) * (1 - ALPHA)) / n)
    return float(np.quantile(e, k, method="higher"))


def baseline_quantiles(df: pd.DataFrame, key: str = "k") -> dict:
    """no-information baseline: empirical training quantiles of the label per ``key`` (unconditional on any input)."""
    out = {}
    for k, g in df.groupby(key):
        out[float(k)] = [float(np.quantile(g["y"], t)) for t in QUANTILES]
    out["_all"] = [float(np.quantile(df["y"], t)) for t in QUANTILES]
    return out


def base_q(base: dict, k: float) -> list[float]:
    return base.get(float(k), base["_all"])


def block_bootstrap_ci(dates: np.ndarray, diff: np.ndarray, reps=1000, seed=11) -> tuple[float, float]:
    """95% CI of mean(diff) resampling whole DATES (loss differences are correlated within a day)."""
    ud = np.unique(dates)
    sums = {d: (float(diff[dates == d].sum()), int((dates == d).sum())) for d in ud}
    rng = np.random.default_rng(seed)
    m = []
    for _ in range(reps):
        pick = rng.choice(ud, size=len(ud), replace=True)
        s = sum(sums[d][0] for d in pick)
        n = sum(sums[d][1] for d in pick)
        m.append(s / n)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def train_group(group: str, df: pd.DataFrame, *, root: Path | None = None, save: bool = True) -> dict:
    """Smoke-train one group on real bars only; returns the report (offline gate included) and saves the model."""
    assert_real_labels(df)
    feats = list(features_for(group))
    rep: dict = {"group": group, "schema": SCHEMA, "rows": int(len(df)), "features": feats, "label": "real stored bar (log return vs last known close)"}
    if len(df) < MIN_ROWS[group]:
        rep.update(status="insufficient_data", gate_pass=False, reasons=[f"rows {len(df)} < {MIN_ROWS[group]} (real overlap of target and proxy bars is too short)"])
        return rep
    try:
        tr, ca, te = split_dates(df["date"].tolist())
    except ValueError as e:
        rep.update(status="insufficient_data", gate_pass=False, reasons=[str(e)])
        return rep
    d_tr, d_ca, d_te = (df[df["date"].isin(s)] for s in (tr, ca, te))
    own = list(own_features_for(group))
    m, mb = _xgb(), _xgb()
    m.fit(d_tr[feats].to_numpy(float), d_tr["y"].to_numpy(float))
    mb.fit(d_tr[own].to_numpy(float), d_tr["y"].to_numpy(float))

    def pq(model, cols, d):
        return np.sort(np.asarray(model.predict(d[cols].to_numpy(float))).reshape(len(d), 3), axis=1)

    q_ca, q_te = pq(m, feats, d_ca), pq(m, feats, d_te)
    margin = cqr_margin(d_ca["y"].to_numpy(float), q_ca)
    b_ca, b_te = pq(mb, own, d_ca), pq(mb, own, d_te)         # baseline = same model class WITHOUT the live related inputs
    b_margin = cqr_margin(d_ca["y"].to_numpy(float), b_ca)
    uncond = baseline_quantiles(d_tr)
    u_te = np.array([base_q(uncond, k) for k in d_te["k"]])
    y = d_te["y"].to_numpy(float)
    lm, lb = pinball(y, q_te), pinball(y, b_te)
    cov = float(np.mean((y >= q_te[:, 0] - margin) & (y <= q_te[:, 2] + margin)))
    cov_b = float(np.mean((y >= b_te[:, 0] - b_margin) & (y <= b_te[:, 2] + b_margin)))
    width = float(np.mean(q_te[:, 2] - q_te[:, 0] + 2 * margin))
    width_b = float(np.mean(b_te[:, 2] - b_te[:, 0] + 2 * b_margin))
    ci = block_bootstrap_ci(d_te["date"].to_numpy(), lb - lm)
    mae_m, mae_n = float(np.mean(np.abs(y - q_te[:, 1]))), float(np.mean(np.abs(y)))
    nz = y != 0
    skill = 1.0 - float(lm.mean() / lb.mean())
    skill_uncond = 1.0 - float(lm.mean() / pinball(y, u_te).mean())
    reasons = []
    if len(d_te) < GATES["min_oos"]:
        reasons.append(f"oos {len(d_te)} < min_oos {GATES['min_oos']}")
    if ci[0] <= 0:
        reasons.append("pinball skill over the baseline is not significantly above zero (95% date-block CI includes 0)")
    if not (0.75 <= cov <= 0.85):
        reasons.append(f"interval coverage {cov:.3f} outside 0.75-0.85")
    mid = hashlib.sha1(f"{group}|{SCHEMA}|{max(tr)}|{len(df)}".encode()).hexdigest()[:10]
    rep.update(model_id=f"{group}-{mid}", train_dates=[min(tr), max(tr)], cal_dates=[min(ca), max(ca)], test_dates=[min(te), max(te)],
               n_train=len(d_tr), n_cal=len(d_ca), n_test=len(d_te), cqr_margin=margin, baseline_margin=b_margin,
               pinball_model=float(lm.mean()), pinball_baseline=float(lb.mean()), skill=skill, skill_vs_unconditional=skill_uncond,
               baseline="same XGBoost class on own-session + calendar features only (no live related inputs)",
               skill_ci95=[float(ci[0] / lb.mean()), float(ci[1] / lb.mean())],
               mae_model=mae_m, mae_naive_zero=mae_n, coverage=cov, coverage_baseline=cov_b, width=width, width_baseline=width_b,
               directional_hit=float(np.mean(np.sign(q_te[nz, 1]) == np.sign(y[nz]))) if nz.any() else float("nan"),
               gate_pass=not reasons, reasons=reasons, status="offline_pass_pending_live" if not reasons else "research_only",
               gates={"min_oos": GATES["min_oos"], "min_shadow_weeks": GATES["min_shadow_weeks"]})
    if save:
        root = Path(root or ROOT) / group
        root.mkdir(parents=True, exist_ok=True)
        m.save_model(str(root / f"{rep['model_id']}.json"))
        mb.save_model(str(root / f"{rep['model_id']}.base.json"))
        (root / f"{rep['model_id']}.meta.json").write_text(json.dumps(rep, indent=1))
    rep["_model"], rep["_bmodel"] = m, mb
    return rep


def load_bundle(group: str, root: Path | None = None) -> dict | None:
    import xgboost as xgb
    d = Path(root or ROOT) / group
    metas = sorted(d.glob("*.meta.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    if not metas:
        return None
    meta = json.loads(metas[-1].read_text())
    stem = str(metas[-1]).replace(".meta.json", "")
    m, mb = xgb.XGBRegressor(), xgb.XGBRegressor()
    m.load_model(stem + ".json")
    mb.load_model(stem + ".base.json")
    meta["_model"], meta["_bmodel"] = m, mb
    return meta


def own_features_for_features(feats: Sequence[str]) -> list[str]:
    return [f for f in feats if f not in PROXY_FEATURES]


def predict_row(bundle: dict, row: dict) -> dict:
    feats = bundle["features"]
    x = np.array([[row.get(f, float("nan")) for f in feats]], dtype=float)
    q = np.sort(np.asarray(bundle["_model"].predict(x)).reshape(1, 3), axis=1)[0]
    mg = bundle.get("cqr_margin")
    mg = 0.0 if mg is None or mg != mg else float(mg)
    own = [row.get(f, float("nan")) for f in own_features_for_features(feats)]
    bq = [float(v) for v in np.sort(np.asarray(bundle["_bmodel"].predict(np.array([own], dtype=float))).reshape(3))]
    return {"q10": float(q[0]), "q50": float(q[1]), "q90": float(q[2]), "lo": float(q[0] - mg), "hi": float(q[2] + mg), "base_q": bq}


# ------------------------------------------------------------------ ledger (predictions never touch the feed store)
LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS issued(
  group_name TEXT NOT NULL, target TEXT NOT NULL, window_end INTEGER NOT NULL, model_id TEXT NOT NULL,
  made_at INTEGER NOT NULL, window_step INTEGER NOT NULL, anchor REAL NOT NULL,
  q10 REAL NOT NULL, q50 REAL NOT NULL, q90 REAL NOT NULL, lo REAL NOT NULL, hi REAL NOT NULL,
  b10 REAL NOT NULL, b50 REAL NOT NULL, b90 REAL NOT NULL, status TEXT NOT NULL,
  predicted INTEGER NOT NULL DEFAULT 1 CHECK(predicted=1),
  PRIMARY KEY(group_name, target, window_end, model_id));
CREATE TABLE IF NOT EXISTS scored(
  group_name TEXT NOT NULL, target TEXT NOT NULL, window_end INTEGER NOT NULL, model_id TEXT NOT NULL,
  scored_at INTEGER NOT NULL, actual REAL NOT NULL, err REAL NOT NULL, abs_err REAL NOT NULL, naive_abs_err REAL NOT NULL,
  pinball REAL NOT NULL, base_pinball REAL NOT NULL, covered INTEGER NOT NULL, dir_hit INTEGER,
  PRIMARY KEY(group_name, target, window_end, model_id));
"""


def default_ledger_path() -> str:
    env = os.environ.get("ATLAS_NOWCAST_XGB_LEDGER")
    if env:
        return env
    return ":memory:" if "pytest" in sys.modules else str(ROOT / "ledger.sqlite")


class Ledger:
    def __init__(self, path: str | None = None):
        self.path = path or default_ledger_path()
        self._lock = threading.Lock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._c.executescript(LEDGER_SQL)

    def issue(self, group: str, target: str, window_end: int, model_id: str, step: int, anchor: float, pred: dict, status: str, now: int) -> None:
        b = pred["base_q"]
        with self._lock, self._c:
            self._c.execute("INSERT OR IGNORE INTO issued VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                            (group, target, int(window_end), model_id, int(now), int(step), float(anchor), pred["q10"], pred["q50"], pred["q90"],
                             pred["lo"], pred["hi"], b[0], b[1], b[2], status))

    def pending(self, now: int) -> list[tuple]:
        with self._lock:
            return self._c.execute("SELECT i.group_name,i.target,i.window_end,i.model_id,i.window_step,i.anchor,i.q10,i.q50,i.q90,i.lo,i.hi,i.b10,i.b50,i.b90 "
                                   "FROM issued i LEFT JOIN scored s USING(group_name,target,window_end,model_id) "
                                   "WHERE s.window_end IS NULL AND i.window_end<=? ORDER BY i.window_end", (int(now),)).fetchall()

    def add_score(self, g, t, we, mid, now, actual, err, aerr, nerr, pin, bpin, cov, hit) -> None:
        with self._lock, self._c:
            self._c.execute("INSERT OR IGNORE INTO scored VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (g, t, int(we), mid, int(now), actual, err, aerr, nerr, pin, bpin, int(cov), hit))

    def issued_rows(self, group: str | None = None) -> list[tuple]:
        with self._lock:
            q = "SELECT * FROM issued" + (" WHERE group_name=?" if group else "")
            return self._c.execute(q, (group,) if group else ()).fetchall()

    def summary(self, group: str) -> dict:
        with self._lock:
            r = self._c.execute("SELECT COUNT(*),AVG(abs_err),AVG(naive_abs_err),AVG(pinball),AVG(base_pinball),AVG(covered),AVG(dir_hit),MIN(window_end),MAX(window_end) "
                                "FROM scored WHERE group_name=?", (group,)).fetchone()
            n_issued = self._c.execute("SELECT COUNT(*) FROM issued WHERE group_name=?", (group,)).fetchone()[0]
        n = int(r[0])
        out = {"group": group, "issued": int(n_issued), "scored": n, "unscored": int(n_issued) - n}
        if n:
            weeks = (r[8] - r[7]) / (7 * 86400)
            skill = 1.0 - r[3] / r[4] if r[4] else float("nan")
            reasons = []
            if n < GATES["min_oos"]:
                reasons.append(f"live scored {n} < min_oos {GATES['min_oos']}")
            if weeks < GATES["min_shadow_weeks"]:
                reasons.append(f"shadow span {weeks:.1f} weeks < {GATES['min_shadow_weeks']}")
            if not skill > 0:
                reasons.append("live pinball skill over the baseline is not positive")
            out.update(mae_model=r[1], mae_naive_zero=r[2], pinball=r[3], base_pinball=r[4], skill=skill, coverage=r[5], directional_hit=r[6],
                       weeks=weeks, live_gate_pass=not reasons, live_reasons=reasons)
        else:
            out.update(live_gate_pass=False, live_reasons=["nothing scored yet"])
        return out

    def close(self) -> None:
        self._c.close()


def status_of(bundle: dict | None, live: dict | None) -> tuple[str, list[str]]:
    if not bundle or "model_id" not in bundle:
        return "no_model", ["no trained model"]
    if not bundle.get("gate_pass"):
        return "research_only", list(bundle.get("reasons", []))
    if not live or not live.get("live_gate_pass"):
        return "offline_pass_pending_live", list((live or {}).get("live_reasons", ["no live score yet"]))
    return "promoted_for_display", []


def payload(group: str, target: str, window_end: int, step: int, anchor: float, pred: dict, bundle: dict, status: str, reasons: list[str]) -> dict:
    """API shape: always a prediction, never a bar. Prices are anchor * exp(log-return estimate)."""
    px = lambda r: anchor * math.exp(r)
    return {"predicted": True, "label": LABEL, "group": group, "target": target, "window_start": window_end - step, "window_end": window_end,
            "anchor_close": anchor, "anchor_note": "last REAL close known at decision time (T+1 for stocks)",
            "est_return": pred["q50"], "est_price": px(pred["q50"]), "interval80": {"lo": px(pred["lo"]), "hi": px(pred["hi"]), "lo_return": pred["lo"], "hi_return": pred["hi"]},
            "model_id": bundle.get("model_id"), "schema": SCHEMA, "status": status, "gate_reasons": reasons,
            "execution_permission": "none", "advice": False, "note": "predicted signal, not market data and not advice"}


# ------------------------------------------------------------------ issue + score against real bars
def _latest_closed_window(now: int, step: int) -> int:
    return (int(now) // step) * step


def issue_stock(feed, ledger: Ledger, bundle: dict, group: str, target: str, now: int) -> dict | None:
    """Predict the latest CLOSED RTH window of a T+1 stock. Returns None outside regular hours or without inputs."""
    g = GROUPS[group]
    step = g["step"]
    T = _latest_closed_window(now, step)
    d = datetime.fromtimestamp(T - 1, NY)
    if d.weekday() > 4 or not (_open_ts(d.date()) < T <= _close_ts(d.date())):
        return None
    st = _store(feed)
    rows = [b for b in st.bars(target, g["interval"], _open_ts(d.date()) - 12 * 86400, _open_ts(d.date()), provider=g["provider"], confirmed_only=True)
            if datetime.fromtimestamp(int(b.event_time), NY).date() < d.date()]
    if not rows:
        return None
    sess = sessions(Bars.from_feed(g["interval"], rows))
    prev = sess[-1]
    if (d.date() - prev.date).days > 4 or known_at(prev.date) > now:
        return None
    prev2 = sess[-2] if len(sess) >= 2 else None
    proxy = _proxy(feed, group, T - 3 * 86400, T)
    row = stock_row(T, prev, prev2, proxy, step)
    if row["px_btc_win"] != row["px_btc_win"]:
        return None
    pred = predict_row(bundle, row)
    from_ledger = ledger.summary(group)
    status, reasons = status_of(bundle, from_ledger)
    ledger.issue(group, target, T, bundle["model_id"], step, prev.last_close, pred, status, now)
    return payload(group, target, T, step, prev.last_close, pred, bundle, status, reasons)


def issue_fx(feed, ledger: Ledger, bundle: dict, group: str, provider: str, target: str, now: int) -> dict | None:
    d = datetime.utcfromtimestamp(now).date()
    T = int(datetime(d.year, d.month, d.day, FX_DECISION_UTC_HOUR, tzinfo=ZoneInfo("UTC")).timestamp())
    if now < T or d.weekday() > 4:
        return None
    st = _store(feed)
    day0 = int(datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("UTC")).timestamp())
    rows = st.bars(target, "1d", day0 - 14 * 86400, day0, provider=provider, confirmed_only=True)      # strictly before today
    if len(rows) < 7:
        return None
    b = Bars.from_feed("1d", rows)
    lc = np.log(b.c)
    Tp = int(b.ts[-1]) + FX_DECISION_UTC_HOUR * 3600
    if T - Tp > 5 * 86400:
        return None
    proxy = _proxy(feed, group, Tp - 86400, T)
    row = {"fx_prev_ret": float(lc[-1] - lc[-2]), "fx_prev_rv5": float(math.sqrt(float(np.sum(np.diff(lc[-6:]) ** 2)))), "dow": float(d.weekday()), "k": 0.0}
    row.update(proxy.feats(T, Tp, T - Tp))
    if row["px_btc_win"] != row["px_btc_win"]:
        return None
    pred = predict_row(bundle, row)
    status, reasons = status_of(bundle, ledger.summary(group))
    ledger.issue(group, target, day0 + 86400, bundle["model_id"], 86400, float(b.c[-1]), pred, status, now)    # window_end = end of the UTC day it describes
    return payload(group, target, day0 + 86400, 86400, float(b.c[-1]), pred, bundle, status, reasons)


def score_due(feed, ledger: Ledger, now: int | None = None) -> int:
    """Compare issued predictions with the REAL bar once it exists in the store; returns the number newly scored."""
    now = int(now if now is not None else time.time())
    st = _store(feed)
    n = 0
    for g, t, we, mid, step, anchor, q10, q50, q90, lo, hi, b10, b50, b90 in ledger.pending(now):
        grp = GROUPS[g]
        if grp["kind"] == "stock":
            bars = st.bars(t, grp["interval"], we - step, we, provider=grp["provider"], confirmed_only=True)
        else:
            provider = dict((tt, pp) for pp, tt in FX_TARGETS)[t]
            bars = st.bars(t, "1d", we - 86400, we, provider=provider, confirmed_only=True)
        bars = [b for b in bars if int(b.event_time) + (step if grp["kind"] == "stock" else 86400) == we]
        if not bars or bars[0].close <= 0 or anchor <= 0:
            continue
        actual = math.log(bars[0].close / anchor)
        q = np.array([[q10, q50, q90]])
        bq = np.array([[b10, b50, b90]])
        ya = np.array([actual])
        hit = None if actual == 0 else int(np.sign(q50) == np.sign(actual))
        ledger.add_score(g, t, we, mid, now, actual, actual - q50, abs(actual - q50), abs(actual), float(pinball(ya, q)[0]), float(pinball(ya, bq)[0]),
                         int(lo <= actual <= hi), hit)
        n += 1
    return n
