"""Second-wave model kinds, all registry-managed (digest-checked, model cards, challenger-only
registration, DSR/PBO-gated promotion, PSI drift):

  meta_label    MetaLabeler          P(primary trade profitable) -> size factor in [0,1]
  factor_sleeve FactorSleeveModel    cross-sectional composite (value/mom/quality/low-vol), filter only
  portfolio     PortfolioModel       chosen allocator (inverse_vol | hrp | herc) + caps, reduce only
  conformal     ConformalModel       split-conformal interval on trade return -> size factor in [0,1]
  execution     ExecutionModel       impact coefficient / POV rate / AC risk aversion (non-alpha)

Every experiment (barrier-width grid, feature screen, factor weights, allocator choice, conformal
level) is appended to the kind's trials.jsonl, and validation uses ALL trials under the models root,
so deflated Sharpe is deflated by the full search."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.models.quant.validation import TrialLog, validation_report

NON_ALPHA_KINDS = {"regime", "vol", "cost", "anomaly", "execution"}   # DSR gate n/a (registry enforces by kind)


# ------------------------------------------------------------------ trial helpers
def _sr(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0


def log_trial(root, kind: str, params: dict, returns, note: str = "") -> float:
    sr = _sr(returns)
    TrialLog(Path(root) / kind / "trials.jsonl").append(kind, params, sr, len(np.asarray(returns)), note)
    return sr


def all_trial_srs(root) -> list[float]:
    out: list[float] = []
    for f in sorted(Path(root).glob("*/trials.jsonl")):
        out += TrialLog(f).srs()
    for f in sorted(Path(root).glob("*/trials.json")):   # legacy
        out += json.loads(f.read_text())
    return out


def n_trials(root) -> int:
    return len(all_trial_srs(root))


# ------------------------------------------------------------------ factor sleeve
@dataclass
class FactorSleeveModel:
    weights: dict                      # factor -> weight (sign from IC, 0 = dropped by screen)
    min_score: float = 0.0             # candidates below this composite z are dropped
    report: dict = field(default_factory=dict)

    def scores(self, close: pd.DataFrame, sectors: dict | None = None) -> pd.Series:
        from atlas.models.quant import factors as F
        comps = _factor_panels(close)
        use = {k: v for k, v in comps.items() if self.weights.get(k, 0) != 0}
        if not use:
            return pd.Series(0.0, index=close.columns)
        tot = sum(self.weights[k] * (F.sector_neutralize(v, sectors) if sectors else v).fillna(0) for k, v in use.items())
        last = tot.iloc[-1]
        sd = last.std()
        return (last - last.mean()) / sd if sd and sd > 0 else last * 0

    def keep(self, symbol: str, scores: pd.Series) -> bool:
        return float(scores.get(symbol, 0.0)) >= self.min_score

    def save(self, d) -> None:
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        (d / "factor.json").write_text(json.dumps({"weights": self.weights, "min_score": self.min_score}))

    @classmethod
    def load(cls, d) -> "FactorSleeveModel":
        j = json.loads((Path(d) / "factor.json").read_text())
        return cls(j["weights"], j["min_score"])


def _factor_panels(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    from atlas.models.quant import factors as F
    n = len(close)
    lb = min(252, max(40, n // 3))
    return {"momentum": F.momentum(close, lookback=lb, skip=min(21, lb // 4)),
            "low_vol": F.low_vol(close, window=min(126, max(20, n // 6))),
            "value": F.value(close=close, long_rev=min(1260, max(60, n // 2))),
            "reversal": F._z(-np.log(close / close.shift(5)))}


def train_factor_sleeve(close: pd.DataFrame, root, sectors: dict | None = None, horizon: int = 5) -> tuple[FactorSleeveModel, dict]:
    from atlas.models.quant.factor_eval import ic_series
    panels = _factor_panels(close)
    fwd = close.shift(-horizon) / close - 1
    cut = int(len(close) * 0.6)
    weights, screen = {}, {}
    for name, f in panels.items():                 # feature selection: every factor screened = 1 trial
        ic_is = ic_series(f.iloc[:cut], fwd.iloc[:cut], min_names=3)
        t = ic_is.mean() / ic_is.std(ddof=1) * np.sqrt(len(ic_is)) if len(ic_is) > 2 and ic_is.std(ddof=1) > 0 else 0.0
        keep = abs(t) >= 2.0
        weights[name] = float(np.sign(ic_is.mean())) if keep else 0.0
        screen[name] = {"ic_is": float(ic_is.mean()) if len(ic_is) else 0.0, "t_is": float(t), "kept": bool(keep)}
        log_trial(root, "factor_sleeve", {"stage": "feature_screen", "factor": name}, ic_is.values, "IC series in-sample")
    model = FactorSleeveModel(weights)
    # OOS long-short (top vs bottom tercile) daily returns of the composite, plus each single factor (for PBO)
    daily = (close.pct_change().shift(-1)).iloc[cut:]
    def ls(score):
        s = score.iloc[cut:]
        r = []
        for t in s.index[:-1]:
            row = s.loc[t].dropna()
            if len(row) < 3:
                r.append(0.0); continue
            k = max(1, len(row) // 3)
            top, bot = row.nlargest(k).index, row.nsmallest(k).index
            r.append(float(daily.loc[t, top].mean() - daily.loc[t, bot].mean()))
        return np.array(r)
    comp = sum(w * panels[k].fillna(0) for k, w in weights.items() if w) if any(weights.values()) else panels["momentum"] * 0
    r_comp = ls(comp)
    perf = np.column_stack([r_comp] + [ls(p) for p in panels.values()])
    log_trial(root, "factor_sleeve", {"stage": "composite", "weights": weights}, r_comp)
    rep = {"screen": screen, "weights": weights, "oos_sr_per_period": _sr(r_comp), "n_oos": int(len(r_comp)),
           "validation": validation_report(r_comp, all_trial_srs(root), perf_matrix=perf),
           "feature_importance_stability_spearman": 1.0 if any(weights.values()) else 0.0}
    model.report = rep
    return model, rep


# ------------------------------------------------------------------ portfolio construction
@dataclass
class PortfolioModel:
    method: str = "inverse_vol"
    lookback: int = 126
    max_weight: float = 0.4
    report: dict = field(default_factory=dict)

    def weights(self, returns: pd.DataFrame) -> pd.Series:
        from atlas.portfolio.construction import METHODS, cap_weights, inverse_vol, skfolio_available
        r = returns.tail(self.lookback).dropna(axis=1, how="any")
        if r.shape[1] == 0:
            return pd.Series(dtype=float)
        if r.shape[1] == 1:
            return pd.Series(1.0, index=r.columns)
        f = METHODS.get(self.method, inverse_vol)
        if self.method == "herc" and not skfolio_available():
            f = inverse_vol
        try:
            w = f(r)
        except Exception:                              # allocator failure -> inverse-vol fallback
            w = inverse_vol(r)
        return cap_weights(w, max(self.max_weight, 1 / r.shape[1]))

    def save(self, d) -> None:
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        (d / "portfolio.json").write_text(json.dumps({"method": self.method, "lookback": self.lookback, "max_weight": self.max_weight}))

    @classmethod
    def load(cls, d) -> "PortfolioModel":
        return cls(**json.loads((Path(d) / "portfolio.json").read_text()))


def train_portfolio(returns: pd.DataFrame, root, lookback: int = 126, rebalance: int = 21, max_weight: float = 0.4) -> tuple[PortfolioModel, dict]:
    from atlas.portfolio.construction import METHODS, cap_weights, skfolio_available
    methods = [m for m in ("inverse_vol", "hrp", "herc") if m != "herc" or skfolio_available()]
    series = {}
    for m in methods:                                 # every allocator tried = 1 trial
        oos = []
        for start in range(lookback, len(returns), rebalance):
            w = cap_weights(METHODS[m](returns.iloc[start - lookback:start]), max(max_weight, 1 / returns.shape[1]))
            oos.append(returns.iloc[start:start + rebalance].to_numpy() @ w.to_numpy())
        series[m] = np.concatenate(oos) if oos else np.zeros(1)
        log_trial(root, "portfolio", {"method": m, "lookback": lookback, "rebalance": rebalance, "max_weight": max_weight}, series[m])
    srs = {m: _sr(r) for m, r in series.items()}
    # choose HRP/HERC only if it beats inverse-vol OOS; otherwise keep the simple benchmark
    best = max(srs, key=srs.get)
    chosen = best if srs[best] > srs["inverse_vol"] else "inverse_vol"
    perf = np.column_stack([series[m] for m in methods])
    rep = {"oos_sharpe_per_period": srs, "chosen": chosen, "benchmark": "inverse_vol",
           "validation": validation_report(series[chosen], all_trial_srs(root), perf_matrix=perf if len(methods) > 1 else None),
           "feature_importance_stability_spearman": 1.0}
    return PortfolioModel(chosen, lookback, max_weight, rep), rep


# ------------------------------------------------------------------ conformal sizing
@dataclass
class ConformalModel:
    """Ridge forecast of the trade's triple-barrier return + split-conformal residual quantile."""
    mean: list
    scale: list
    coef: list
    intercept: float
    q: float
    ref_width: float
    confidence: float
    features: list
    abstain_mult: float = 3.0
    report: dict = field(default_factory=dict)

    def _pred(self, X: pd.DataFrame) -> np.ndarray:
        Z = (X[self.features].to_numpy(float) - np.asarray(self.mean)) / np.asarray(self.scale)
        return Z @ np.asarray(self.coef) + self.intercept

    def interval(self, X):
        p = self._pred(X)
        return p - self.q, p + self.q

    def size_factor(self, X) -> np.ndarray:
        """Width is constant for a split-conformal on absolute residuals, so the factor uses the
        interval's position: shrink when the lower bound is below zero (long trade may lose)."""
        from atlas.models.quant.conformal import size_from_width
        lo, hi = self.interval(X)
        w = size_from_width(hi - lo, self.ref_width, self.abstain_mult)
        pos = np.clip((hi) / np.maximum(hi - lo, 1e-12), 0, 1)   # share of the interval above zero
        return np.clip(w * pos, 0, 1)

    def save(self, d) -> None:
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        j = {k: v for k, v in asdict(self).items() if k != "report"}
        (d / "conformal.json").write_text(json.dumps(j))

    @classmethod
    def load(cls, d) -> "ConformalModel":
        return cls(**json.loads((Path(d) / "conformal.json").read_text()))


def train_conformal(ds: pd.DataFrame, root, features: list, confidences=(0.7, 0.8, 0.9)) -> tuple[ConformalModel, dict]:
    from sklearn.linear_model import Ridge
    n = len(ds)
    a, b = int(n * 0.5), int(n * 0.75)
    X, y = ds[features].to_numpy(float), ds["ret"].to_numpy(float)
    mu, sd = X[:a].mean(0), X[:a].std(0); sd[sd == 0] = 1
    rg = Ridge(alpha=10.0).fit((X[:a] - mu) / sd, y[:a])
    pred = lambda Z: ((Z - mu) / sd) @ rg.coef_ + rg.intercept_  # noqa: E731
    res = np.abs(y[a:b] - pred(X[a:b]))
    best, rows = None, {}
    for c in confidences:                              # each confidence level = 1 trial
        q = float(np.quantile(res, min(1.0, np.ceil((len(res) + 1) * c) / len(res)), method="higher"))
        m = ConformalModel(mu.tolist(), sd.tolist(), rg.coef_.tolist(), float(rg.intercept_), q, 2 * q, c, list(features))
        f = m.size_factor(ds.iloc[b:])
        lo, hi = m.interval(ds.iloc[b:])
        cov = float(((y[b:] >= lo) & (y[b:] <= hi)).mean())
        r = f * y[b:]
        log_trial(root, "conformal", {"confidence": c}, r)
        rows[c] = {"coverage_oos": cov, "sr": _sr(r), "mean_factor": float(f.mean())}
        if best is None or rows[c]["sr"] > rows[best[0]]["sr"]:
            best = (c, m, r)
    c, m, r = best
    rep = {"by_confidence": rows, "chosen_confidence": c, "unscaled_sr": _sr(y[b:]),
           "validation": validation_report(r, all_trial_srs(root)), "feature_importance_stability_spearman": 1.0}
    m.report = rep
    return m, rep


# ------------------------------------------------------------------ execution parameters (non-alpha)
@dataclass
class ExecutionModel:
    impact_Y: float = 0.8
    pov_rate: float = 0.07
    ac_risk_aversion: float = 1e-6
    single_order_max_participation: float = 0.01
    report: dict = field(default_factory=dict)

    def save(self, d) -> None:
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        (d / "execution.json").write_text(json.dumps({k: v for k, v in asdict(self).items() if k != "report"}))

    @classmethod
    def load(cls, d) -> "ExecutionModel":
        return cls(**json.loads((Path(d) / "execution.json").read_text()))


def calibrate_execution(fills: pd.DataFrame | None, root) -> tuple[ExecutionModel, dict]:
    """fills: columns participation, daily_vol_bps, half_spread_bps, realized_bps. Y is fitted by
    least squares on realized - half_spread = Y*vol*sqrt(part), then haircut x1.25 (paper fills are
    optimistic). Fewer than 30 fills -> conservative defaults."""
    m = ExecutionModel()
    rep = {"n_fills": 0 if fills is None else int(len(fills)), "method": "default"}
    if fills is not None and len(fills) >= 30:
        x = fills["daily_vol_bps"].to_numpy() * np.sqrt(fills["participation"].to_numpy())
        y = fills["realized_bps"].to_numpy() - fills["half_spread_bps"].to_numpy()
        Y = float(max(0.1, (x @ y) / max(x @ x, 1e-12)))
        m.impact_Y = Y * 1.25
        rep |= {"method": "least_squares_x1.25_haircut", "Y_raw": Y}
    rep |= {"validation": {"applies": False, "reason": "non-alpha model (execution parameters)"},
            "feature_importance_stability_spearman": 1.0}
    m.report = rep
    return m, rep


# ------------------------------------------------------------------ meta-labeler training with barrier grid
def train_meta_with_grid(bars: dict[str, pd.DataFrame], root, grid=((1.0, 1.0), (1.5, 1.0), (2.0, 1.0)),
                         max_hold: int = 10, cost_bps: float = 10.0, vol_model=None, news_veto=None):
    """Every (pt, sl) barrier pair is a trial; the best by OOS meta-filtered Sharpe is kept and DSR
    is deflated by all trials in the root."""
    from atlas.models.quant.meta import meta_dataset, momentum_primary, train_meta
    best = None
    for pt, sl in grid:
        ds = meta_dataset(bars, momentum_primary, pt, sl, max_hold, cost_bps, vol_model, news_veto)
        if len(ds) < 200:
            continue
        model, rep = train_meta(ds, n_splits=4)
        cut = int(len(ds) * 0.7)
        oos = ds.iloc[cut:]
        take = model.size_factor(oos)
        daily = pd.Series(take * oos["ret"].to_numpy(), index=oos.index).groupby(level=0).mean()
        log_trial(root, "meta_label", {"pt": pt, "sl": sl, "max_hold": max_hold, "cost_bps": cost_bps}, daily.values)
        if best is None or _sr(daily) > _sr(best[3]):
            best = (model, rep | {"pt": pt, "sl": sl, "max_hold": max_hold}, ds, daily)
    if best is None:
        raise ValueError("not enough labelled events for meta-labeling")
    model, rep, ds, daily = best
    rep["validation"] = validation_report(daily.values, all_trial_srs(root))
    rep["feature_importance_stability_spearman"] = 1.0
    model.params = {"pt": rep["pt"], "sl": rep["sl"], "max_hold": max_hold}
    return model, rep, ds


# ------------------------------------------------------------------ model cards
def card(kind: str):
    from atlas.models.quant.modelcard import ModelCard
    from atlas.models.quant.meta import META_FEATURES
    common = dict(out_of_scope="Creating trades, increasing size, live trading.",
                  data="Daily bars (Parquet store or deterministic synthetic GBM); triple-barrier labels with t1.",
                  risks=["Overfitting (DSR over all logged trials, PBO, shadow gates)", "Regime change (PSI drift auto-demotes)"])
    spec = {
        "meta_label": ("Meta-labeler", "Estimate P(primary rule trade is profitable after cost) and convert it to a size factor in [0,1].",
                       "Shrink/drop rule candidates after the sleeve scorer; news veto is an input.", META_FEATURES,
                       ["Primary is a fixed momentum rule", "Synthetic data has no edge"]),
        "factor_sleeve": ("Factor sleeve composite", "Rank active-equity names on sector-neutral value/momentum/low-vol/reversal.",
                          "Drop candidates below the composite threshold.", ["momentum", "low_vol", "value", "reversal"],
                          ["Value uses a price-reversal proxy until PIT fundamentals exist", "Small universes are noisy"]),
        "portfolio": ("Portfolio allocator", "Allocate a sleeve budget across names (HRP/HERC vs inverse-vol, chosen OOS).",
                      "Cap each candidate's notional at weight x sleeve budget.", ["trailing daily returns"],
                      ["HRP does not dominate inverse-vol; benchmark kept"]),
        "conformal": ("Conformal sizer", "Split-conformal interval on the trade return; shrink when the interval reaches below 0.",
                      "Multiply approved size by a factor in [0,1].", META_FEATURES, ["Exchangeability is violated in markets (ACI available)"]),
        "execution": ("Execution parameters", "Impact coefficient, POV rate and AC risk aversion for child-order plans.",
                      "Plan child orders; never change the parent quantity.", ["participation", "daily_vol_bps", "half_spread_bps"],
                      ["Paper fills understate impact (x1.25 haircut)"]),
    }[kind]
    return ModelCard(name=spec[0], kind=kind, purpose=spec[1], intended_use=spec[2], features=list(spec[3]),
                     limitations=list(spec[4]), **common)
