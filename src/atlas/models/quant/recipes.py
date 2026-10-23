"""Recipe search: which COMBINATION of existing components and data sources gives the best risk-adjusted return
under the policy limits (2% daily loss, 10% max drawdown, paper). Not raw return.

Recipe = model × data × regime × vol × text-veto × meta-label × conformal sizing × portfolio × cost gate × execution.
* Every evaluated combination is appended to the trial log (family "recipe"), so the Deflated Sharpe Ratio
  is computed against ALL trials ever run (multiple-testing penalty) and PBO (CSCV) over the trial matrix.
* Evaluation: purged, embargoed expanding walk-forward (5 folds); calibration (meta-label, conformal) uses an inner
  hold-out carved from the training fold only. Top recipes are re-checked with CPCV paths.
* Models only rank / gate / shrink: long-only, exposure ≤ 1, vol-targeted, loss limits simulated.
* The winner is registered as a CHALLENGER (kind "recipe"); it must pass the existing champion/challenger shadow
  gates and owner approval. No auto-promotion.

HONESTY: the default data is a SYNTHETIC market with small planted effects in fundamentals/news/macro so the machinery
can be exercised end to end. Results on it demonstrate the search works; they do NOT prove any real edge.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.models.quant.validation import TrialLog, cpcv, pbo_cscv
from atlas.models.quant.metrics import deflated_sharpe, max_drawdown_pct

HORIZON, EMBARGO, REBAL = 5, 5, 5
ANN = 252

DIMENSIONS = {
    "model": ["momentum", "lgbm", "lgbm_stack", "tsfm"],
    "data": ["price", "price+fund", "price+news", "price+macro", "all"],
    "regime": ["none", "hmm"],
    "vol": ["rolling", "har"],
    "text_veto": ["off", "on"],
    "meta": ["off", "on"],
    "conformal": ["off", "on"],
    "portfolio": ["equal", "hrp", "herc"],
    "cost_gate": ["off", "on"],
    "execution": ["market", "twap"],
}
DATA_FEEDS = {   # data channel -> feeds / MCP servers that would supply it (see mcp-autopilot-research.md)
    "price": ["bars.parquet/replay", "Massive MCP (US)", "EODHD MCP (TSX)", "Kraken CLI MCP -s market (crypto)"],
    "fund": ["EODHD fundamentals", "FMP MCP", "Finnhub basic_financials", "SEDAR+ (our adapter)"],
    "news": ["Finnhub news/sentiment MCP", "Benzinga", "GDELT (our adapter)", "EODHD news"],
    "macro": ["Bank of Canada Valet (our adapter)", "FRED (our adapter)", "StatCan WDS (our adapter)"],
}


@dataclass(frozen=True)
class Recipe:
    model: str = "momentum"
    data: str = "price"
    regime: str = "none"
    vol: str = "rolling"
    text_veto: str = "off"
    meta: str = "off"
    conformal: str = "off"
    portfolio: str = "equal"
    cost_gate: str = "off"
    execution: str = "market"

    def valid(self) -> bool:
        if self.model in ("momentum", "tsfm") and self.data != "price":
            return False                              # these models only read prices
        if self.text_veto == "on" and "news" not in self.data and self.data != "all":
            return False                              # nothing to veto with
        return True

    @property
    def key(self) -> str:
        return "|".join(f"{k}={v}" for k, v in asdict(self).items())

    def channels(self) -> set[str]:
        return {"price", "fund", "news", "macro"} if self.data == "all" else set(self.data.split("+"))


def grid() -> list[Recipe]:
    keys = list(DIMENSIONS)
    return [r for r in (Recipe(**dict(zip(keys, v))) for v in itertools.product(*DIMENSIONS.values())) if r.valid()]


# ------------------------------------------------------------------------------------------------ synthetic world
@dataclass
class World:
    close: pd.DataFrame       # date x symbol
    ret: pd.DataFrame         # daily log returns
    fund: pd.DataFrame        # value score (published with 1-day lag)
    news: pd.DataFrame        # daily headline sentiment in [-1,1] (0 = no news)
    macro: pd.DataFrame       # date x [rate_chg_20, curve]
    sleeves: dict[str, str]
    synthetic: bool = True

    @property
    def digest(self) -> str:
        return hashlib.sha256(pd.util.hash_pandas_object(self.close, index=True).values.tobytes()).hexdigest()


def synthetic_world(n_days: int = 1500, seed: int = 11) -> World:
    """Planted, SMALL effects: value tilt, news under-reaction, rates hurt in stress. Noise dominates (as in reality)."""
    rng = np.random.default_rng(seed)
    syms = {"XIC": "core", "VFV": "core", "ZAG": "core", "SHOP": "equity", "RY": "equity", "ENB": "equity",
            "BTC": "crypto", "ETH": "crypto"}
    vol = {"core": 0.008, "equity": 0.015, "crypto": 0.035}
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    n = len(syms)
    # regime: calm(0)/stressed(1) Markov chain
    reg = np.zeros(n_days, int)
    for t in range(1, n_days):
        reg[t] = reg[t - 1] if rng.random() > (0.01 if reg[t - 1] == 0 else 0.05) else 1 - reg[t - 1]
    rate = np.cumsum(rng.normal(0, 0.02, n_days)); rate_chg = pd.Series(rate).diff(20).fillna(0).to_numpy()
    value = np.zeros((n_days, n)); v = rng.normal(0, 1, n)
    news = np.zeros((n_days, n))
    R = np.zeros((n_days, n))
    mkt = rng.normal(0.0003, 0.006, n_days) * np.where(reg == 1, 2.2, 1.0) - np.where(reg == 1, 0.0015, 0.0)
    pending = np.zeros(n)
    for t in range(n_days):
        v = 0.995 * v + rng.normal(0, 0.1, n); value[t] = v
        hit = rng.random(n) < 0.04
        s = np.where(hit, np.clip(rng.normal(0, 0.6, n), -1, 1), 0.0); news[t] = s
        sig = np.array([vol[syms[k]] for k in syms]) * np.where(reg[t] == 1, 1.8, 1.0)
        drift = (0.00008 * value[t - 1] if t else 0) + pending - 0.0004 * rate_chg[t] * reg[t]
        R[t] = mkt[t] * np.array([0.6 if syms[k] != "crypto" else 1.5 for k in syms]) + drift + rng.normal(0, sig) + s * sig * 0.6
        pending = 0.7 * pending + s * sig * 0.08                 # under-reaction: news keeps drifting
    ret = pd.DataFrame(R, idx, list(syms))
    close = 100 * np.exp(ret.cumsum())
    return World(close, ret, pd.DataFrame(value, idx, list(syms)).shift(1), pd.DataFrame(news, idx, list(syms)),
                 pd.DataFrame({"rate_chg_20": rate_chg, "curve": -rate / 10}, idx).shift(1), syms)


def world_from_parquet(d: str | Path, sleeves: dict[str, str] | None = None) -> World:
    """Real point-in-time daily closes (<SYMBOL>.parquet with a close column). Fundamentals/news/macro channels are
    EMPTY (zeros) until those feeds are enabled, so recipes using them carry no information."""
    closes = {p.stem: pd.read_parquet(p)["close"] for p in sorted(Path(d).glob("*.parquet"))}
    close = pd.DataFrame(closes).sort_index().ffill().dropna()
    ret = np.log(close).diff().fillna(0.0)
    z = pd.DataFrame(0.0, close.index, close.columns)
    sl = sleeves or {s: ("crypto" if "-USD" in s or s in ("BTC", "ETH") else "core" if s.endswith((".TO",)) and s[:3] in ("XIC", "VFV", "ZAG") else "equity") for s in close}
    return World(close, ret, z, z, pd.DataFrame({"rate_chg_20": 0.0, "curve": 0.0}, close.index), sl, synthetic=False)


# ------------------------------------------------------------------------------------------------ features
def features(w: World, channels: set[str]) -> dict[str, pd.DataFrame]:
    r = w.ret
    F = {"mom5": r.rolling(5).sum(), "mom20": r.rolling(20).sum(), "mom60": r.rolling(60).sum(),
         "rv20": r.rolling(20).std(), "dist50": np.log(w.close / w.close.rolling(50).mean())}
    d = r.clip(lower=0).rolling(14).mean(); u = (-r.clip(upper=0)).rolling(14).mean()
    F["rsi"] = d / (d + u + 1e-12) - 0.5
    if "fund" in channels:
        F["value"] = w.fund
    if "news" in channels:
        F["news5"] = w.news.rolling(5).sum(); F["news1"] = w.news
    if "macro" in channels:
        for c in w.macro:
            F[c] = pd.DataFrame(np.repeat(w.macro[[c]].to_numpy(), r.shape[1], 1), r.index, r.columns)
    return F


def stack_panel(F: dict[str, pd.DataFrame], target: pd.DataFrame | None = None) -> pd.DataFrame:
    parts = {k: v.stack(future_stack=True) for k, v in F.items()}
    X = pd.DataFrame(parts)
    if target is not None:
        X["y"] = target.stack(future_stack=True)
    X.index.names = ["date", "sym"]
    return X


# ------------------------------------------------------------------------------------------------ models
def _lgbm(seed: int = 0):
    import lightgbm as lgb
    return lgb.LGBMRegressor(n_estimators=120, learning_rate=0.05, num_leaves=15, min_child_samples=50, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=seed, verbose=-1,
                             n_jobs=4, deterministic=True, force_row_wise=True)


class FoldModel:
    """Fits on the training fold (purged), calibrates meta-label + conformal on an inner hold-out (last 20% of train)."""

    def __init__(self, kind: str, sleeves: dict[str, str], tsfm=None):
        self.kind, self.sleeves, self.tsfm = kind, sleeves, tsfm

    def _fit_base(self, X: pd.DataFrame, cols: list[str]):
        if self.kind == "momentum":
            return None
        if self.kind == "tsfm":
            return None
        models = {}
        sl = X.index.get_level_values("sym").map(self.sleeves)
        for s in set(self.sleeves.values()):
            m = sl == s
            if m.sum() > 200:
                models[s] = _lgbm().fit(X.loc[m, cols], X.loc[m, "y"])
        if self.kind == "lgbm_stack":
            models["_global"] = _lgbm(1).fit(X[cols], X["y"])
        return models

    def _predict_base(self, models, X: pd.DataFrame, cols: list[str]) -> np.ndarray:
        if self.kind == "momentum":
            return X["mom20"].to_numpy()
        sl = X.index.get_level_values("sym").map(self.sleeves)
        p = np.zeros(len(X))
        for s, m in models.items():
            if s == "_global":
                continue
            mk = np.asarray(sl == s)
            if mk.any():
                p[mk] = m.predict(X.loc[mk, cols])
        if self.kind == "lgbm_stack":
            g = models["_global"].predict(X[cols])
            return np.column_stack([p, g, X["mom20"].to_numpy()])
        return p


def fold_predictions(w: World, rec_model: str, channels: set[str], folds: list[tuple[pd.Timestamp, pd.Timestamp]],
                     tsfm=None) -> pd.DataFrame:
    """Per rebalance date x symbol: score, meta_p, width (conformal). All computed out-of-sample."""
    from sklearn.linear_model import LogisticRegression, Ridge
    F = features(w, channels)
    fwd = w.ret.rolling(HORIZON).sum().shift(-HORIZON)
    P = stack_panel(F, fwd).dropna(subset=list(F))
    cols = list(F)
    dates = P.index.get_level_values("date")
    out = []
    for start, end in folds:
        train = P[(dates < start - pd.tseries.offsets.BDay(HORIZON + EMBARGO))].dropna(subset=["y"])
        test = P[(dates >= start) & (dates < end)]
        test = test[test.index.get_level_values("date").isin(rebalance_dates(w.close.index, start, end))]
        if len(train) < 500 or test.empty:
            continue
        tdates = train.index.get_level_values("date").unique()
        cut = tdates[int(len(tdates) * 0.8)]
        inner, hold = train[train.index.get_level_values("date") < cut - pd.tseries.offsets.BDay(HORIZON)], train[train.index.get_level_values("date") >= cut]
        fm = FoldModel(rec_model, w.sleeves)
        if rec_model == "tsfm":
            s_hold = _tsfm_scores(w, hold, tsfm, fit_end=cut)
            s_test = _tsfm_scores(w, test, tsfm, fit_end=start)
        else:
            base = fm._fit_base(inner, cols)
            ph, pt = fm._predict_base(base, hold, cols), fm._predict_base(base, test, cols)
            if rec_model == "lgbm_stack":
                st = Ridge(alpha=1.0).fit(ph, hold["y"])
                s_hold, s_test = st.predict(ph), st.predict(pt)
            else:
                s_hold, s_test = ph, pt
        # meta-label: P(primary long is right | score, features) trained on the inner hold-out only
        Mh = np.column_stack([s_hold, hold[cols].to_numpy()])
        Mt = np.column_stack([s_test, test[cols].to_numpy()])
        yb = (hold["y"].to_numpy() > 0).astype(int)
        try:
            lr = LogisticRegression(C=0.5, max_iter=300).fit(np.nan_to_num(Mh), yb)
            meta_p = lr.predict_proba(np.nan_to_num(Mt))[:, 1]
        except ValueError:
            meta_p = np.full(len(test), 0.5)
        # conformal: per-sleeve 80% abs-residual quantile from hold-out; width relative to the global median
        scale = np.std(s_hold) / (np.std(hold["y"]) + 1e-12) if np.std(s_hold) > 0 else 1.0
        res = np.abs(hold["y"].to_numpy() - s_hold / (scale + 1e-12))
        sl_h = hold.index.get_level_values("sym").map(w.sleeves); sl_t = test.index.get_level_values("sym").map(w.sleeves)
        q = {s: float(np.quantile(res[np.asarray(sl_h == s)], 0.8)) if (sl_h == s).sum() > 20 else float(np.quantile(res, 0.8)) for s in set(w.sleeves.values())}
        width = np.array([q[s] for s in sl_t]) * (1 + test["rv20"].to_numpy() / (hold["rv20"].median() + 1e-12)) / 2
        out.append(pd.DataFrame({"score": s_test, "meta_p": meta_p, "width": width, "ref_width": float(np.median(list(q.values())))},
                                index=test.index))
    return pd.concat(out) if out else pd.DataFrame(columns=["score", "meta_p", "width", "ref_width"])


def _tsfm_scores(w: World, rows: pd.DataFrame, tsfm, fit_end) -> np.ndarray:
    if tsfm is None:
        from atlas.models.quant.tsfm import TSFMComponent
        tsfm = TSFMComponent("patch-linear", horizon=HORIZON)
    syms = list(w.ret.columns)
    if tsfm.name == "patch-linear":
        tsfm.fit(w.ret[w.ret.index < fit_end].to_numpy().T)
    sc: dict = {}
    for d in rows.index.get_level_values("date").unique():
        ctx = w.ret[w.ret.index <= d].tail(256).to_numpy().T
        sc.update({(d, s): v for s, v in zip(syms, tsfm.forecast(ctx).scores)})
    return np.array([sc.get(k, 0.0) for k in rows.index])


def rebalance_dates(index: pd.DatetimeIndex, start, end) -> pd.DatetimeIndex:
    d = index[(index >= start) & (index < end)]
    return d[::REBAL]


def walk_forward_folds(index: pd.DatetimeIndex, n_folds: int = 5, oos_frac: float = 0.6) -> list[tuple]:
    first = int(len(index) * (1 - oos_frac))
    edges = np.linspace(first, len(index) - HORIZON, n_folds + 1).astype(int)
    return [(index[a], index[b]) for a, b in zip(edges[:-1], edges[1:])]


# ------------------------------------------------------------------------------------------------ portfolio simulation
COST_BPS = {"market": 10.0, "twap": 6.0}


def simulate(w: World, rec: Recipe, preds: pd.DataFrame, regime_mult: pd.Series | None, har_vol: pd.DataFrame | None,
             daily_loss_pct: float = 2.0, max_dd_pct: float = 10.0, vol_target: float = 0.12) -> dict:
    from atlas.portfolio.construction import _hrp_inhouse, herc, inverse_vol
    ret = w.ret
    days = ret.index[(ret.index >= preds.index.get_level_values("date").min())] if len(preds) else ret.index[:0]
    if len(days) == 0:
        return {"returns": pd.Series(dtype=float)}
    rdates = set(preds.index.get_level_values("date").unique())
    wts = pd.Series(0.0, index=ret.columns)
    out, turnover, breaches, halted_until, peak, eq = [], 0.0, 0, None, 1.0, 1.0
    pending = None
    dd_halts = 0
    for i, d in enumerate(days[:-1]):
        nxt = days[i + 1]
        if pending is not None:          # TWAP: half today, rest applied with the delay
            wts = pending; pending = None
        if d in rdates and (halted_until is None or d >= halted_until):
            p = preds.loc[d]
            s = p["score"].copy()
            size = pd.Series(1.0, index=s.index)
            if rec.meta == "on":
                size *= np.where(p["meta_p"] > 0.5, (p["meta_p"] - 0.5) * 2 + 0.5, 0.0)
            if rec.conformal == "on":
                ref = float(p["ref_width"].iloc[0])
                size *= np.clip(ref / np.maximum(p["width"], 1e-12), 0, 1) * (p["width"] <= 3 * ref)
            if rec.text_veto == "on":
                n5 = w.news.rolling(5).sum().shift(1).loc[d, s.index]   # what was known BEFORE today's open
                size *= np.clip((n5 + 0.6) / 0.4, 0, 1)                   # veto at <= -0.6, downsize to -0.2
            cand = s[(s > 0) & (size > 0)].index
            target = pd.Series(0.0, index=ret.columns)
            if len(cand):
                hist = ret.loc[:d].tail(126)[list(cand)]
                if rec.portfolio == "hrp" and len(cand) > 1:
                    base = _hrp_inhouse(hist)
                elif rec.portfolio == "herc" and len(cand) > 1:
                    try:
                        base = herc(hist)
                    except Exception:  # noqa: BLE001 - optional dependency
                        base = inverse_vol(hist)
                else:
                    base = pd.Series(1 / len(cand), index=cand)
                target[cand] = base * size[cand]
                # vol targeting (portfolio level) with rolling or HAR asset vols, long-only, exposure <= 1
                av = (har_vol.loc[d, cand] if (rec.vol == "har" and har_vol is not None) else hist.std() * math.sqrt(ANN)).clip(lower=0.02)
                corr = hist.corr().fillna(0).to_numpy()
                cov = np.outer(av, av) * corr
                pv = float(np.sqrt(max(target[cand].to_numpy() @ cov @ target[cand].to_numpy(), 1e-12)))
                target *= min(1.0, vol_target / pv) / max(1.0, target.sum())
                if rec.regime == "hmm" and regime_mult is not None:
                    target *= float(regime_mult.asof(d)) if not regime_mult.empty else 1.0
            delta = target - wts
            if rec.cost_gate == "on":
                delta[delta.abs() < 0.02] = 0.0                            # skip trades whose cost likely beats edge
            new = wts + delta
            tc = float(delta.abs().sum()) * COST_BPS[rec.execution] / 1e4
            turnover += float(delta.abs().sum())
            if rec.execution == "twap":
                pending, wts = new, wts + delta / 2
            else:
                wts = new
        else:
            tc = 0.0
        r = float((wts * (np.exp(ret.loc[nxt]) - 1)).sum()) - tc
        if r <= -daily_loss_pct / 100:
            breaches += 1                                                   # engine halts for the day (loss realised)
        out.append(r)
        eq *= 1 + r; peak = max(peak, eq)
        if (peak - eq) / peak * 100 >= max_dd_pct and halted_until is None:
            wts = pd.Series(0.0, index=ret.columns); pending = None
            halted_until = days[min(len(days) - 1, i + 21)]; dd_halts += 1   # drawdown limit: flat ~1 month, re-qualify
            peak = eq
        elif halted_until is not None and d >= halted_until:
            halted_until = None
    rs = pd.Series(out, index=days[1:len(out) + 1])
    return {"returns": rs, "turnover": turnover, "daily_breaches": breaches, "dd_halts": dd_halts}


def regime_multiplier(w: World, fit_end) -> pd.Series:
    from atlas.models.quant.regime import RegimeModel, regime_features
    idx = w.close.mean(axis=1)
    F = regime_features(idx, w.close)
    m = RegimeModel.fit(F[F.index < fit_end], n_states=3)
    return m.risk_multiplier(F)


def har_vols(w: World, fit_end) -> pd.DataFrame:
    from atlas.models.quant.vol import VolModel
    out = {}
    for s in w.ret.columns:
        r = w.ret[s]
        vm = VolModel("har", VolModel.fit_har(r[r.index < fit_end]))
        out[s] = np.sqrt(vm.var_path(r).clip(lower=1e-10) * ANN).clip(0.05, 2.0)
    return pd.DataFrame(out).shift(1)        # forecast known before the day


def score_returns(r: pd.Series, trial_srs: list[float], breaches: int, dd_halts: int) -> dict:
    a = r.to_numpy()
    sd = a.std(ddof=1) if len(a) > 1 else 0
    sr = float(a.mean() / sd) if sd > 0 else 0.0
    d = deflated_sharpe(a, trial_srs if len(trial_srs) >= 2 else trial_srs + [0.0, 0.0])
    mdd = max_drawdown_pct(np.log1p(a))
    neg = a[a < 0]
    sortino = float(a.mean() / neg.std(ddof=1) * math.sqrt(ANN)) if len(neg) > 1 and neg.std(ddof=1) > 0 else 0.0
    cagr = float(np.prod(1 + a) ** (ANN / max(1, len(a))) - 1) * 100
    # objective: risk-adjusted, constraint-aware (not raw return)
    objective = sr * math.sqrt(ANN) - 0.25 * breaches - 0.5 * dd_halts - max(0.0, mdd - 10.0) * 0.1
    return {"sharpe": sr * math.sqrt(ANN), "sortino": sortino, "cagr_pct": cagr, "max_dd_pct": mdd, "vol_pct": sd * math.sqrt(ANN) * 100,
            "daily_breaches": breaches, "dd_halts": dd_halts, "dsr": d["dsr"], "psr": d["psr_vs_0"], "objective": objective,
            "sr_per_period": sr}


# ------------------------------------------------------------------------------------------------ search
def search(world: World | None = None, n_trials: int = 60, seed: int = 7, out_dir: str | Path = "var/recipes",
           trial_log: str | Path | None = None, tsfm_provider: str = "chronos-bolt", progress=None,
           must_include: tuple[Recipe, ...] = ()) -> dict:
    t0 = time.time()
    w = world or synthetic_world()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    log = TrialLog(trial_log or out / "trials.jsonl")
    g = grid()
    rng = random.Random(seed)
    base = Recipe()
    picks = [base, *must_include] + rng.sample([r for r in g if r != base and r not in must_include], max(0, min(n_trials, len(g)) - 1 - len(must_include)))
    folds = walk_forward_folds(w.close.index)
    oos_start = folds[0][0]
    cache: dict[tuple, pd.DataFrame] = {}
    tsfm = None
    if any(r.model == "tsfm" for r in picks):
        from atlas.models.quant.tsfm import TSFMComponent
        tsfm = TSFMComponent(tsfm_provider, horizon=HORIZON)
    rm, hv = regime_multiplier(w, oos_start), har_vols(w, oos_start)
    rows, series = [], {}
    for i, rec in enumerate(picks):
        k = (rec.model, rec.data)
        if k not in cache:
            cache[k] = fold_predictions(w, rec.model, rec.channels(), folds, tsfm)
        sim = simulate(w, rec, cache[k], rm, hv)
        r = sim["returns"]
        if r.empty:
            continue
        series[rec.key] = r
        sr = float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0
        log.append("recipe", asdict(rec), sr, len(r), note=f"world={w.digest[:12]} synthetic={w.synthetic}")
        rows.append({"recipe": rec, "turnover": sim["turnover"], **{"_b": sim["daily_breaches"], "_h": sim["dd_halts"]}})
        if progress:
            progress(i + 1, len(picks), rec)
    all_srs = log.srs("recipe")                               # every trial ever run (incl. previous searches)
    table = []
    for row in rows:
        rec = row["recipe"]
        m = score_returns(series[rec.key], all_srs, row["_b"], row["_h"])
        table.append({"key": rec.key, **asdict(rec), **m, "turnover": row["turnover"]})
    table.sort(key=lambda x: (x["objective"], x["dsr"]), reverse=True)
    M = pd.DataFrame(series).dropna()
    pbo = pbo_cscv(M.to_numpy(), n_blocks=10) if M.shape[1] >= 2 and len(M) > 40 else {"pbo": None}
    # CPCV re-check of the top 3 by path Sharpe dispersion (purged combinatorial paths over the OOS period)
    for t in table[:3]:
        r = series[t["key"]]
        t0s, t1s = r.index, r.index + pd.tseries.offsets.BDay(HORIZON)
        paths = [float(r.iloc[te].mean() / (r.iloc[te].std(ddof=1) + 1e-12) * math.sqrt(ANN)) for _, te, _ in cpcv(t0s, t1s, 6, 2)]
        t["cpcv_sharpe_min"], t["cpcv_sharpe_median"] = float(np.min(paths)), float(np.median(paths))
    feed_value = _feed_value(table)
    res = {"generated": pd.Timestamp.utcnow().isoformat(), "synthetic": w.synthetic, "world_digest": w.digest,
           "grid_size": len(g), "evaluated": len(table), "trial_log_total": len(all_srs), "pbo": pbo.get("pbo"),
           "oos_start": str(oos_start.date()), "oos_end": str(w.close.index[-1].date()), "folds": len(folds),
           "elapsed_s": round(time.time() - t0, 1), "tsfm_provider": tsfm.name if tsfm else None,
           "tsfm_status": tsfm.status if tsfm else None, "table": table, "feed_value": feed_value,
           "baseline": next((t for t in table if t["key"] == base.key), None)}
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def _feed_value(table: list[dict]) -> list[dict]:
    """Marginal value of each data channel: best objective/DSR with the channel vs best price-only (same evaluated set)."""
    def best(pred):
        c = [t for t in table if pred(t)]
        return max(c, key=lambda t: t["objective"]) if c else None
    p = best(lambda t: t["data"] == "price")
    out = []
    for ch in ("fund", "news", "macro"):
        b = best(lambda t: ch in t["data"] or t["data"] == "all")
        if b and p:
            out.append({"channel": ch, "best_with": b["objective"], "best_price_only": p["objective"],
                        "delta_objective": b["objective"] - p["objective"], "delta_sharpe": b["sharpe"] - p["sharpe"],
                        "dsr_with": b["dsr"], "feeds": DATA_FEEDS[ch]})
    return sorted(out, key=lambda x: x["delta_objective"], reverse=True)


# ------------------------------------------------------------------------------------------------ challenger + report
class RecipeConfig:
    """Registered artefact: the recipe definition (JSON). Loaded by the shadow runner; never executes by itself."""

    def __init__(self, recipe: dict, metrics: dict):
        self.recipe, self.metrics = recipe, metrics

    def save(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.json").write_text(json.dumps({"recipe": self.recipe, "metrics": self.metrics}, indent=1, default=str))

    @classmethod
    def load(cls, d: Path) -> "RecipeConfig":
        j = json.loads((d / "recipe.json").read_text())
        return cls(j["recipe"], j["metrics"])


def register_winner(res: dict, models_root: str | Path, audit=None) -> str | None:
    """Winner -> challenger in the 'recipe' registry (must still pass shadow gates + owner approval to promote)."""
    from atlas.models.quant.modelcard import ModelCard
    from atlas.models.quant.registry import ModelRegistry
    if not res["table"]:
        return None
    win = res["table"][0]
    reg = ModelRegistry(Path(models_root) / "recipe", audit=audit, model_cls=RecipeConfig, kind="recipe")
    rec = {k: win[k] for k in DIMENSIONS}
    metrics = {k: win[k] for k in ("sharpe", "sortino", "max_dd_pct", "dsr", "psr", "objective", "daily_breaches", "cpcv_sharpe_median")
               if k in win} | {"pbo": res["pbo"], "n_trials": res["trial_log_total"], "synthetic": res["synthetic"],
                               "validation": {"dsr": win["dsr"], "pbo": res["pbo"], "n_trials": res["trial_log_total"]}}
    card = ModelCard(
        name="Recipe challenger", kind="recipe", purpose="Combination of components chosen by recipe search.",
        intended_use="Shadow-only challenger until it passes champion/challenger gates and owner approval.",
        out_of_scope="Auto-promotion, live trading, exceeding risk limits.",
        data=f"{'SYNTHETIC world' if res['synthetic'] else 'historical bars'} digest {res['world_digest'][:12]}; OOS {res['oos_start']}..{res['oos_end']}",
        features=[f"{k}={v}" for k, v in rec.items()],
        limitations=["Synthetic results do not prove edge." if res["synthetic"] else "Backtest ≠ live.",
                     f"Selected among {res['trial_log_total']} trials (DSR/PBO reported)."],
        risks=["Selection bias (mitigated by DSR + PBO + shadow)", "Regime change"])
    mid = reg.register(RecipeConfig(rec, metrics), metrics, data_hash=res["world_digest"], actor="learning_loop", card=card)
    reg.make_challenger(mid, actor="learning_loop")
    return mid


def render_md(res: dict, top: int = 15) -> str:
    L = ["# Recipe search: ranked results", "",
         f"Generated {res['generated']} · grid {res['grid_size']} valid combinations · **{res['evaluated']} evaluated this run** · "
         f"**{res['trial_log_total']} trials in the log** (all count toward the Deflated Sharpe penalty) · PBO (CSCV) = "
         f"{'n/a' if res['pbo'] is None else format(res['pbo'], '.2f')} · OOS {res['oos_start']} → {res['oos_end']} ({res['folds']} purged walk-forward folds, "
         f"embargo {EMBARGO}d, horizon {HORIZON}d) · TSFM provider: {res.get('tsfm_provider') or 'n/a'} ({res.get('tsfm_status') or '-'})", "",
         "> **Synthetic data warning.** " + ("This run used a SYNTHETIC market with small planted effects. It shows the search, "
         "validation and multiple-testing machinery working end to end. It does **not** prove any real edge. Re-run on point-in-time "
         "historical data (`--parquet-dir`) before drawing conclusions." if res["synthetic"] else "Historical backtest; past ≠ future."), "",
         "Objective = annualised Sharpe − 0.25×(days breaching the 2% daily loss limit) − 0.5×(10% drawdown halts) − 0.1×(DD above 10%). "
         "Ranked by objective, then DSR. Not raw return.", "",
         "| # | model | data | regime | vol | veto | meta | conformal | portfolio | cost gate | exec | Sharpe | DSR | MaxDD % | breaches | CAGR % | CPCV med |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(res["table"][:top], 1):
        L.append(f"| {i} | {t['model']} | {t['data']} | {t['regime']} | {t['vol']} | {t['text_veto']} | {t['meta']} | {t['conformal']} | "
                 f"{t['portfolio']} | {t['cost_gate']} | {t['execution']} | {t['sharpe']:.2f} | {t['dsr']:.2f} | {t['max_dd_pct']:.1f} | "
                 f"{t['daily_breaches']} | {t['cagr_pct']:.1f} | {t.get('cpcv_sharpe_median', float('nan')):.2f} |")
    b = res.get("baseline")
    if b:
        L += ["", f"Baseline (momentum, price-only, everything off): Sharpe {b['sharpe']:.2f}, DSR {b['dsr']:.2f}, MaxDD {b['max_dd_pct']:.1f}%."]
    L += ["", "## Which data feeds add the most expected value", "",
          "| channel | Δ objective vs best price-only | Δ Sharpe | DSR with | would come from |", "|---|---|---|---|---|"]
    for f in res["feed_value"]:
        L.append(f"| {f['channel']} | {f['delta_objective']:+.2f} | {f['delta_sharpe']:+.2f} | {f['dsr_with']:.2f} | {', '.join(f['feeds'])} |")
    return "\n".join(L) + "\n"
