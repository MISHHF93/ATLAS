"""Stateful, deterministic Control-Plane Action Engine for ATLAS.

Executes rule-checked trade proposals, manages open positions, enforces kill-switch
and auto-flatten actions, and manages model approval and alias promotion/rollback.
Zero imports from `atlas.ai` — only the deterministic control plane authorizes actions.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime

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
    rule_evaluation: RuleEvaluationReport


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
        self.audit_log: list[str] = [
            f"{now.isoformat()} | control_plane_initialized | track=competition | kill_switch=False"
        ]
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
        )
        eval_rep = evaluate_trading_rules(rulebook, snap, cand, evaluated_at=ts)
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

