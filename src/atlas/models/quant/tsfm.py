"""Time-series foundation models (TSFM) as ADVISORY recipe components. Offline only.

Providers (optional, loaded from the local Hugging Face cache with HF_HUB_OFFLINE=1; never downloaded at run time):
  chronos-bolt  amazon/chronos-bolt-{tiny,mini,small,base}  (chronos-forecasting package; CPU OK for tiny/mini)
  timesfm       google/timesfm-2.5-200m-pytorch              (timesfm package)
  moirai        Salesforce/moirai-2.0-R-small                (uni2ts package)
  lag-llama     time-series-foundation-models/Lag-Llama      (lag-llama repo)
  patchtst/tft  trained per fold (neuralforecast) when installed
Fallback (always available, no downloads): `patch-linear`, a PatchTST-inspired linear head (ridge on normalised return
patches) trained inside each walk-forward fold.

Safety: forecasts are FEATURES (a score per symbol). They can only rank/scale down via the recipe and the pipeline's
shrink-only stages; they never create orders. Every call has a timeout; on timeout or error the component abstains
(score 0 => no position from this component) and the event is counted for drift/health monitoring.
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import os
import time
from dataclasses import dataclass, field

import numpy as np

from atlas.models.quant.modelcard import ModelCard


@dataclass
class ForecastResult:
    scores: np.ndarray           # expected next-horizon return (or sign-preserving score) per series
    provider: str
    elapsed_s: float
    abstained: bool = False
    note: str = ""


class Provider:
    name = "base"
    hf_id: str | None = None
    package: str | None = None

    def available(self) -> tuple[bool, str]:
        if self.package and importlib.util.find_spec(self.package) is None:
            return False, f"package {self.package!r} not installed"
        if self.hf_id and not _hf_cached(self.hf_id):
            return False, f"{self.hf_id} not in local HF cache (offline mode never downloads)"
        return True, "ok"

    def fit(self, train_ctx: np.ndarray, horizon: int) -> None:   # zero-shot providers ignore this
        pass

    def predict(self, ctx: np.ndarray, horizon: int) -> np.ndarray:
        raise NotImplementedError


def _hf_cached(repo: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(repo, "config.json"), str)
    except Exception:  # noqa: BLE001
        return False


class ChronosBolt(Provider):
    name, package = "chronos-bolt", "chronos"

    def __init__(self, size: str = "tiny"):
        self.hf_id = f"amazon/chronos-bolt-{size}"
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            import torch
            from chronos import BaseChronosPipeline
            torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
            self._pipe = BaseChronosPipeline.from_pretrained(self.hf_id, device_map="cpu", torch_dtype=torch.float32)
        return self._pipe

    def predict(self, ctx: np.ndarray, horizon: int) -> np.ndarray:
        import torch
        pipe = self._load()
        # forecast PRICE level (normalised to 1 at the last obs) then convert to an expected return
        lvl = np.exp(np.cumsum(np.nan_to_num(ctx), axis=1))
        lvl = lvl / lvl[:, -1:]
        q, mean = pipe.predict_quantiles(torch.tensor(lvl, dtype=torch.float32), prediction_length=horizon,
                                         quantile_levels=[0.1, 0.5, 0.9])
        med = q[:, -1, 1].numpy()
        return np.log(np.maximum(med, 1e-6))


class TimesFM(Provider):
    name, package, hf_id = "timesfm", "timesfm", "google/timesfm-2.5-200m-pytorch"


class Moirai(Provider):
    name, package, hf_id = "moirai", "uni2ts", "Salesforce/moirai-2.0-R-small"


class LagLlama(Provider):
    name, package, hf_id = "lag-llama", "lag_llama", "time-series-foundation-models/Lag-Llama"


class PatchTST(Provider):
    name, package = "patchtst", "neuralforecast"


class PatchLinear(Provider):
    """PatchTST-inspired linear fallback: per-patch means of normalised returns -> ridge -> next-horizon return."""
    name = "patch-linear"

    def __init__(self, context: int = 64, patch: int = 8, alpha: float = 10.0):
        self.context, self.patch, self.alpha, self.w = context, patch, alpha, None

    def _X(self, ctx: np.ndarray) -> np.ndarray:
        c = np.nan_to_num(ctx[:, -self.context:])
        sd = c.std(1, keepdims=True) + 1e-9
        z = c / sd
        P = z.reshape(len(z), -1, self.patch).mean(2)
        return np.column_stack([np.ones(len(P)), P])

    def fit(self, train_ctx: np.ndarray, horizon: int) -> None:
        """train_ctx: (n_series, T) daily log returns. Builds rolling samples inside the training fold only."""
        X, y = [], []
        n, T = train_ctx.shape
        for t in range(self.context, T - horizon, 3):
            X.append(self._X(train_ctx[:, t - self.context:t]))
            y.append(np.nan_to_num(train_ctx[:, t:t + horizon]).sum(1))
        if not X:
            self.w = None
            return
        X, y = np.vstack(X), np.concatenate(y)
        A = X.T @ X + self.alpha * np.eye(X.shape[1]); A[0, 0] -= self.alpha
        self.w = np.linalg.solve(A, X.T @ y)

    def predict(self, ctx: np.ndarray, horizon: int) -> np.ndarray:
        if self.w is None or ctx.shape[1] < self.context:
            return np.zeros(len(ctx))
        return self._X(ctx) @ self.w


REGISTRY = {"chronos-bolt": ChronosBolt, "timesfm": TimesFM, "moirai": Moirai, "lag-llama": LagLlama, "patchtst": PatchTST,
            "patch-linear": PatchLinear}


@dataclass
class TSFMComponent:
    """Wraps a provider with a timeout, fallback, and simple drift/health counters."""
    preferred: str = "chronos-bolt"
    timeout_s: float = 20.0
    horizon: int = 5
    stats: dict = field(default_factory=lambda: {"calls": 0, "timeouts": 0, "errors": 0, "fallbacks": 0, "abs_err": []})

    def __post_init__(self):
        ok, why = REGISTRY[self.preferred]().available() if self.preferred in REGISTRY else (False, "unknown provider")
        self.provider: Provider = REGISTRY[self.preferred]() if ok else PatchLinear()
        self.status = "ok" if ok else f"fallback to patch-linear: {why}"
        self._pool = cf.ThreadPoolExecutor(max_workers=1)

    @property
    def name(self) -> str:
        return self.provider.name

    def fit(self, train_ctx: np.ndarray) -> None:
        self.provider.fit(train_ctx, self.horizon)

    def forecast(self, ctx: np.ndarray) -> ForecastResult:
        self.stats["calls"] += 1
        t0 = time.monotonic()
        fut = self._pool.submit(self.provider.predict, ctx, self.horizon)
        try:
            s = np.asarray(fut.result(timeout=self.timeout_s), float)
            return ForecastResult(np.nan_to_num(s), self.provider.name, time.monotonic() - t0)
        except cf.TimeoutError:
            self.stats["timeouts"] += 1
            return ForecastResult(np.zeros(len(ctx)), self.provider.name, time.monotonic() - t0, True, "timeout: abstain")
        except Exception as e:  # noqa: BLE001 - fail closed (abstain)
            self.stats["errors"] += 1
            return ForecastResult(np.zeros(len(ctx)), self.provider.name, time.monotonic() - t0, True, f"error: {e!r}"[:200])

    def record_outcome(self, predicted: np.ndarray, realised: np.ndarray) -> None:
        self.stats["abs_err"] = (self.stats["abs_err"] + list(np.abs(np.asarray(predicted) - np.asarray(realised))))[-500:]

    def drift(self, reference_mae: float | None, ratio: float = 1.5) -> dict:
        e = self.stats["abs_err"]
        mae = float(np.mean(e)) if e else None
        bad = self.stats["timeouts"] + self.stats["errors"]
        return {"mae_recent": mae, "reference_mae": reference_mae, "drift": bool(mae and reference_mae and mae > ratio * reference_mae),
                "failure_rate": bad / max(1, self.stats["calls"])}


def tsfm_card(provider: str) -> ModelCard:
    return ModelCard(
        name=f"TSFM forecaster ({provider})", kind="tsfm_forecast",
        purpose="Zero-shot / fold-trained forecast of next-5-day return used as ONE ranking feature in a recipe.",
        intended_use="Paper research and paper autopilot ranking. Advisory feature only; shrink/drop via the pipeline.",
        out_of_scope="Creating orders, sizing up beyond the risk budget, live trading, intraday execution.",
        data="Daily log returns (point-in-time, context window only). Pretrained corpora per the upstream model card.",
        features=["last 64-512 daily log returns per symbol"],
        limitations=["Foundation models are trained on generic series; financial returns are near-noise, so expected edge is small.",
                     "CPU inference: tiny/mini sizes only; larger models need a GPU.",
                     "Synthetic-data evaluation does not prove edge."],
        risks=["Spurious confidence on regime breaks", "Upstream licence terms (check model card)", "Silent degradation: monitored by MAE drift + failure rate"],
        extra={"timeout_s": 20, "fallback": "patch-linear (in-fold ridge)", "offline": "HF_HUB_OFFLINE=1"})
