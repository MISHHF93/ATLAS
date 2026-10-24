"""Microstructure engine with data-tier gating.

Tiers (what the feed actually holds for an instrument):
  bars   - confirmed OHLCV bars only            -> bar-based estimators
  l1     - bid/ask quotes                       -> quoted spread, quote imbalance
  trades - signed trade prints                  -> VPIN, Kyle's lambda, trade-flow imbalance
  l2     - order-book depth                     -> OFI, book entropy (microstructure.orderbook)
A metric is computed only if its tier is present; otherwise it is returned as gated with the missing tier named.
The ATLAS feed store currently holds bars + last-print quotes (no bid/ask, no signed prints, no depth), so today
only the bar tier is available. Bar estimators are labelled ESTIMATES (Corwin-Schultz 2012 high-low spread;
Amihud 2002 illiquidity; Parkinson 1980 range volatility)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

TIER_METRICS = {
    "bars": ["corwin_schultz_spread_bps", "amihud_illiquidity", "parkinson_vol_ann", "volume_z"],
    "l1": ["quoted_spread_bps", "quote_imbalance"],
    "trades": ["vpin", "kyles_lambda", "trade_flow_imbalance"],
    "l2": ["order_flow_imbalance", "book_entropy"],
}


def detect_tiers(bars, quotes: list[dict] | None = None, has_prints: bool = False, has_depth: bool = False) -> dict[str, bool]:
    q = quotes or []
    return {"bars": bool(bars), "l1": any(("bid" in r and "ask" in r) for r in q), "trades": has_prints, "l2": has_depth}


def corwin_schultz(bars) -> float | None:
    """Mean Corwin-Schultz spread estimate (fraction of price) over consecutive bar pairs; negatives set to 0."""
    k = 3 - 2 * math.sqrt(2)
    s = []
    for a, b in zip(bars, bars[1:]):
        if min(a.low, b.low) <= 0:
            continue
        beta = math.log(a.high / a.low) ** 2 + math.log(b.high / b.low) ** 2
        gamma = math.log(max(a.high, b.high) / min(a.low, b.low)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        s.append(max(0.0, 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))))
    return float(np.mean(s)) if s else None


def bar_metrics(bars, n: int = 200) -> dict[str, Any]:
    w = bars[-n:]
    if len(w) < 20:
        return {"status": "insufficient_bars", "n": len(w)}
    c = np.array([b.close for b in w]); v = np.array([b.volume for b in w])
    r = np.diff(np.log(c))
    dv = c[1:] * v[1:]
    amihud = float(np.mean(np.abs(r[dv > 0]) / dv[dv > 0])) * 1e6 if (dv > 0).any() else None
    hl = np.array([math.log(b.high / b.low) ** 2 for b in w if b.low > 0])
    per_year = 365 * 86400 / w[0].duration
    cs = corwin_schultz(w)
    vz = float((v[-1] - v[:-1].mean()) / v[:-1].std()) if v[:-1].std() > 0 else None
    return {"status": "ok", "n": len(w), "corwin_schultz_spread_bps": None if cs is None else round(cs * 1e4, 3),
            "amihud_illiquidity": None if amihud is None else round(amihud, 6),
            "parkinson_vol_ann": round(float(math.sqrt(hl.mean() / (4 * math.log(2)) * per_year)), 4) if len(hl) else None,
            "volume_z": None if vz is None else round(vz, 3), "kind": "estimate_from_bars"}


def report(inst: str, bars, quotes=None, has_prints: bool = False, has_depth: bool = False) -> dict[str, Any]:
    tiers = detect_tiers(bars, quotes, has_prints, has_depth)
    metrics: list[dict[str, Any]] = []
    bm = bar_metrics(bars) if tiers["bars"] else {}
    for tier, names in TIER_METRICS.items():
        for m in names:
            if not tiers[tier]:
                metrics.append({"metric": m, "tier": tier, "status": "gated", "reason": f"requires {tier} data; feed has none for {inst}"})
            elif tier == "bars":
                metrics.append({"metric": m, "tier": tier, "status": "ok" if bm.get(m) is not None else bm.get("status", "unavailable"),
                                "value": bm.get(m), "kind": "estimate"})
            else:  # pragma: no cover - higher tiers are not stored by the ATLAS feed today
                metrics.append({"metric": m, "tier": tier, "status": "not_wired", "reason": "tier present but adapter not wired"})
    top = max((t for t in ("l2", "trades", "l1", "bars") if tiers[t]), key=list(TIER_METRICS).index, default=None)
    return {"instrument": inst, "tiers": tiers, "highest_tier": top, "metrics": metrics, "bars_used": min(len(bars), 200),
            "execution_permission": "none"}
