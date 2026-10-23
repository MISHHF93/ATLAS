"""Founder (owner's own capital) track: rulebook derived from the signed founder risk policy.

The prop-competition rulebook keeps its configurable 4% daily-loss rule (published prop rules).
The founder's own capital runs under the owner's policy: a **2% daily loss Safe stop**, 4% weekly,
10% max drawdown (paper profile), loaded from ``config/founder/risk_policy.yaml`` (sha256-pinned).
If the policy is missing or fails its pin, the built-in defaults below are used: they are the same
numbers, so the founder track never loosens silently. Paper only; ``execution_permission`` stays "none".
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from atlas.control.rules import TradingRuleBook

FOUNDER_DEFAULT_DAILY_LOSS_FRACTION = Decimal("0.02")
FOUNDER_DEFAULT_MAX_DRAWDOWN_FRACTION = Decimal("0.10")
FOUNDER_RULEBOOK_ID = "founder-capital-2026-q4:v1"


def founder_policy_dir() -> Path:
    """`ATLAS_FOUNDER_CONFIG_DIR` (name only; defaults to repo `config/founder`)."""
    env = os.environ.get("ATLAS_FOUNDER_CONFIG_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "config" / "founder"


def _policy_limits(config_dir: Path) -> tuple[Decimal, Decimal, str, float | None]:
    try:
        from atlas.control.policy import load_all

        cfg = load_all(config_dir)
        ll = cfg.risk.loss_limits
        hold = cfg.risk.position_limits.max_holding_seconds
        return (Decimal(str(ll.daily_pct)) / 100, Decimal(str(ll.max_drawdown_pct)) / 100,
                f"config/founder/risk_policy.yaml@v{cfg.risk.version}", float(hold) if hold else None)
    except Exception:  # noqa: BLE001  fail closed to the owner's documented defaults
        return FOUNDER_DEFAULT_DAILY_LOSS_FRACTION, FOUNDER_DEFAULT_MAX_DRAWDOWN_FRACTION, "builtin-founder-defaults", None


def build_founder_rulebook(config_dir: str | Path | None = None) -> TradingRuleBook:
    # Holding limit comes ONLY from the pinned policy (owner decision 2026-10-23: 86400 s). If the policy is
    # missing or fails its pin it stays None, so the control plane default-denies entries (fail closed).
    daily, mdd, ref, hold = _policy_limits(Path(config_dir) if config_dir else founder_policy_dir())
    # The founder track may only be TIGHTER than the owner's defaults, never looser.
    daily = min(daily, FOUNDER_DEFAULT_DAILY_LOSS_FRACTION)
    mdd = min(mdd, FOUNDER_DEFAULT_MAX_DRAWDOWN_FRACTION)
    return TradingRuleBook(
        rulebook_id=FOUNDER_RULEBOOK_ID,
        revision="1.0.0",
        track="open_market",
        evidence_ref=f"docs/lola-port-plan.md#founder-capital-track ({ref})",
        max_per_trade_risk_fraction=Decimal("0.005"),
        required_stop_kind="either",
        min_stop_distance_bps=Decimal("30"),
        max_daily_loss_fraction=daily,
        drawdown_mode="static",
        max_drawdown_fraction=mdd,
        max_position_notional_usd=Decimal("40000"),
        max_gross_leverage=Decimal("1.0"),
        max_correlated_exposure_fraction=Decimal("0.50"),
        max_sector_exposure_fraction=Decimal("0.40"),
        require_verified_quality=True,
        require_commercial_license=True,
        max_data_age_seconds=3600.0,
        allowed_sessions=frozenset({"regular_open", "continuous_24_7"}),
        max_holding_seconds=hold,
        forbid_funding_window_entry=True,
    )


__all__ = ["FOUNDER_DEFAULT_DAILY_LOSS_FRACTION", "FOUNDER_RULEBOOK_ID", "build_founder_rulebook", "founder_policy_dir"]
