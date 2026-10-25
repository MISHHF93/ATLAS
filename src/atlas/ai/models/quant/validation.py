"""Validation integrity (AFML ch.7/12; Bailey, Borwein, López de Prado & Zhu 2014).

* ``purged_kfold_t1`` / ``cpcv``: purged + embargoed K-fold and Combinatorial Purged CV driven by
  per-sample label END times (t1), e.g. from triple-barrier labels. CPCV yields phi = C(N,k)*k/N
  out-of-sample backtest paths instead of one walk-forward path.
* ``pbo_cscv``: Probability of Backtest Overfitting via Combinatorially Symmetric CV.
* ``TrialLog``: append-only JSONL register of EVERY trial (incl. hyperparameters such as barrier
  widths). DSR is deflated by the FULL trial count; undercounting is the main way DSR lies.
* ``validation_report``: PSR / DSR / PBO bundle stored in model metrics; registry promotion and the
  autonomy evaluator both require DSR > 0.95 (and PBO < 0.5 when present).
"""
from __future__ import annotations

import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from atlas.ai.models.quant.metrics import deflated_sharpe, probabilistic_sharpe

DSR_THRESHOLD = 0.95


def _as_ns(a) -> np.ndarray:
    return np.asarray(a).astype("datetime64[ns]").astype(np.int64) if np.asarray(a).dtype.kind == "M" else np.asarray(a, np.int64)


def _purge(train: np.ndarray, t0: np.ndarray, t1: np.ndarray, test_blocks: list[np.ndarray], embargo_ns: int) -> np.ndarray:
    keep = np.ones(len(train), bool)
    for blk in test_blocks:
        lo, hi = t0[blk].min(), t1[blk].max()
        # drop train samples whose [t0, t1] overlaps [lo, hi + embargo]
        keep &= ~((t0[train] <= hi + embargo_ns) & (t1[train] >= lo))
    return train[keep]


def _blocks(n_obs: int, n_groups: int) -> list[np.ndarray]:
    return [b for b in np.array_split(np.arange(n_obs), n_groups) if len(b)]


def purged_kfold_t1(t0, t1, n_splits: int = 5, embargo_pct: float = 0.01):
    """Samples must be sorted by t0. Yields (train_idx, test_idx)."""
    a0, a1 = _as_ns(t0), _as_ns(t1)
    if np.any(a1 < a0):
        raise ValueError("t1 must be >= t0")
    emb = int((a0.max() - a0.min()) * embargo_pct)
    idx = np.arange(len(a0))
    for blk in _blocks(len(a0), n_splits):
        yield _purge(np.setdiff1d(idx, blk), a0, a1, [blk], emb), blk


def cpcv(t0, t1, n_groups: int = 6, k_test: int = 2, embargo_pct: float = 0.01):
    """Combinatorial Purged CV. Yields (train_idx, test_idx, test_group_ids)."""
    a0, a1 = _as_ns(t0), _as_ns(t1)
    emb = int((a0.max() - a0.min()) * embargo_pct)
    groups = _blocks(len(a0), n_groups)
    idx = np.arange(len(a0))
    for combo in itertools.combinations(range(len(groups)), k_test):
        test_blocks = [groups[g] for g in combo]
        test = np.concatenate(test_blocks)
        yield _purge(np.setdiff1d(idx, test), a0, a1, test_blocks, emb), test, combo


def cpcv_paths(n_groups: int, k_test: int) -> int:
    return math.comb(n_groups, k_test) * k_test // n_groups


def assemble_paths(oos_by_split: dict[tuple, dict[int, np.ndarray]], n_groups: int, k_test: int) -> list[np.ndarray]:
    """oos_by_split[combo][group] = OOS returns for that group from that split. Each group appears in
    phi splits; path j uses the j-th occurrence of every group -> phi full-length OOS paths."""
    phi = cpcv_paths(n_groups, k_test)
    occ: dict[int, list[np.ndarray]] = {g: [] for g in range(n_groups)}
    for combo in sorted(oos_by_split):
        for g, r in oos_by_split[combo].items():
            occ[g].append(np.asarray(r, float))
    return [np.concatenate([occ[g][j] for g in range(n_groups)]) for j in range(phi)]


def pbo_cscv(perf: np.ndarray, n_blocks: int = 16, metric=None) -> dict:
    """perf: T x N matrix of per-period returns for N strategy configurations (trials).
    Splits rows into S blocks; for every half/half combination picks the best IS config and records
    its OOS relative rank. PBO = P(logit(rank) <= 0) i.e. best-IS config is below median OOS."""
    M = np.asarray(perf, float)
    T, N = M.shape
    if N < 2:
        raise ValueError("PBO needs >= 2 configurations")
    S = n_blocks - (n_blocks % 2)
    metric = metric or (lambda x: x.mean(0) / (x.std(0, ddof=1) + 1e-12))
    blocks = np.array_split(np.arange(T), S)
    logits, degr = [], []
    for c in itertools.combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[i] for i in c])
        oos_idx = np.concatenate([blocks[i] for i in range(S) if i not in c])
        is_p, oos_p = metric(M[is_idx]), metric(M[oos_idx])
        best = int(np.argmax(is_p))
        rank = (oos_p < oos_p[best]).sum() + 0.5 * ((oos_p == oos_p[best]).sum() - 1) + 1  # 1..N
        w = rank / (N + 1)
        logits.append(math.log(w / (1 - w)))
        degr.append((float(is_p[best]), float(oos_p[best])))
    lg = np.array(logits)
    return {"pbo": float((lg <= 0).mean()), "n_combinations": len(lg), "logit_median": float(np.median(lg)),
            "is_oos_best": degr[:5], "n_configs": N, "n_blocks": S}


class TrialLog:
    """Append-only trial register (one JSON object per line). Never rewritten or truncated."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, family: str, params: dict, sr_per_period: float, n_obs: int, note: str = "") -> dict:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "family": family, "params": params,
               "sr": float(sr_per_period), "n_obs": int(n_obs), "note": note}
        with self.path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def records(self, family: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        out = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        return [r for r in out if family is None or r["family"] == family]

    def srs(self, family: str | None = None) -> list[float]:
        return [r["sr"] for r in self.records(family)]

    def count(self, family: str | None = None) -> int:
        return len(self.records(family))


def validation_report(returns, trial_srs: list[float], perf_matrix=None, cpcv_path_srs: list[float] | None = None) -> dict:
    """Bundle stored as metrics['validation']; consumed by registry gates + autonomy evaluator."""
    r = np.asarray(returns, float)
    trials = list(trial_srs)
    d = deflated_sharpe(r, trials if len(trials) >= 2 else trials + [0.0, 0.0])
    out = {"psr": probabilistic_sharpe(r, 0.0), "dsr": d["dsr"], "n_trials": max(len(trials), 1),
           "sr_per_period": d["sr_per_period"], "sr0": d["sr0_expected_max_per_period"], "dsr_threshold": DSR_THRESHOLD}
    if perf_matrix is not None and np.asarray(perf_matrix).shape[1] >= 2 and np.asarray(perf_matrix).shape[0] >= 64:
        T = np.asarray(perf_matrix).shape[0]
        out["pbo"] = pbo_cscv(perf_matrix, n_blocks=min(16, max(4, (T // 16) // 2 * 2)))["pbo"]
    if cpcv_path_srs:
        p = np.asarray(cpcv_path_srs, float)
        out["cpcv"] = {"n_paths": len(p), "sr_mean": float(p.mean()), "sr_std": float(p.std(ddof=1)) if len(p) > 1 else 0.0,
                       "frac_paths_positive": float((p > 0).mean())}
    out["passes"] = bool(out["dsr"] > DSR_THRESHOLD and out.get("pbo", 0.0) < 0.5)
    return out
