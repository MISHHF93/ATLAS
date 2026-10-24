"""Vol-target position sizing with regime scaling and policy caps (TRD §13 stage 4).
qty = (sleeve_budget x target_vol x regime_mult x llm_mult) / (forecast_vol x price x fx), then
min(... Kelly cap, max_position_pct x bot_capital, max_position_notional). Every multiplier is
clipped to <= 1, so models can only REDUCE size relative to the vol-target baseline."""
from __future__ import annotations


def vol_target_qty(sleeve_budget_base: float, target_vol: float, forecast_vol: float, price: float, fx: float,
                   bot_capital: float, max_position_pct: float, max_notional: float, regime_mult: float = 1.0,
                   screener_mult: float = 1.0, p_hit: float | None = None, payoff_ratio: float = 1.0,
                   kelly_fraction: float = 0.25, vol_floor: float = 0.05) -> dict:
    if min(price, fx) <= 0 or sleeve_budget_base <= 0:
        return {"qty": 0.0, "reason": "invalid inputs"}
    rm, sm = min(1.0, max(0.0, regime_mult)), min(1.0, max(0.0, screener_mult))
    fv = max(vol_floor, forecast_vol)
    base_notional = sleeve_budget_base * min(1.0, target_vol / fv)
    caps = {"vol_target": base_notional, "position_pct": bot_capital * max_position_pct / 100, "notional": max_notional}
    if p_hit is not None:
        f = max(0.0, p_hit - (1 - p_hit) / max(payoff_ratio, 1e-9)) * kelly_fraction
        caps["kelly"] = f * bot_capital
    notional = min(caps.values()) * rm * sm
    qty = notional / (price * fx)
    return {"qty": qty, "notional_base": notional, "caps": caps, "binding": min(caps, key=caps.get),
            "regime_mult": rm, "screener_mult": sm, "forecast_vol": fv}


def contracts_for_risk(instrument_id: str, risk_usd: float, entry: float, stop: float) -> dict:
    """Whole futures contracts for a fixed dollar risk, using the single contract-spec source (feeds.contracts).
    Per-contract risk = |entry - stop| x multiplier + round-trip cost assumption. Rounds DOWN; 0 means do not trade."""
    from atlas.feeds.contracts import contract_for
    spec = contract_for(instrument_id)
    if spec is None:
        return {"contracts": 0, "reason": "no_contract_spec"}
    dist = abs(entry - stop)
    if not dist > 0 or not risk_usd > 0:
        return {"contracts": 0, "reason": "invalid inputs"}
    per = dist * spec.multiplier + spec.cost_per_contract_rt_usd
    n = int(risk_usd // per)
    return {"contracts": n, "risk_per_contract_usd": per, "risk_used_usd": n * per, "multiplier": spec.multiplier,
            "cost_per_contract_rt_usd": spec.cost_per_contract_rt_usd, "spec_verified": spec.verified,
            "reason": "" if n else "one contract exceeds the risk budget"}
