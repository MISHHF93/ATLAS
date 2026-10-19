"""Deterministic control-plane trading rules and remaining-room calculators.

Hard boundaries enforced here:
- Only deterministic code evaluates risk, sizing, circuit breakers, and kill switches.
- LLMs may propose research or flag violations; they never enforce or override rules.
- Any unknown/unconfigured rule field or stale/unverified input defaults to DENY.
- Even when simulated rule checks pass in research, `execution_permission` remains `"none"`.
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from atlas.models.schemas import NonnegativeDecimal, PositiveDecimal, Probability, Record, Text


class TradingRuleBook(Record):
    """Versioned deterministic rulebook for either a competition or open-market track."""
    rulebook_id: Text
    revision: Text
    track: Literal["competition", "open_market"]
    evidence_ref: Text  # Reference to published competition rulebook or venue policy

    # 1. Per-trade risk (typically 0.005 to 0.01 = 0.5% to 1.0% equity)
    max_per_trade_risk_fraction: PositiveDecimal | None = None
    required_stop_kind: Literal["atr", "structure", "either"] = "either"
    min_stop_distance_bps: PositiveDecimal | None = None

    # 2. Daily loss limit / circuit breaker
    max_daily_loss_fraction: PositiveDecimal | None = None

    # 3. Maximum drawdown (static from initial equity or trailing from high-water mark)
    drawdown_mode: Literal["static", "trailing"] = "trailing"
    max_drawdown_fraction: PositiveDecimal | None = None

    # 4. Position / notional / leverage / correlation / sector caps
    max_position_notional_usd: PositiveDecimal | None = None
    max_gross_leverage: PositiveDecimal | None = None
    max_correlated_exposure_fraction: PositiveDecimal | None = None
    max_sector_exposure_fraction: PositiveDecimal | None = None

    # 5. Data-quality, freshness, and license gates
    require_verified_quality: bool = True
    require_commercial_license: bool = True
    max_data_age_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    # 6. Session / horizon rules and time-based exits
    allowed_sessions: frozenset[str] = frozenset({"regular_open", "continuous_24_7"})
    max_holding_seconds: int | None = Field(default=None, gt=0)
    forbid_funding_window_entry: bool = True

    # 7. Competition consistency & minimum trading days (competition track only)
    min_trading_days: int = Field(default=0, ge=0)
    max_single_day_profit_share: Probability | None = None

    @model_validator(mode="after")
    def competition_constraints(self) -> Self:
        if self.track == "competition" and self.min_trading_days <= 0:
            raise ValueError("Competition rulebook must specify positive min_trading_days")
        return self


class AccountRiskSnapshot(Record):
    """Point-in-time read-only snapshot of simulated or observed account state."""
    as_of: AwareDatetime
    source: Text
    initial_equity_usd: PositiveDecimal
    current_equity_usd: PositiveDecimal
    high_water_mark_usd: PositiveDecimal
    start_of_day_equity_usd: PositiveDecimal
    gross_notional_usd: NonnegativeDecimal
    correlated_exposure_usd: NonnegativeDecimal = Decimal("0")
    sector_exposure_usd: NonnegativeDecimal = Decimal("0")
    completed_trading_days: int = Field(default=0, ge=0)
    best_day_profit_usd: NonnegativeDecimal = Decimal("0")
    total_cumulative_profit_usd: Decimal = Decimal("0")
    kill_switch_engaged: bool = False
    is_book_of_record: Literal[False] = False

    @model_validator(mode="after")
    def hwm_valid(self) -> Self:
        if self.high_water_mark_usd < self.initial_equity_usd:
            raise ValueError("high_water_mark_usd cannot be below initial_equity_usd")
        return self


class ProposedTradeCheck(Record):
    """Hypothetical trade candidate evaluated against the deterministic rulebook."""
    instrument_id: Text
    notional_usd: PositiveDecimal
    stop_kind: Literal["atr", "structure", "none"]
    stop_distance_bps: NonnegativeDecimal
    holding_horizon_seconds: int = Field(gt=0)
    current_holding_seconds: int = Field(default=0, ge=0)
    session_state: Text
    data_quality: Literal["verified", "unknown", "rejected"]
    data_age_seconds: float = Field(ge=0, allow_inf_nan=False)
    license_verified: bool
    correlated_group_add_usd: NonnegativeDecimal = Decimal("0")
    sector_add_usd: NonnegativeDecimal = Decimal("0")


class LimitProximity(Record):
    rule_name: Text
    current_value: str
    limit_value: str
    utilization_pct: float = Field(ge=0, allow_inf_nan=False)
    remaining_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    status: Literal["healthy", "warning", "breached", "unconfigured"]


class RemainingRoomReport(Record):
    rulebook_id: Text
    track: Literal["competition", "open_market"]
    as_of: AwareDatetime
    max_safe_trade_notional_usd: str | None
    daily_loss_room_usd: str | None
    drawdown_room_usd: str | None
    leverage_room_usd: str | None
    consistency_compliant: bool
    minimum_days_met: bool
    proximities: tuple[LimitProximity, ...]
    execution_permission: Literal["none"] = "none"


class RuleEvaluationReport(Record):
    rulebook_id: Text
    revision: Text
    track: Literal["competition", "open_market"]
    evaluated_at: AwareDatetime
    compliance_passed: bool
    auto_flatten_required: bool
    kill_switch_active: bool
    time_exit_triggered: bool
    violations: tuple[str, ...]
    remaining_room: RemainingRoomReport
    execution_permission: Literal["none"] = "none"


def _proximity(name: str, current: Decimal, limit: Decimal | None) -> LimitProximity:
    if limit is None or limit <= 0:
        return LimitProximity(
            rule_name=name,
            current_value=str(round(current, 6)),
            limit_value="unconfigured",
            utilization_pct=100.0,
            remaining_pct=0.0,
            status="unconfigured",
        )
    ratio = float(current / limit) * 100.0
    util = max(0.0, round(ratio, 2))
    rem = max(0.0, min(100.0, round(100.0 - util, 2)))
    if current >= limit:
        status: Literal["healthy", "warning", "breached", "unconfigured"] = "breached"
    elif util >= 75.0:
        status = "warning"
    else:
        status = "healthy"
    return LimitProximity(
        rule_name=name,
        current_value=str(round(current, 6)),
        limit_value=str(round(limit, 6)),
        utilization_pct=util,
        remaining_pct=rem,
        status=status,
    )


def evaluate_trading_rules(
    rulebook: TradingRuleBook,
    account: AccountRiskSnapshot,
    candidate: ProposedTradeCheck,
    *,
    evaluated_at: datetime | None = None,
) -> RuleEvaluationReport:
    """Evaluate deterministic trading rules. Unknown/unconfigured fields default-deny."""
    now = evaluated_at or account.as_of
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    violations: list[str] = []
    auto_flatten = False
    time_exit = False

    # 0. Check kill switch first
    if account.kill_switch_engaged:
        violations.append("kill_switch_engaged: operator or circuit kill switch is active")
        auto_flatten = True

    # Verify mandatory numeric limits are configured (default-deny when None)
    required_fields = (
        ("max_per_trade_risk_fraction", rulebook.max_per_trade_risk_fraction),
        ("min_stop_distance_bps", rulebook.min_stop_distance_bps),
        ("max_daily_loss_fraction", rulebook.max_daily_loss_fraction),
        ("max_drawdown_fraction", rulebook.max_drawdown_fraction),
        ("max_position_notional_usd", rulebook.max_position_notional_usd),
        ("max_gross_leverage", rulebook.max_gross_leverage),
        ("max_correlated_exposure_fraction", rulebook.max_correlated_exposure_fraction),
        ("max_sector_exposure_fraction", rulebook.max_sector_exposure_fraction),
        ("max_data_age_seconds", rulebook.max_data_age_seconds),
        ("max_holding_seconds", rulebook.max_holding_seconds),
    )
    for field_name, val in required_fields:
        if val is None:
            violations.append(f"default_deny_unconfigured:{field_name}")

    equity = account.current_equity_usd

    # 1. Per-trade risk & stop structure
    stop_fraction = candidate.stop_distance_bps / Decimal("10000")
    trade_risk_usd = candidate.notional_usd * stop_fraction
    trade_risk_fraction = trade_risk_usd / equity
    if candidate.stop_kind == "none" or candidate.stop_distance_bps <= 0:
        violations.append("stop_loss_missing: every trade requires an ATR or structure stop")
    elif rulebook.required_stop_kind != "either" and candidate.stop_kind != rulebook.required_stop_kind:
        violations.append(f"stop_kind_mismatch: expected {rulebook.required_stop_kind}")
    if rulebook.min_stop_distance_bps is not None and candidate.stop_distance_bps < rulebook.min_stop_distance_bps:
        violations.append("stop_distance_too_tight: below min_stop_distance_bps")
    if rulebook.max_per_trade_risk_fraction is not None and trade_risk_fraction > rulebook.max_per_trade_risk_fraction:
        violations.append("per_trade_risk_exceeded: exceeds max_per_trade_risk_fraction")

    max_safe_notional: Decimal | None = None
    if (
        rulebook.max_per_trade_risk_fraction is not None
        and stop_fraction > 0
        and rulebook.max_position_notional_usd is not None
    ):
        risk_cap_notional = (equity * rulebook.max_per_trade_risk_fraction) / stop_fraction
        max_safe_notional = min(risk_cap_notional, rulebook.max_position_notional_usd)

    # 2. Daily loss limit / circuit breaker
    daily_loss_usd = max(Decimal("0"), account.start_of_day_equity_usd - equity)
    daily_loss_fraction = daily_loss_usd / account.start_of_day_equity_usd
    daily_loss_room: Decimal | None = None
    if rulebook.max_daily_loss_fraction is not None:
        max_daily_loss_usd = account.start_of_day_equity_usd * rulebook.max_daily_loss_fraction
        daily_loss_room = max(Decimal("0"), max_daily_loss_usd - daily_loss_usd)
        if daily_loss_fraction >= rulebook.max_daily_loss_fraction:
            violations.append("daily_loss_circuit_breaker: daily loss limit reached or breached")
            auto_flatten = True

    # 3. Maximum drawdown (static or trailing)
    reference_peak = (
        account.initial_equity_usd if rulebook.drawdown_mode == "static" else account.high_water_mark_usd
    )
    drawdown_usd = max(Decimal("0"), reference_peak - equity)
    drawdown_fraction = drawdown_usd / reference_peak
    drawdown_room: Decimal | None = None
    if rulebook.max_drawdown_fraction is not None:
        max_dd_usd = reference_peak * rulebook.max_drawdown_fraction
        drawdown_room = max(Decimal("0"), max_dd_usd - drawdown_usd)
        if drawdown_fraction >= rulebook.max_drawdown_fraction:
            violations.append(f"max_drawdown_breached:{rulebook.drawdown_mode}")
            auto_flatten = True

    # 4. Position / notional / leverage / correlation / sector caps
    if rulebook.max_position_notional_usd is not None and candidate.notional_usd > rulebook.max_position_notional_usd:
        violations.append("position_notional_cap_exceeded")

    projected_gross = account.gross_notional_usd + candidate.notional_usd
    projected_leverage = projected_gross / equity
    leverage_room: Decimal | None = None
    if rulebook.max_gross_leverage is not None:
        max_gross_usd = equity * rulebook.max_gross_leverage
        leverage_room = max(Decimal("0"), max_gross_usd - account.gross_notional_usd)
        if projected_leverage > rulebook.max_gross_leverage:
            violations.append("gross_leverage_cap_exceeded")

    projected_corr_fraction = (account.correlated_exposure_usd + candidate.correlated_group_add_usd) / equity
    if (
        rulebook.max_correlated_exposure_fraction is not None
        and projected_corr_fraction > rulebook.max_correlated_exposure_fraction
    ):
        violations.append("correlated_exposure_cap_exceeded")

    projected_sector_fraction = (account.sector_exposure_usd + candidate.sector_add_usd) / equity
    if (
        rulebook.max_sector_exposure_fraction is not None
        and projected_sector_fraction > rulebook.max_sector_exposure_fraction
    ):
        violations.append("sector_exposure_cap_exceeded")

    # 5. Data-quality, freshness, and license gates
    if rulebook.require_verified_quality and candidate.data_quality != "verified":
        violations.append("data_quality_unverified")
    if rulebook.require_commercial_license and not candidate.license_verified:
        violations.append("data_or_model_license_unverified")
    if rulebook.max_data_age_seconds is not None and candidate.data_age_seconds > rulebook.max_data_age_seconds:
        violations.append("stale_market_data")

    # 6. Session / horizon rules and time-based exits
    if candidate.session_state not in rulebook.allowed_sessions:
        violations.append(f"session_not_permitted:{candidate.session_state}")
    if rulebook.forbid_funding_window_entry and candidate.session_state == "funding_window":
        violations.append("funding_window_entry_forbidden")
    if rulebook.max_holding_seconds is not None:
        if candidate.holding_horizon_seconds > rulebook.max_holding_seconds:
            violations.append("horizon_exceeds_max_holding_seconds")
        if candidate.current_holding_seconds >= rulebook.max_holding_seconds:
            violations.append("time_based_exit_required: max holding duration elapsed")
            time_exit = True

    # 7. Competition consistency and minimum trading days
    consistency_ok = True
    min_days_met = account.completed_trading_days >= rulebook.min_trading_days
    if rulebook.track == "competition" and rulebook.max_single_day_profit_share is not None:
        if account.total_cumulative_profit_usd > 0:
            share = float(account.best_day_profit_usd / account.total_cumulative_profit_usd)
            if share > rulebook.max_single_day_profit_share:
                consistency_ok = False
                violations.append("competition_consistency_rule_breached: single day profit share too high")

    proximities = (
        _proximity("per_trade_risk_fraction", trade_risk_fraction, rulebook.max_per_trade_risk_fraction),
        _proximity("daily_loss_fraction", daily_loss_fraction, rulebook.max_daily_loss_fraction),
        _proximity(f"drawdown_{rulebook.drawdown_mode}_fraction", drawdown_fraction, rulebook.max_drawdown_fraction),
        _proximity("position_notional_usd", candidate.notional_usd, rulebook.max_position_notional_usd),
        _proximity("gross_leverage", projected_leverage, rulebook.max_gross_leverage),
        _proximity("correlated_exposure_fraction", projected_corr_fraction, rulebook.max_correlated_exposure_fraction),
        _proximity("sector_exposure_fraction", projected_sector_fraction, rulebook.max_sector_exposure_fraction),
    )

    remaining = RemainingRoomReport(
        rulebook_id=rulebook.rulebook_id,
        track=rulebook.track,
        as_of=now,
        max_safe_trade_notional_usd=str(round(max_safe_notional, 2)) if max_safe_notional is not None else None,
        daily_loss_room_usd=str(round(daily_loss_room, 2)) if daily_loss_room is not None else None,
        drawdown_room_usd=str(round(drawdown_room, 2)) if drawdown_room is not None else None,
        leverage_room_usd=str(round(leverage_room, 2)) if leverage_room is not None else None,
        consistency_compliant=consistency_ok,
        minimum_days_met=min_days_met,
        proximities=proximities,
    )

    return RuleEvaluationReport(
        rulebook_id=rulebook.rulebook_id,
        revision=rulebook.revision,
        track=rulebook.track,
        evaluated_at=now,
        compliance_passed=len(violations) == 0,
        auto_flatten_required=auto_flatten,
        kill_switch_active=account.kill_switch_engaged,
        time_exit_triggered=time_exit,
        violations=tuple(violations),
        remaining_room=remaining,
    )

