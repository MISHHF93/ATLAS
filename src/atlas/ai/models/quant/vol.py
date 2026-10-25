"""Volatility forecaster: HAR-RV (Corsi 2009) and GARCH(1,1) (arch package), chosen by walk-forward
QLIKE loss. Parameters stored as JSON; forecasts computed by explicit recursions (no pickle).
Output: next-day annualised vol, floored and capped, for vol-target sizing (sizing is capped by policy)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ANN = 252


def _har_X(rv: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"d": rv, "w": rv.rolling(5).mean(), "m": rv.rolling(22).mean()})


def qlike(rv_true, var_fc) -> float:
    a, f = np.asarray(rv_true, float), np.maximum(np.asarray(var_fc, float), 1e-12)
    return float(np.mean(a / f - np.log(a / f) - 1))


@dataclass
class VolModel:
    kind: str                 # "har" | "garch"
    params: dict
    floor_ann: float = 0.05
    cap_ann: float = 2.0
    report: dict | None = None

    # ---------------------------------------------------------------- fitting
    @staticmethod
    def fit_har(r: pd.Series) -> dict:
        rv = (r ** 2).rename("rv")
        X = _har_X(rv)
        y = rv.shift(-1)
        m = X.notna().all(1) & y.notna()
        A = np.column_stack([np.ones(m.sum()), X[m].to_numpy()])
        b, *_ = np.linalg.lstsq(A, y[m].to_numpy(), rcond=None)
        return {"b": b.tolist()}

    @staticmethod
    def fit_garch(r: pd.Series) -> dict:
        try:
            from arch import arch_model
            res = arch_model(r * 100, mean="Zero", vol="GARCH", p=1, q=1, rescale=False).fit(disp="off")
            p = res.params
            return {"omega": float(p["omega"]) / 1e4, "alpha": float(p["alpha[1]"]), "beta": float(p["beta[1]"])}
        except ImportError:
            from scipy.optimize import minimize
            x = (r.dropna().to_numpy(dtype=float)) * 100.0
            v0 = float(np.var(x)) if len(x) else 1.0
            def nll(theta):
                om, al, bt = theta
                if om <= 1e-8 or al < 0.01 or bt < 0.01 or al + bt >= 0.999:
                    return 1e12
                s2 = v0
                ll = 0.0
                for xi in x:
                    s2 = om + al * (xi * xi) + bt * s2
                    ll += np.log(s2) + (xi * xi) / s2
                return 0.5 * ll
            opt = minimize(nll, x0=np.array([0.05 * v0, 0.10, 0.85]), method="Nelder-Mead")
            om, al, bt = opt.x if opt.success else (0.05 * v0, 0.10, 0.85)
            al_c = float(np.clip(al, 0.01, 0.30))
            bt_c = float(np.clip(bt, 0.50, 0.98 - al_c))
            return {"omega": float(max(om, 1e-8)) / 1e4, "alpha": al_c, "beta": bt_c}

    # ---------------------------------------------------------------- forecasting (causal)
    def var_path(self, r: pd.Series) -> pd.Series:
        """One-step-ahead daily variance forecast made at each t using data <= t."""
        if self.kind == "har":
            b = np.asarray(self.params["b"])
            X = _har_X(r ** 2)
            v = b[0] + X.to_numpy() @ b[1:]
            return pd.Series(v, index=r.index).clip(lower=1e-10)
        o, a, bt = self.params["omega"], self.params["alpha"], self.params["beta"]
        x = r.to_numpy(float)
        s2 = np.empty(len(x))
        prev = np.var(x[:min(len(x), 60)]) if len(x) else 1e-4
        for t in range(len(x)):
            prev = o + a * x[t] ** 2 + bt * prev
            s2[t] = prev
        return pd.Series(s2, index=r.index)

    def forecast_ann(self, r: pd.Series) -> float:
        v = self.var_path(r).dropna()
        if v.empty:
            return self.cap_ann  # unknown => assume high vol (smaller size)
        return float(np.clip(np.sqrt(v.iloc[-1] * ANN), self.floor_ann, self.cap_ann))

    @classmethod
    def select(cls, r: pd.Series, n_splits: int = 4) -> "VolModel":
        """Walk-forward: fit on expanding window, score next block by QLIKE; pick the lower loss."""
        r = r.dropna()
        n = len(r)
        edges = np.linspace(int(n * 0.4), n, n_splits + 1).astype(int)
        losses = {"har": [], "garch": []}
        for k in range(n_splits):
            tr, te = r.iloc[:edges[k]], r.iloc[edges[k]:edges[k + 1]]
            for kind in losses:
                try:
                    p = cls.fit_har(tr) if kind == "har" else cls.fit_garch(tr)
                except Exception:  # noqa: BLE001  (e.g. arch missing)
                    losses[kind].append(np.inf); continue
                m = cls(kind, p)
                fc = m.var_path(r.iloc[:edges[k + 1]]).shift(1).iloc[edges[k]:edges[k + 1]]   # forecast made the day before
                ok = fc.notna() & (te ** 2 > 0)
                losses[kind].append(qlike((te ** 2)[ok], fc[ok]))
        mean = {k: float(np.mean(v)) for k, v in losses.items()}
        best = min(mean, key=mean.get)
        m = cls(best, cls.fit_har(r) if best == "har" else cls.fit_garch(r))
        m.report = {"qlike": mean, "chosen": best, "n": n}
        return m

    def save(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "vol.json").write_text(json.dumps({"kind": self.kind, "params": self.params, "floor_ann": self.floor_ann, "cap_ann": self.cap_ann}))

    @classmethod
    def load(cls, d: Path) -> "VolModel":
        return cls(**json.loads((d / "vol.json").read_text()))


def vol_card():
    from atlas.ai.models.quant.modelcard import ModelCard
    return ModelCard("Volatility forecaster", "vol", "Forecast next-day volatility per instrument for vol-target sizing.",
                     "Input to qty = budget x target_vol / forecast_vol, then capped by policy limits.",
                     "Direction forecasts; sizing above policy caps.", "Daily close-to-close returns (PIT).",
                     ["r^2 daily/weekly/monthly (HAR)", "GARCH(1,1) recursion"],
                     ["Close-to-close RV is noisy (no intraday data)", "Vol floor 5% / cap 200% annualised"],
                     ["Underforecast vol -> larger size (bounded by max position % and notional)"],
                     authority="sizing input only; every size is capped by policy")
