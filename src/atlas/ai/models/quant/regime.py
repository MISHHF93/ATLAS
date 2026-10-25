"""Market regime detector: Gaussian HMM (hmmlearn) on daily index return, realized vol and breadth;
falls back to a Gaussian mixture if hmmlearn is unavailable. States are ordered by volatility
(calm < normal < stressed). Inference uses the causal FORWARD filter only (no smoothing, so no
look-ahead). Output is a risk multiplier in [floor, 1]: it can only scale the risk budget DOWN."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REGIME_FEATURES = ["ret_20", "rv_20", "breadth"]
DEFAULT_MULT = {"calm": 1.0, "normal": 0.75, "stressed": 0.4}
NAMES = {2: ["calm", "stressed"], 3: ["calm", "normal", "stressed"]}


def regime_features(index_close: pd.Series, universe_closes: pd.DataFrame | None = None) -> pd.DataFrame:
    r = np.log(index_close).diff()
    out = pd.DataFrame(index=index_close.index)
    out["ret_20"] = r.rolling(20).sum()
    out["rv_20"] = r.rolling(20).std() * np.sqrt(252)
    if universe_closes is not None and universe_closes.shape[1] > 0:
        out["breadth"] = (universe_closes > universe_closes.rolling(50).mean()).mean(axis=1).where(universe_closes.rolling(50).count().min(axis=1) >= 50)
    else:
        out["breadth"] = (index_close > index_close.rolling(50).mean()).astype(float).where(index_close.rolling(50).count() >= 50)
    return out.dropna()


@dataclass
class RegimeModel:
    mean: list            # scaler
    scale: list
    means: list           # [k][d] in scaled space, ordered calm..stressed
    covars: list          # [k][d] diagonal
    transmat: list
    startprob: list
    names: list
    mult: dict = field(default_factory=lambda: dict(DEFAULT_MULT))
    floor: float = 0.25
    backend: str = "hmm"

    @classmethod
    def fit(cls, F: pd.DataFrame, n_states: int = 3, seed: int = 7) -> "RegimeModel":
        X = F[REGIME_FEATURES].to_numpy(float)
        mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
        Z = (X - mu) / sd
        try:
            from hmmlearn.hmm import GaussianHMM
            m = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=200, random_state=seed, tol=1e-4)
            m.fit(Z)
            means, cov, A, pi, backend = m.means_, np.array([np.diag(c) for c in m.covars_]), m.transmat_, m.startprob_, "hmm"
        except ImportError:  # pragma: no cover
            from sklearn.mixture import GaussianMixture
            g = GaussianMixture(n_states, covariance_type="diag", random_state=seed).fit(Z)
            means, cov, backend = g.means_, g.covariances_, "gmm"
            A = np.full((n_states, n_states), 1 / n_states); pi = g.weights_
        order = np.argsort(means[:, REGIME_FEATURES.index("rv_20")])   # by volatility
        A2 = A[np.ix_(order, order)]
        return cls(mu.tolist(), sd.tolist(), means[order].tolist(), cov[order].tolist(), A2.tolist(), pi[order].tolist(),
                   NAMES.get(n_states, [f"s{i}" for i in range(n_states)]), backend=backend)

    def _loglik(self, Z):
        m, c = np.asarray(self.means), np.maximum(np.asarray(self.covars), 1e-6)
        return -0.5 * (((Z[:, None, :] - m[None]) ** 2) / c[None] + np.log(2 * np.pi * c[None])).sum(-1)

    def filtered_proba(self, F: pd.DataFrame) -> pd.DataFrame:
        """Causal forward filter: P(state_t | x_1..x_t)."""
        Z = (F[REGIME_FEATURES].to_numpy(float) - np.asarray(self.mean)) / np.asarray(self.scale)
        ll = self._loglik(Z)
        A, a = np.asarray(self.transmat), np.asarray(self.startprob)
        out = np.zeros_like(ll)
        prev = None
        for t in range(len(Z)):
            prior = a if prev is None else prev @ A
            w = np.log(np.maximum(prior, 1e-300)) + ll[t]
            w = np.exp(w - w.max()); w /= w.sum()
            out[t] = prev = w
        return pd.DataFrame(out, index=F.index, columns=self.names)

    def risk_multiplier(self, F: pd.DataFrame) -> pd.Series:
        P = self.filtered_proba(F)
        m = np.array([min(1.0, float(self.mult.get(n, 1.0))) for n in self.names])
        return pd.Series(np.clip(P.to_numpy() @ m, self.floor, 1.0), index=F.index, name="regime_mult")

    def save(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "regime.json").write_text(json.dumps(self.__dict__))

    @classmethod
    def load(cls, d: Path) -> "RegimeModel":
        return cls(**json.loads((d / "regime.json").read_text()))


def regime_card():
    from atlas.ai.models.quant.modelcard import ModelCard
    return ModelCard("Market regime detector", "regime",
                     "Classify the market as calm / normal / stressed and scale the risk budget DOWN in riskier regimes.",
                     "Multiply sleeve risk budgets by a factor in [0.25, 1] before vol-target sizing (paper).",
                     "Raising risk above policy, predicting returns, timing entries.",
                     "Daily index closes + universe breadth, point-in-time.", REGIME_FEATURES,
                     ["States are unsupervised and may be unstable across refits", "Lags turning points (filter only)"],
                     ["False calm regime -> no extra reduction (policy limits still apply)"],
                     authority="scale-down only (multiplier <= 1)")
