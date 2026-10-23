"""Per-autonomy-level limit profiles. The effective limit is the TIGHTER of the
level profile and the base loss/position limits. Live stays locked in this build
regardless of level: profiles can only tighten the paper limits."""
from __future__ import annotations

from atlas.control.policy.schemas import RiskPolicy


def apply_limit_profile(policy: RiskPolicy) -> RiskPolicy:
    prof = policy.autonomy.profile
    if prof is None:
        return policy
    ll, pl = policy.loss_limits, policy.position_limits
    ll2 = ll.model_copy(update={"daily_pct": min(ll.daily_pct, prof.daily_pct),
                                "weekly_pct": min(ll.weekly_pct, prof.weekly_pct),
                                "max_drawdown_pct": min(ll.max_drawdown_pct, prof.max_drawdown_pct)})
    pl2 = pl.model_copy(update={"max_position_pct_bot_capital": min(pl.max_position_pct_bot_capital,
                                                                    prof.max_position_pct_bot_capital)})
    return policy.model_copy(update={"loss_limits": ll2, "position_limits": pl2})


def autonomy_status(policy: RiskPolicy) -> dict:
    prof = policy.autonomy.profile
    return {"level": policy.autonomy.level, "profile": prof.name if prof else None,
            "profile_wants_live": bool(prof and prof.live), "live_locked": True, "mode": "paper",
            "effective_daily_pct": policy.loss_limits.daily_pct,
            "effective_max_drawdown_pct": policy.loss_limits.max_drawdown_pct}
