"""Stateful, deterministic Control-Plane Action Engine for ATLAS.

Executes rule-checked trade proposals, manages open positions, enforces kill-switch
and auto-flatten actions, and manages model approval and alias promotion/rollback.
Zero imports from `atlas.ai` — only the deterministic control plane authorizes actions.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from atlas.strategies.base import StrategySignal

from pydantic import AwareDatetime, Field

from atlas.control.rules import (
    AccountRiskSnapshot,
    ProposedTradeCheck,
    RuleEvaluationReport,
    TradingRuleBook,
    evaluate_trading_rules,
)
from atlas.models.schemas import Record, Text


class ActionableOrderRequest(Record):
    track: Literal["competition", "open_market"] = "competition"
    instrument_id: Text = "comp:btc-perp:v1"
    side: Literal["buy", "sell"] = "buy"
    notional_usd: Decimal = Decimal("25000")
    stop_kind: Literal["atr", "structure"] = "atr"
    stop_distance_bps: Decimal = Decimal("180")
    holding_horizon_seconds: int = 14400
    vpin_toxicity: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    data_age_ms: float = Field(default=8.4, ge=0, allow_inf_nan=False)


class ActionablePositionRecord(Record):
    position_id: Text
    track: Literal["competition", "open_market"]
    instrument_id: Text
    side: Literal["buy", "sell"]
    notional_usd: Decimal
    stop_kind: Literal["atr", "structure"]
    stop_distance_bps: Decimal
    opened_at: AwareDatetime
    status: Literal["open", "flattened", "closed"] = "open"


class ActionableOrderDecision(Record):
    order_id: Text
    evaluated_at: AwareDatetime
    track: Literal["competition", "open_market"]
    instrument_id: Text
    side: Literal["buy", "sell"]
    notional_usd: Decimal
    control_plane_decision: Literal["authorized_and_executed", "rejected_by_control_plane"]
    violations: tuple[str, ...] = ()
    position_id: Text | None = None
    entry_price: float | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    quantity: Decimal | None = None
    execution_mode: Literal["paper"] = "paper"
    rule_evaluation: RuleEvaluationReport


class BracketOrderIntakeReport(Record):
    """Result of the Signal Intake & Bracket Order Bridge inside `ActionableControlPlaneEngine`."""

    order_id: Text
    symbol: Text
    track: Literal["competition", "open_market"]
    direction: Literal["BUY", "SELL", "HOLD"]
    target_entry_price: float
    stop_loss_price: float
    take_profit_price: float
    stop_distance_bps: Decimal
    sized_notional_usd: Decimal
    risk_budget_usd: Decimal
    risk_fraction_of_equity: float
    data_age_ms: float
    remaining_room_hud: dict[str, Any]
    decision: ActionableOrderDecision
    connector_receipt: dict[str, Any] | None = None
    execution_permission: Literal["none"] = "none"


class ActionableControlState(Record):
    track: Literal["competition", "open_market"]
    kill_switch_engaged: bool
    account: AccountRiskSnapshot
    rule_evaluation: RuleEvaluationReport
    open_positions: tuple[ActionablePositionRecord, ...]
    order_history: tuple[ActionableOrderDecision, ...]
    active_champion_model: Text
    active_challenger_model: Text
    challenger_approved: bool
    training_runs_completed: int
    audit_log: tuple[str, ...]


class ActionableControlPlaneEngine:
    """Deterministic control-plane execution, risk, and lifecycle action engine."""

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.comp_rulebook = TradingRuleBook(
            rulebook_id="prop-comp-2026-q4:v1",
            revision="1.0.0",
            track="competition",
            evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md#competition-track",
            max_per_trade_risk_fraction=Decimal("0.0075"),
            required_stop_kind="either",
            min_stop_distance_bps=Decimal("25"),
            max_daily_loss_fraction=Decimal("0.04"),
            drawdown_mode="trailing",
            max_drawdown_fraction=Decimal("0.08"),
            max_position_notional_usd=Decimal("50000"),
            max_gross_leverage=Decimal("3.0"),
            max_correlated_exposure_fraction=Decimal("0.60"),
            max_sector_exposure_fraction=Decimal("0.75"),
            require_verified_quality=True,
            require_commercial_license=True,
            max_data_age_seconds=3600.0,
            allowed_sessions=frozenset({"regular_open", "continuous_24_7"}),
            max_holding_seconds=86400,
            forbid_funding_window_entry=True,
            min_trading_days=5,
            max_single_day_profit_share=0.35,
        )
        self.open_rulebook = TradingRuleBook(
            rulebook_id="open-market-swing-2026-q4:v1",
            revision="1.0.0",
            track="open_market",
            evidence_ref="docs/architecture/RESEARCH_OPERATING_CONTRACT.md#open-market-track",
            max_per_trade_risk_fraction=Decimal("0.005"),
            required_stop_kind="either",
            min_stop_distance_bps=Decimal("30"),
            max_daily_loss_fraction=Decimal("0.03"),
            drawdown_mode="static",
            max_drawdown_fraction=Decimal("0.10"),
            max_position_notional_usd=Decimal("40000"),
            max_gross_leverage=Decimal("2.0"),
            max_correlated_exposure_fraction=Decimal("0.50"),
            max_sector_exposure_fraction=Decimal("0.60"),
            require_verified_quality=True,
            require_commercial_license=True,
            max_data_age_seconds=3600.0,
            allowed_sessions=frozenset({"regular_open", "continuous_24_7"}),
            max_holding_seconds=86400,
            forbid_funding_window_entry=False,
        )
        self.active_track: Literal["competition", "open_market"] = "competition"
        self.kill_switch_engaged: bool = False
        self.initial_equity_usd = Decimal("100000")
        self.current_equity_usd = Decimal("101850")
        self.high_water_mark_usd = Decimal("103100")
        self.start_of_day_equity_usd = Decimal("102900")
        self.gross_notional_usd = Decimal("25000")
        self.correlated_exposure_usd = Decimal("12000")
        self.sector_exposure_usd = Decimal("12000")
        self.completed_trading_days = 6
        self.best_day_profit_usd = Decimal("820")
        self.total_cumulative_profit_usd = Decimal("2950")
        self.open_positions: list[ActionablePositionRecord] = [
            ActionablePositionRecord(
                position_id="pos-001",
                track="competition",
                instrument_id="comp:btc-perp:v1",
                side="buy",
                notional_usd=Decimal("25000"),
                stop_kind="atr",
                stop_distance_bps=Decimal("180"),
                opened_at=now,
                status="open",
            )
        ]
        self.order_history: list[ActionableOrderDecision] = []
        self.active_champion_model: str = "naive:last_value:v1"
        self.active_challenger_model: str = "local_tree:boosted_stump_v1:v1"
        self.challenger_approved: bool = True
        self.training_runs_completed: int = 1
        self.last_feed_latency_ms: float = 8.4
        self.data_freshness_breach: bool = False
        self.audit_log: list[str] = [
            f"{now.isoformat()} | control_plane_initialized | track=competition | kill_switch=False"
        ]
        self.execution_connector = None
        self._order_seq = 1
        self._pos_seq = 1

    def _rulebook_for(self, track: Literal["competition", "open_market"]) -> TradingRuleBook:
        return self.comp_rulebook if track == "competition" else self.open_rulebook

    def _snapshot(self, now: datetime) -> AccountRiskSnapshot:
        return AccountRiskSnapshot(
            as_of=now,
            source=f"control_plane:{self.active_track}",
            initial_equity_usd=self.initial_equity_usd,
            current_equity_usd=self.current_equity_usd,
            high_water_mark_usd=self.high_water_mark_usd,
            start_of_day_equity_usd=self.start_of_day_equity_usd,
            gross_notional_usd=self.gross_notional_usd,
            correlated_exposure_usd=self.correlated_exposure_usd,
            sector_exposure_usd=self.sector_exposure_usd,
            completed_trading_days=self.completed_trading_days,
            best_day_profit_usd=self.best_day_profit_usd,
            total_cumulative_profit_usd=self.total_cumulative_profit_usd,
            kill_switch_engaged=self.kill_switch_engaged,
        )

    def get_state(self, now: datetime | None = None) -> ActionableControlState:
        ts = now or datetime.now(timezone.utc)
        rulebook = self._rulebook_for(self.active_track)
        snap = self._snapshot(ts)
        default_cand = ProposedTradeCheck(
            instrument_id="comp:btc-perp:v1" if self.active_track == "competition" else "open:spy-etf:v1",
            notional_usd=Decimal("25000"),
            stop_kind="atr",
            stop_distance_bps=Decimal("180"),
            holding_horizon_seconds=14400,
            current_holding_seconds=0,
            session_state="continuous_24_7" if self.active_track == "competition" else "regular_open",
            data_quality="verified",
            data_age_seconds=30.0,
            license_verified=True,
            correlated_group_add_usd=Decimal("6250"),
            sector_add_usd=Decimal("6250"),
        )
        eval_rep = evaluate_trading_rules(rulebook, snap, default_cand, evaluated_at=ts)
        return ActionableControlState(
            track=self.active_track,
            kill_switch_engaged=self.kill_switch_engaged,
            account=snap,
            rule_evaluation=eval_rep,
            open_positions=tuple(p for p in self.open_positions if p.status == "open"),
            order_history=tuple(self.order_history[-15:]),
            active_champion_model=self.active_champion_model,
            active_challenger_model=self.active_challenger_model,
            challenger_approved=self.challenger_approved,
            training_runs_completed=self.training_runs_completed,
            audit_log=tuple(self.audit_log[-20:]),
        )

    def submit_order(
        self,
        request: ActionableOrderRequest,
        *,
        now: datetime | None = None,
        intake_violations: tuple[str, ...] = (),
    ) -> ActionableOrderDecision:
        ts = now or datetime.now(timezone.utc)
        self.active_track = request.track
        rulebook = self._rulebook_for(request.track)
        snap = self._snapshot(ts)
        cand = ProposedTradeCheck(
            instrument_id=request.instrument_id,
            notional_usd=request.notional_usd,
            stop_kind=request.stop_kind,
            stop_distance_bps=request.stop_distance_bps,
            holding_horizon_seconds=request.holding_horizon_seconds,
            current_holding_seconds=0,
            session_state="continuous_24_7" if request.track == "competition" else "regular_open",
            data_quality="verified",
            data_age_seconds=25.0,
            license_verified=True,
            correlated_group_add_usd=(request.notional_usd * Decimal("0.25")).quantize(Decimal("0.01")),
            sector_add_usd=(request.notional_usd * Decimal("0.25")).quantize(Decimal("0.01")),
            vpin_toxicity=request.vpin_toxicity,
        )
        eval_rep = evaluate_trading_rules(rulebook, snap, cand, evaluated_at=ts)
        extra_violations = list(eval_rep.violations) + list(intake_violations)
        if request.track == "open_market" and request.data_age_ms > 2000.0:
            extra_violations.append("data_stale_open_market_2000ms")
        if request.track == "competition" and float(request.data_age_ms) > 500.0:
            extra_violations.append("data_stale_competition_500ms: market data staleness exceeds 500ms")
        if extra_violations != list(eval_rep.violations):
            eval_rep = eval_rep.model_copy(
                update={
                    "compliance_passed": False,
                    "violations": tuple(extra_violations),
                }
            )
        self._order_seq += 1
        order_id = f"ord-{self._order_seq:03d}"

        if eval_rep.compliance_passed:
            self._pos_seq += 1
            pos_id = f"pos-{self._pos_seq:03d}"
            pos = ActionablePositionRecord(
                position_id=pos_id,
                track=request.track,
                instrument_id=request.instrument_id,
                side=request.side,
                notional_usd=request.notional_usd,
                stop_kind=request.stop_kind,
                stop_distance_bps=request.stop_distance_bps,
                opened_at=ts,
                status="open",
            )
            self.open_positions.append(pos)
            self.gross_notional_usd += request.notional_usd
            self.correlated_exposure_usd += cand.correlated_group_add_usd
            self.sector_exposure_usd += cand.sector_add_usd
            decision = ActionableOrderDecision(
                order_id=order_id,
                evaluated_at=ts,
                track=request.track,
                instrument_id=request.instrument_id,
                side=request.side,
                notional_usd=request.notional_usd,
                control_plane_decision="authorized_and_executed",
                violations=(),
                position_id=pos_id,
                rule_evaluation=eval_rep,
            )
            self.audit_log.append(
                f"{ts.isoformat()} | order_authorized | {order_id} | {request.side.upper()} {request.instrument_id} ${request.notional_usd}"
            )
        else:
            decision = ActionableOrderDecision(
                order_id=order_id,
                evaluated_at=ts,
                track=request.track,
                instrument_id=request.instrument_id,
                side=request.side,
                notional_usd=request.notional_usd,
                control_plane_decision="rejected_by_control_plane",
                violations=eval_rep.violations,
                position_id=None,
                rule_evaluation=eval_rep,
            )
            self.audit_log.append(
                f"{ts.isoformat()} | order_rejected | {order_id} | reasons={','.join(eval_rep.violations)}"
            )

        self.order_history.append(decision)
        return decision

    def flatten_all_positions(
        self,
        *,
        reason: str = "operator_auto_flatten",
        now: datetime | None = None,
    ) -> ActionableControlState:
        ts = now or datetime.now(timezone.utc)
        flattened_count = 0
        updated: list[ActionablePositionRecord] = []
        for pos in self.open_positions:
            if pos.status == "open":
                flattened_count += 1
                updated.append(pos.model_copy(update={"status": "flattened"}))
            else:
                updated.append(pos)
        self.open_positions = updated
        self.gross_notional_usd = Decimal("0")
        self.correlated_exposure_usd = Decimal("0")
        self.sector_exposure_usd = Decimal("0")
        self.audit_log.append(
            f"{ts.isoformat()} | positions_flattened | count={flattened_count} | reason={reason}"
        )
        return self.get_state(ts)

    def close_position(
        self,
        position_id: str,
        *,
        exit_price: float,
        fee_usd: Decimal = Decimal("0"),
        reason: str = "paper_close",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Book a paper exit for one open position. This is not a venue fill."""
        ts = now or datetime.now(timezone.utc)
        rejected = {
            "status": "rejected",
            "position_id": position_id,
            "execution_mode": "paper",
            "execution_permission": "none",
        }
        if not math.isfinite(exit_price) or exit_price <= 0:
            return {**rejected, "reason": "invalid_exit_price"}
        if fee_usd < 0:
            return {**rejected, "reason": "invalid_fee"}
        pos = next((p for p in self.open_positions if p.position_id == position_id and p.status == "open"), None)
        if pos is None:
            return {**rejected, "reason": "position_not_open"}
        entry: float | None = None
        for order in reversed(self.order_history):
            if order.position_id == position_id and order.entry_price:
                entry = float(order.entry_price)
                break
        pnl = Decimal("0")
        if entry is not None and entry > 0:
            sign = Decimal("1") if pos.side == "buy" else Decimal("-1")
            pnl = (Decimal(str((exit_price - entry) / entry)) * pos.notional_usd * sign).quantize(Decimal("0.01"))
        net = (pnl - fee_usd).quantize(Decimal("0.01"))
        self.current_equity_usd = (self.current_equity_usd + net).quantize(Decimal("0.01"))
        if self.current_equity_usd > self.high_water_mark_usd:
            self.high_water_mark_usd = self.current_equity_usd
        self.gross_notional_usd = max(Decimal("0"), self.gross_notional_usd - pos.notional_usd)
        exposure_cut = (pos.notional_usd * Decimal("0.25")).quantize(Decimal("0.01"))
        self.correlated_exposure_usd = max(Decimal("0"), self.correlated_exposure_usd - exposure_cut)
        self.sector_exposure_usd = max(Decimal("0"), self.sector_exposure_usd - exposure_cut)
        self.open_positions = [
            item.model_copy(update={"status": "closed"}) if item.position_id == position_id else item
            for item in self.open_positions
        ]
        self.audit_log.append(
            f"{ts.isoformat()} | position_closed | {position_id} | reason={reason} | paper_pnl_usd={net}"
        )
        return {
            "status": "closed",
            "position_id": position_id,
            "exit_price": exit_price,
            "paper_pnl_usd": float(net),
            "equity_usd": float(self.current_equity_usd),
            "reason": reason,
            "execution_mode": "paper",
            "execution_permission": "none",
        }

    def set_kill_switch(
        self,
        engaged: bool,
        *,
        reason: str = "operator_kill_switch",
        now: datetime | None = None,
    ) -> ActionableControlState:
        ts = now or datetime.now(timezone.utc)
        self.kill_switch_engaged = engaged
        if engaged:
            self.flatten_all_positions(reason=f"kill_switch_engaged:{reason}", now=ts)
        else:
            self.audit_log.append(f"{ts.isoformat()} | kill_switch_reset | reason={reason}")
        return self.get_state(ts)

    def apply_lifecycle_action(
        self,
        action: Literal["approve_challenger", "revoke_challenger", "promote_challenger", "rollback_to_champion"],
        *,
        now: datetime | None = None,
    ) -> ActionableControlState:
        ts = now or datetime.now(timezone.utc)
        if action == "approve_challenger":
            self.challenger_approved = True
        elif action == "revoke_challenger":
            self.challenger_approved = False
        elif action == "promote_challenger":
            if not self.challenger_approved:
                raise PermissionError("Cannot promote challenger without active scoped approval")
            self.active_champion_model = self.active_challenger_model
        elif action == "rollback_to_champion":
            self.active_champion_model = "naive:last_value:v1"
        self.audit_log.append(
            f"{ts.isoformat()} | lifecycle_action | action={action} | champion={self.active_champion_model} | approved={self.challenger_approved}"
        )
        return self.get_state(ts)

    def record_training_run(self, *, now: datetime | None = None) -> ActionableControlState:
        ts = now or datetime.now(timezone.utc)
        self.training_runs_completed += 1
        rev = self.training_runs_completed
        self.active_challenger_model = f"local_tree:boosted_stump_v1:v{rev}"
        self.audit_log.append(
            f"{ts.isoformat()} | self_training_completed | challenger={self.active_challenger_model} | runs={self.training_runs_completed}"
        )
        return self.get_state(ts)

    def report_feed_latency(
        self,
        *,
        track: Literal["competition", "open_market"] = "competition",
        latency_ms: float,
        provider: str = "live_stream",
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Reports live ingestion tick-to-decision latency to the deterministic control plane.

        If data feed staleness exceeds 500ms on prop competition tracks, flags a deterministic
        data-freshness circuit breach.
        """
        ts = now or datetime.now(timezone.utc)
        self.last_feed_latency_ms = float(latency_ms)
        threshold_ms = 500.0 if track == "competition" else 2000.0
        breach = float(latency_ms) > threshold_ms
        self.data_freshness_breach = breach
        if breach:
            self.audit_log.append(
                f"{ts.isoformat()} | data_freshness_circuit_breach | track={track} | provider={provider} | latency_ms={latency_ms:.2f} > {threshold_ms:.1f}ms"
            )
        else:
            self.audit_log.append(
                f"{ts.isoformat()} | feed_latency_verified | track={track} | provider={provider} | latency_ms={latency_ms:.2f}ms"
            )
        return {
            "track": track,
            "provider": provider,
            "latency_ms": round(float(latency_ms), 2),
            "threshold_ms": threshold_ms,
            "data_freshness_breach": breach,
            "evaluated_at": ts.isoformat(),
        }

    def get_remaining_room_hud(
        self,
        *,
        track: Literal["competition", "open_market"] | None = None,
    ) -> dict[str, object]:
        """Compute exact dollar and percentage buffers remaining before breaching daily or trailing drawdown limits."""
        active_trk = track or self.active_track
        rulebook = self._rulebook_for(active_trk)
        sod = max(Decimal("1"), self.start_of_day_equity_usd)
        hwm = max(Decimal("1"), self.initial_equity_usd if rulebook.drawdown_mode == "static" else self.high_water_mark_usd)
        curr = self.current_equity_usd

        daily_limit_frac = rulebook.max_daily_loss_fraction  # 0.04 on competition, 0.03 on open_market
        trailing_limit_frac = rulebook.max_drawdown_fraction  # 0.08 on competition, 0.10 on open_market

        daily_floor_usd = (sod * (Decimal("1") - daily_limit_frac)).quantize(Decimal("0.01"))
        trailing_floor_usd = (hwm * (Decimal("1") - trailing_limit_frac)).quantize(Decimal("0.01"))

        daily_room_usd = max(Decimal("0.00"), (curr - daily_floor_usd).quantize(Decimal("0.01")))
        trailing_room_usd = max(Decimal("0.00"), (curr - trailing_floor_usd).quantize(Decimal("0.01")))

        daily_dd_frac = max(Decimal("0"), (sod - curr) / sod)
        trailing_dd_frac = max(Decimal("0"), (hwm - curr) / hwm)

        daily_room_pct = float(max(Decimal("0"), (daily_limit_frac - daily_dd_frac) * Decimal("100")))
        trailing_room_pct = float(max(Decimal("0"), (trailing_limit_frac - trailing_dd_frac) * Decimal("100")))

        return {
            "track": active_trk,
            "current_equity_usd": float(curr),
            "start_of_day_equity_usd": float(sod),
            "high_water_mark_usd": float(hwm),
            "daily_floor_usd": float(daily_floor_usd),
            "trailing_floor_usd": float(trailing_floor_usd),
            "daily_loss_room_usd": float(daily_room_usd),
            "daily_loss_room_pct": round(daily_room_pct, 3),
            "trailing_dd_room_usd": float(trailing_room_usd),
            "trailing_dd_room_pct": round(trailing_room_pct, 3),
            "daily_drawdown_fraction": round(float(daily_dd_frac), 6),
            "trailing_drawdown_fraction": round(float(trailing_dd_frac), 6),
            "daily_loss_limit_pct": float(daily_limit_frac * Decimal("100")),
            "drawdown_limit_pct": float(trailing_limit_frac * Decimal("100")),
            "drawdown_mode": rulebook.drawdown_mode,
        }

    def evaluate_market_tick(
        self,
        *,
        symbol: str,
        price: float,
        track: Literal["competition", "open_market"] = "competition",
        latency_ms: float = 8.4,
        provider: str = "live_stream",
        mark_to_market_equity_usd: Decimal | float | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Real-time control-plane hook invoked on incoming market ticks.

        1. Checks market data staleness (> 500ms on `competition` track triggers data-freshness circuit alert).
        2. Evaluates real-time mark-to-market open equity against the 4.0% daily loss limit and 8.0% trailing
           high-water-mark drawdown floor; if either threshold is touched/breached, immediately triggers
           deterministic auto-flattening of all open positions.
        """
        ts = now or datetime.now(timezone.utc)
        freshness = self.report_feed_latency(
            track=track,
            latency_ms=latency_ms,
            provider=provider,
            now=ts,
        )

        if mark_to_market_equity_usd is not None:
            new_eq = Decimal(str(round(float(mark_to_market_equity_usd), 2)))
            self.current_equity_usd = new_eq
            if new_eq > self.high_water_mark_usd:
                self.high_water_mark_usd = new_eq

        rulebook = self._rulebook_for(track)
        sod = max(Decimal("1"), self.start_of_day_equity_usd)
        hwm = max(Decimal("1"), self.initial_equity_usd if rulebook.drawdown_mode == "static" else self.high_water_mark_usd)
        curr = self.current_equity_usd

        daily_dd_frac = max(Decimal("0"), (sod - curr) / sod)
        trailing_dd_frac = max(Decimal("0"), (hwm - curr) / hwm)

        daily_breached = daily_dd_frac >= rulebook.max_daily_loss_fraction
        trailing_breached = trailing_dd_frac >= rulebook.max_drawdown_fraction

        auto_flattened = False
        breach_reasons: list[str] = []
        if daily_breached:
            breach_reasons.append(
                f"daily_loss_circuit_breaker:{float(daily_dd_frac * 100):.2f}%>={float(rulebook.max_daily_loss_fraction * 100):.2f}%"
            )
        if trailing_breached:
            breach_reasons.append(
                f"trailing_hwm_drawdown_floor:{float(trailing_dd_frac * 100):.2f}%>={float(rulebook.max_drawdown_fraction * 100):.2f}%"
            )

        if daily_breached or trailing_breached:
            auto_flattened = True
            self.kill_switch_engaged = True
            reason_str = "|".join(breach_reasons)
            self.flatten_all_positions(reason=f"tick_mtm_liquidation:{symbol}@{price}:{reason_str}", now=ts)

        hud = self.get_remaining_room_hud(track=track)
        status: Literal["AUTO_FLATTENED", "STALE_DATA_ALERT", "NOMINAL"] = (
            "AUTO_FLATTENED"
            if auto_flattened
            else ("STALE_DATA_ALERT" if bool(freshness["data_freshness_breach"]) else "NOMINAL")
        )

        return {
            "status": status,
            "symbol": symbol.upper(),
            "price": round(float(price), 4),
            "track": track,
            "latency_ms": round(float(latency_ms), 2),
            "data_freshness_breach": bool(freshness["data_freshness_breach"]),
            "auto_flattened": auto_flattened,
            "kill_switch_engaged": self.kill_switch_engaged,
            "breach_reasons": tuple(breach_reasons),
            "open_positions_count": sum(1 for p in self.open_positions if p.status == "open"),
            "remaining_room_hud": hud,
            "evaluated_at": ts.isoformat(),
        }

    def ingest_whale_policy_signal(
        self,
        signal: Any,
        *,
        track: Literal["competition", "open_market"] | None = None,
        risk_fraction_target: Decimal = Decimal("0.0060"),
        desired_notional_usd: Decimal | None = None,
        data_age_ms: float = 8.4,
        execution_connector: Any | None = None,
        require_connector: bool = False,
        now: datetime | None = None,
    ) -> BracketOrderIntakeReport:
        """Signal Intake & Bracket Order Bridge inside `ActionableControlPlaneEngine`.

        1. Verifies strict AI Air-Gap (`signal.execution_permission == "none"`).
        2. Checks `get_remaining_room_hud()` and sizes position strictly within the 0.50%-0.75%
           per-trade equity risk envelope (unless an explicit `desired_notional_usd` is supplied).
        3. Attaches mandatory structural ATR stop-loss and take-profit brackets.
        4. Rejects orders deterministically if:
           - Floating daily drawdown breaches the 4.0% daily circuit breaker
           - Account equity breaches the 8.0% max trailing drawdown floor
           - Single-day profit consistency gate (> 35%) is violated
           - Per-trade risk exceeds 0.75% of account balance
           - Mandatory ATR stop-loss bracket is missing (`stop_distance_bps <= 0`)
           - Market data staleness exceeds 500ms on the `competition` track
        5. Dispatches authorized bracket orders to `execution_connector` when provided.
        """
        ts = now or datetime.now(timezone.utc)
        sig_dict = signal.model_dump() if hasattr(signal, "model_dump") else dict(signal)

        if sig_dict.get("execution_permission") != "none":
            raise ValueError("AI Air-Gap Violation: incoming StrategySignal must have execution_permission == 'none'")

        sym = str(sig_dict.get("symbol", "BTC-USD")).upper().strip()
        resolved_track: Literal["competition", "open_market"] = (
            track
            if track in ("competition", "open_market")
            else ("competition" if sym.endswith("-USD") or sym.endswith("USDT") else "open_market")
        )
        direction: Literal["BUY", "SELL", "HOLD"] = str(sig_dict.get("direction", "BUY")).upper()  # type: ignore[assignment]
        entry_px = float(sig_dict.get("target_entry_price") or sig_dict.get("reference_price") or 0.0)
        stop_px = float(sig_dict.get("suggested_stop_loss", 0.0))
        tp_px = float(sig_dict.get("suggested_take_profit", 0.0))
        telemetry = sig_dict.get("telemetry") or {}
        vpin_val = float(telemetry.get("vpin", 0.0))
        intake_violations: list[str] = []
        if require_connector and execution_connector is None:
            intake_violations.append("execution_connector_unconfigured")
        if direction not in ("BUY", "SELL"):
            intake_violations.append("non_actionable_signal")
            direction = "HOLD"
        if not all(math.isfinite(x) and x > 0 for x in (entry_px, stop_px, tp_px)):
            intake_violations.append("invalid_bracket_prices")
            entry_px, stop_px, tp_px = 0.0, 0.0, 0.0
        elif not ((direction == "BUY" and stop_px < entry_px < tp_px) or
                  (direction == "SELL" and tp_px < entry_px < stop_px)):
            intake_violations.append("invalid_bracket_direction")
        if not math.isfinite(vpin_val) or not 0 <= vpin_val <= 1:
            intake_violations.append("invalid_vpin")
            vpin_val = 1.0
        if not math.isfinite(data_age_ms) or data_age_ms < 0:
            intake_violations.append("invalid_data_age")
            data_age_ms = 1e12
        rulebook = self._rulebook_for(resolved_track)


        if entry_px > 0 and stop_px > 0 and abs(entry_px - stop_px) > 1e-9:
            raw_stop_bps = abs(entry_px - stop_px) / entry_px * 10_000.0
            stop_bps = Decimal(str(round(raw_stop_bps, 2)))
        else:
            stop_bps = Decimal("0")

        hud = self.get_remaining_room_hud(track=resolved_track)
        equity = self.current_equity_usd

        # Enforce 0.50%-0.75% equity risk sizing when desired_notional_usd is not explicitly overridden
        clamped_risk_frac = min(rulebook.max_per_trade_risk_fraction or Decimal("0"), Decimal("0.0075"), max(Decimal("0"), Decimal(str(risk_fraction_target))))
        risk_budget_usd = (equity * clamped_risk_frac).quantize(Decimal("0.01"))

        if desired_notional_usd is not None:
            sized_notional = Decimal(str(desired_notional_usd)).quantize(Decimal("0.01"))
        elif stop_bps > Decimal("0"):
            stop_frac = stop_bps / Decimal("10000")
            raw_notional = risk_budget_usd / stop_frac
            rulebook = self._rulebook_for(resolved_track)
            max_cap = rulebook.max_position_notional_usd or (
                Decimal("50000") if resolved_track == "competition" else Decimal("40000")
            )
            sized_notional = min(max_cap, raw_notional.quantize(Decimal("0.01")))
        else:
            sized_notional = Decimal("25000")

        lot_sizes = {"BTC-USD": Decimal("0.0001"), "ETH-USD": Decimal("0.001"), "SOL-USD": Decimal("0.01"),
                     **{x: Decimal("1") for x in ("SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA")}}
        lot = lot_sizes.get(sym)
        if lot is None:
            intake_violations.append("instrument_lot_metadata_unavailable")
        if desired_notional_usd is None and entry_px > 0 and stop_bps > 0:
            # RemainingRoomReport is the canonical policy result, including floating losses.
            preview = evaluate_trading_rules(rulebook, self._snapshot(ts), ProposedTradeCheck(
                instrument_id=sym, notional_usd=max(Decimal("0.01"), sized_notional),
                stop_kind="atr", stop_distance_bps=stop_bps, holding_horizon_seconds=3600,
                session_state="continuous_24_7" if resolved_track == "competition" else "regular_open",
                data_quality="verified", data_age_seconds=data_age_ms / 1000, license_verified=True,
                vpin_toxicity=vpin_val,
            ), evaluated_at=ts).remaining_room
            for room in (preview.max_safe_trade_notional_usd, preview.leverage_room_usd):
                if room is not None:
                    sized_notional = min(sized_notional, Decimal(room))
            if lot is not None:
                quantity = (sized_notional / Decimal(str(entry_px)) / lot).to_integral_value(rounding=ROUND_DOWN) * lot
                sized_notional = quantity * Decimal(str(entry_px))
            if sized_notional <= 0:
                intake_violations.append("insufficient_remaining_room_for_one_lot")
                sized_notional = Decimal("0.01")

        actual_risk_usd = (sized_notional * (stop_bps / Decimal("10000"))).quantize(Decimal("0.01"))
        actual_risk_frac = float(actual_risk_usd / max(Decimal("1"), equity))

        prefix = "comp" if resolved_track == "competition" else "open"
        inst_id = f"{prefix}:{sym.lower().replace('-usd', '')}-perp:v1" if resolved_track == "competition" else f"{prefix}:{sym.lower()}-eq:v1"
        side: Literal["buy", "sell"] = "sell" if direction == "SELL" else "buy"

        req = ActionableOrderRequest(
            track=resolved_track,
            instrument_id=inst_id,
            side=side,
            notional_usd=sized_notional,
            stop_kind="atr",
            stop_distance_bps=stop_bps,
            holding_horizon_seconds=3600,
            vpin_toxicity=min(1.0, max(0.0, vpin_val)),
            data_age_ms=float(data_age_ms),
        )
        decision = self.submit_order(req, now=ts, intake_violations=tuple(intake_violations))
        decision = decision.model_copy(update={
            "entry_price": entry_px, "stop_loss_price": stop_px,
            "take_profit_price": tp_px,
            "quantity": sized_notional / Decimal(str(entry_px)) if entry_px > 0 else Decimal("0"),
        })
        self.order_history[-1] = decision

        connector_receipt: dict[str, Any] | None = None
        if decision.control_plane_decision == "authorized_and_executed" and execution_connector is not None:
            if hasattr(execution_connector, "route_approved_order"):
                raw_rec = execution_connector.route_approved_order(
                    decision,
                    tactic=str(sig_dict.get("execution_tactic", "ALMGREN_CHRISS")),
                    reference_price=entry_px,
                    executed_at=ts,
                )
                connector_receipt = raw_rec.model_dump(mode="json") if hasattr(raw_rec, "model_dump") else dict(raw_rec)

        return BracketOrderIntakeReport(
            order_id=decision.order_id,
            symbol=sym,
            track=resolved_track,
            direction=direction,
            target_entry_price=entry_px,
            stop_loss_price=stop_px,
            take_profit_price=tp_px,
            stop_distance_bps=stop_bps,
            sized_notional_usd=sized_notional,
            risk_budget_usd=actual_risk_usd,
            risk_fraction_of_equity=round(actual_risk_frac, 6),
            data_age_ms=round(float(data_age_ms), 2),
            remaining_room_hud=hud,
            decision=decision,
            connector_receipt=connector_receipt,
            execution_permission="none",
        )

    def process_strategy_signal(self, signal: StrategySignal, current_equity: float) -> BracketOrderIntakeReport:
        """Deterministic entry point. Equity must include realized and floating P&L.

        Existing connectors are paper simulators; this method does not claim a venue fill.
        """
        if signal.execution_permission != "none":
            raise ValueError("Signal execution_permission must be none")
        if not math.isfinite(current_equity) or current_equity <= 0:
            raise ValueError("current_equity must be finite and positive")
        self.current_equity_usd = Decimal(str(current_equity))
        self.high_water_mark_usd = max(self.high_water_mark_usd, self.current_equity_usd)
        return self.ingest_whale_policy_signal(signal, execution_connector=self.execution_connector, require_connector=True)

    evaluate_and_bracket_signal = ingest_whale_policy_signal



