"""Pydantic schemas for risk_policy.yaml, brokers.yaml, schedule.yaml.

Safety-critical fields are strictly typed and range-checked; descriptive
fields are allowed through (extra="allow") so the spec files load as-is.
All models are frozen: the policy is immutable once loaded.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Pct = float


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- risk policy
class ModeCfg(_Frozen):
    default: Literal["paper"]  # live is not a valid value in this build
    live_requires: list[str] = []


class LimitProfile(_Strict):
    name: str
    daily_pct: Pct = Field(gt=0, le=100)
    weekly_pct: Pct = Field(gt=0, le=100)
    max_drawdown_pct: Pct = Field(gt=0, le=100)
    max_position_pct_bot_capital: Pct = Field(gt=0, le=100)
    live: bool = False


class AutonomyCfg(_Frozen):
    level: int = Field(ge=1, le=4)
    approval_required_below_level: int = Field(ge=1, le=4)
    approval_ttl_seconds: int = Field(gt=0, le=3600)
    limit_profiles: dict[int, LimitProfile] = {}

    @model_validator(mode="after")
    def _profiles(self) -> "AutonomyCfg":
        lp = self.limit_profiles
        if lp:
            if set(lp) != {1, 2, 3, 4}:
                raise ValueError("autonomy.limit_profiles must define levels 1-4")
            if lp[1].live:
                raise ValueError("level 1 profile must be paper (live: false)")
            l2 = lp[2]
            if l2.daily_pct > 1.0 or l2.max_drawdown_pct > 8.0:
                raise ValueError("level 2 (small live) profile must be <= 1% daily loss and <= 8% max drawdown (BRD)")
            for a, b in ((2, 3), (3, 4)):
                if lp[b].daily_pct > lp[a].daily_pct or lp[b].max_drawdown_pct > lp[a].max_drawdown_pct:
                    raise ValueError(f"level {b} profile may not be looser than level {a} on loss limits")
        return self

    @property
    def profile(self) -> "LimitProfile | None":
        return self.limit_profiles.get(self.level)


class CapitalCfg(_Frozen):
    allocation_cap_pct: Pct = Field(gt=0, le=100)
    allocation_cap_hard_ceiling_pct: Pct = Field(gt=0, le=100)
    profits_raise_cap: bool

    @model_validator(mode="after")
    def _cap_below_ceiling(self) -> "CapitalCfg":
        if self.allocation_cap_pct > self.allocation_cap_hard_ceiling_pct:
            raise ValueError("allocation_cap_pct exceeds allocation_cap_hard_ceiling_pct")
        if self.profits_raise_cap:
            raise ValueError("profits_raise_cap must be false (cap rises only via autonomy ladder)")
        return self


class SleeveCfg(_Frozen):
    target_pct: Pct = Field(ge=0, le=100)
    min_pct: Pct = Field(default=0, ge=0, le=100)
    max_pct: Pct = Field(ge=0, le=100)
    instruments: list[str] = []
    locked: bool = False

    @model_validator(mode="after")
    def _bands(self) -> "SleeveCfg":
        if not (self.min_pct <= self.target_pct <= self.max_pct):
            raise ValueError(f"sleeve bands invalid: min {self.min_pct} <= target {self.target_pct} <= max {self.max_pct}")
        return self


class LossLimitsCfg(_Frozen):
    daily_pct: Pct = Field(gt=0, le=100)
    weekly_pct: Pct = Field(gt=0, le=100)
    max_drawdown_pct: Pct = Field(gt=0, le=100)
    per_strategy_max_drawdown_pct: Pct = Field(gt=0, le=100)

    @model_validator(mode="after")
    def _ordering(self) -> "LossLimitsCfg":
        if not (self.daily_pct <= self.weekly_pct <= self.max_drawdown_pct):
            raise ValueError("loss limits must satisfy daily <= weekly <= max_drawdown")
        return self


class PositionLimitsCfg(_Frozen):
    max_position_pct_bot_capital: Pct = Field(gt=0, le=100)
    max_position_notional_base: float = Field(gt=0)
    max_gross_exposure_pct: Pct = Field(gt=0, le=100)  # >100 would be leverage
    max_net_fx_exposure_pct: Pct = Field(ge=0, le=100)
    max_single_currency_pct: Pct = Field(ge=0, le=100)
    max_sector_pct: Pct = Field(ge=0, le=100)
    max_orders_per_minute: int = Field(gt=0, le=600)
    max_open_orders: int = Field(gt=0, le=1000)
    price_collar_pct: Pct = Field(gt=0, le=20)


class MlFilterCfg(_Frozen):
    enabled: bool = True
    min_p_hit: float = Field(default=0.55, ge=0.5, le=1)
    require_exp_return_above_cost: bool = True
    fallback: Literal["rules_only_half_size", "halt"] = "rules_only_half_size"


class LlmScreenerCfg(_Frozen):
    enabled: bool = True
    provider: Literal["offline_stub", "none", "finbert_local", "http_llm"] = "offline_stub"  # real providers need explicit opt-in (env)
    allowed_actions: list[Literal["none", "downsize", "veto"]] = ["none", "downsize", "veto"]
    allowed_downsize_mults: list[float] = [0.5, 0.25]
    max_size_mult: float = Field(default=1.0, gt=0, le=1.0)   # can NEVER upsize
    timeout_s: float = Field(default=5, gt=0, le=60)
    on_timeout: Literal["veto", "downsize", "pass", "safe_default"] = "veto"  # safe_default = TRD (downsize)
    on_error: Literal["veto", "downsize", "pass", "safe_default"] = "veto"

    @model_validator(mode="after")
    def _mults(self) -> "LlmScreenerCfg":
        if any(not (0 < m < 1) for m in self.allowed_downsize_mults):
            raise ValueError("downsize multipliers must be in (0, 1)")
        return self


class ModelPromotionCfg(_Frozen):
    min_shadow_weeks: int = Field(default=4, ge=4)   # BRD/TRD: >= 4 weeks shadow
    owner_signoff_at_level_ge: int = Field(default=3, ge=1, le=4)
    min_lift_bps: float = 0
    max_brier_worsening: float = Field(default=0.0, ge=0)
    max_drawdown_pct: float = Field(default=10, gt=0, le=100)
    min_dsr: float = Field(default=0.95, ge=0.95, lt=1)   # deflated Sharpe over ALL logged trials
    max_pbo: float = Field(default=0.5, gt=0, le=0.5)     # probability of backtest overfitting (CSCV)


class AiControlsCfg(_Frozen):
    ai_can_approve_orders: Literal[False]
    ai_can_change_policy: Literal[False]
    ml_filter: MlFilterCfg = MlFilterCfg()
    llm_screener: LlmScreenerCfg = LlmScreenerCfg()
    model_promotion: ModelPromotionCfg = ModelPromotionCfg()


class KillSwitchCfg(_Frozen):
    enabled: Literal[True]
    channels: list[str]
    reset_requires: list[str]


class WatchdogCfg(_Frozen):
    heartbeat_interval_s: float = Field(gt=0, le=60)
    missed_beats_to_halt: int = Field(ge=1, le=20)
    deadman_timeout_s: float = Field(gt=0)
    fail_mode: Literal["closed"]


class RebalanceCfg(_Frozen):
    drift_band_pp: Pct = Field(gt=0, le=50)
    schedule: Literal["weekly", "daily", "monthly"] = "weekly"
    schedule_time_et: str = "Mon 15:30"
    max_cost_bps: float = Field(gt=0, le=200)
    min_trade_value_base: float = Field(ge=0)


class RiskPolicy(_Frozen):
    version: int
    base_currency: str
    owner: str
    mode: ModeCfg
    autonomy: AutonomyCfg
    capital: CapitalCfg
    sleeves: dict[str, SleeveCfg]
    loss_limits: LossLimitsCfg
    position_limits: PositionLimitsCfg
    ai_controls: AiControlsCfg
    kill_switch: KillSwitchCfg
    watchdog: WatchdogCfg
    rebalance: RebalanceCfg

    @field_validator("base_currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        if len(v) != 3 or not v.isupper():
            raise ValueError("base_currency must be ISO-4217 uppercase")
        return v

    @model_validator(mode="after")
    def _sleeves(self) -> "RiskPolicy":
        for req in ("core", "active", "high_risk"):
            if req not in self.sleeves:
                raise ValueError(f"required sleeve missing: {req}")
        total = sum(s.target_pct for s in self.sleeves.values())
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"sleeve target_pct must sum to 100, got {total}")
        d = self.sleeves.get("derivatives")
        if d is not None and not d.locked:
            raise ValueError("derivatives sleeve must be locked in this build (Phase 5)")
        if self.autonomy.level != 1:
            raise ValueError("this paper-only build requires autonomy.level == 1")
        return self


# ---------------------------------------------------------------- brokers
class PlatformCfg(_Frozen):
    enabled: bool
    mode: Literal["paper"]  # 'live' rejected at schema level in this build
    asset_classes: list[str]
    account_currency: str
    permissions: dict[str, Any] = {}

    @model_validator(mode="after")
    def _no_money_movement_or_leverage(self) -> "PlatformCfg":
        p = self.permissions
        for k in ("withdrawals", "withdraw", "transfer", "margin"):
            if p.get(k) is True:
                raise ValueError(f"permission {k!r} must not be true")
        lev = p.get("leverage_max")
        if lev is not None and float(lev) > 1.0:
            raise ValueError("leverage_max must be <= 1.0 (no leverage)")
        return self


class BrokersCfg(_Frozen):
    version: float
    base_currency: str
    default_mode: Literal["paper"]
    platforms: dict[str, PlatformCfg]
    routing: dict[str, Any]


# ---------------------------------------------------------------- schedule
class VenueCfg(_Frozen):
    tz: str
    brokers: list[str] = []
    enabled: bool = True


class IntradayRulesCfg(_Frozen):
    flatten_intraday_strategies_before_close_min: int = Field(ge=0)
    hold_overnight_allowed_sleeves: list[str]


class ScheduleCfg(_Frozen):
    version: float
    owner_timezone: str
    on_calendar_mismatch: Literal["treat_closed"]
    venues: dict[str, VenueCfg]
    intraday_rules: IntradayRulesCfg
