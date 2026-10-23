"""Capital-aware compounding inside a risk budget (shrink-only overlay on top of the pipeline's sizing).

* Deployable capital = the risk engine's bot capital = min(bot equity, allocation cap). Realized profits stay in the
  bot and are reinvested automatically up to the cap; above it they are NOT (policy `profits_raise_cap: false`), and
  money is never pulled from the bank or the payments module.
* Volatility targeting: allowed gross exposure scales with target_vol / realized_vol (capped at 1, no leverage).
* Fractional Kelly cap: gross exposure <= kelly_fraction * mu / sigma^2 from the bot's own daily returns; with too
  little history a neutral "warming up" budget applies. Estimated edge <= 0 => no new risk is added.
* The overlay can only SHRINK buy orders (factor in [0, 1]); sells (risk-reducing) pass unchanged."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from atlas.autopilot.config import AutopilotCfg


def daily_returns(equity_points: list) -> pd.Series:
    if not equity_points or len(equity_points) < 3:
        return pd.Series(dtype=float)
    s = pd.Series([float(v) for _, v in equity_points], index=pd.to_datetime([t for t, _ in equity_points], utc=True, format="ISO8601"))
    d = s.groupby(s.index.tz_convert("America/Toronto").date).last()
    return d.pct_change().dropna()


def vol_target_scale(r: pd.Series, target_annual_pct: float, ppy: int = 252) -> tuple[float, float | None]:
    if len(r) < 5:
        return 1.0, None
    vol = float(r.std(ddof=1) * math.sqrt(ppy) * 100)
    return (min(1.0, target_annual_pct / vol) if vol > 0 else 1.0), vol


def fractional_kelly(r: pd.Series, fraction: float, min_obs: int, ppy: int = 252) -> tuple[float | None, dict]:
    if len(r) < min_obs:
        return None, {"obs": len(r), "reason": f"warming up: {len(r)} of {min_obs} daily returns"}
    mu, var = float(r.mean() * ppy), float(r.var(ddof=1) * ppy)
    if var <= 0:
        return None, {"obs": len(r), "reason": "zero variance"}
    full = mu / var
    return max(0.0, min(1.0, fraction * full)), {"obs": len(r), "mu_annual": mu, "sigma_annual": math.sqrt(var), "full_kelly": full}


def risk_budget(svc, cfg: AutopilotCfg, equity_points: list) -> dict[str, Any]:
    s = svc.broker.snapshot()
    cap = svc.cfg.risk.capital.allocation_cap_pct / 100 * s.total_account_equity_base
    deployable = svc.engine.bot_capital(s)
    r = daily_returns(equity_points)
    vscale, vol = vol_target_scale(r, cfg.vol_target_annual_pct)
    kf, kinfo = fractional_kelly(r, cfg.kelly_fraction, cfg.kelly_min_obs)
    kcap = cfg.warmup_exposure if kf is None else kf
    frac = max(0.0, min(1.0, vscale, kcap))
    gross = float(s.gross_exposure_base)
    allowed = frac * deployable
    start_cap = float(svc.store.get("autopilot.capital_at_start") or deployable)
    return {"allocation_cap": cap, "bot_equity": s.bot_equity, "deployable_capital": deployable,
            "reinvested_since_start": deployable - start_cap, "above_cap_not_reinvested": max(0.0, s.bot_equity - cap),
            "realized_vol_annual_pct": vol, "vol_target_annual_pct": cfg.vol_target_annual_pct, "vol_scale": vscale,
            "kelly_fraction": cfg.kelly_fraction, "kelly_cap": kf, "kelly": kinfo, "exposure_fraction": frac,
            "allowed_gross": allowed, "current_gross": gross, "headroom": max(0.0, allowed - gross),
            "note": "shrink-only: limits new buys; never adds leverage, never moves money from payments"}


def overlay_factor(intent, budget: dict) -> float:
    """Factor in [0, 1] applied to a child order's quantity. Sells are never shrunk."""
    if intent.side != "buy":
        return 1.0
    value = intent.qty * intent.reference_price * (intent.fx_rate_to_base or 1.0)
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, budget["headroom"] / value))
