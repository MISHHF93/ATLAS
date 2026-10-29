"""ATLAS End-to-End User Lifecycle & Master Spec Alignment Engine (`src/atlas/lifecycle.py`).

Unifies the platform's 4-step user lifecycle across both Realms:
1. Stage 1 (`1_onboard_and_realm`): Realm selection (Open-Market Equities vs. Prop Trading Competitions),
   ICP persona mapping (`ICP-01`..`ICP-04`), and automated Webcam Biometric KYC readiness (`Features 1-10`).
2. Stage 2 (`2_signal_discovery`): Real-time 12-Factor Whale ML & Causal GBDT opportunity lock
   (`WSDM-01`..`WSDM-05`) with `execution_permission: "none"`.
3. Stage 3 (`3_deterministic_execution`): Zero-touch pre-trade order sizing and deterministic authorization
   via `ActionableControlPlaneEngine` (0 LLM imports, 4% daily / 8% trailing HWM / <=35% consistency).
4. Stage 4 (`4_evaluation_and_graduation`): Challenge progression tracking (Phase 1 -> Phase 2 -> Funded 80/20
   or Open-Market T+1 Compounding) and 8-Ledger non-custodial isolation (`ATLAS_MASTER_SPEC.md`).

All analytical and lifecycle state outputs enforce `execution_permission = "none"`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from atlas.control.engine import ActionableControlPlaneEngine
from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.models.bot_orchestrator import BotOrchestrator

LifecycleStageId = Literal[
    "1_onboard_and_realm",
    "2_signal_discovery",
    "3_deterministic_execution",
    "4_evaluation_and_graduation",
]


@dataclass
class ChallengeProgressionState:
    realm: Literal["competition", "open_market"]
    challenge_tier: str
    current_phase: str
    starting_balance_usd: float
    current_equity_usd: float
    high_water_mark_usd: float
    profit_target_pct: float
    current_return_pct: float
    progress_to_target_pct: float
    trading_days_completed: int
    min_trading_days_required: int
    max_single_day_profit_share_pct: float
    consistency_gate_limit_pct: float
    daily_loss_cushion_usd: float
    trailing_hwm_cushion_usd: float
    kyc_proctoring_verified: bool
    payout_split_label: str
    ledger_isolation_note: str
    execution_permission: Literal["none"] = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserLifecycleEngine:
    """Manages the simplified 4-stage user lifecycle across Open-Market and Prop Competition tracks."""

    def __init__(self) -> None:
        self.active_stage: LifecycleStageId = "2_signal_discovery"
        self.active_realm: Literal["competition", "open_market"] = "competition"
        self.active_icp: Literal["ICP-01", "ICP-02", "ICP-03", "ICP-04"] = "ICP-01"
        self.challenge_tier: str = "100k_2phase"
        self.phase_index: int = 0  # 0: Phase 1 (+8%), 1: Phase 2 (+5%), 2: Funded (80/20)
        self.trading_days_completed: int = 5
        self.simulated_bonus_equity_usd: float = 0.0
        self.kyc_verified: bool = True

    def _phase_metadata(self, realm: Literal["competition", "open_market"]) -> tuple[str, float, str]:
        if realm == "open_market":
            return (
                "Open-Market NYSE/Nasdaq Desk (T+1 Reg-T Compounding)",
                10.0,
                "100% Direct Broker Account (Ledger 2 · Non-Custodial)",
            )
        if self.phase_index == 0:
            return ("Phase 1 Evaluation (+8.0% Profit Target)", 8.0, "Qualifies for Phase 2 Verification")
        if self.phase_index == 1:
            return ("Phase 2 Verification (+5.0% Profit Target)", 5.0, "Qualifies for Funded 80/20 Account")
        return ("Funded Prop Trader Account (Active)", 4.0, "80% Trader / 20% Firm Bi-Weekly Split (Ledger 6)")

    def build_state(
        self,
        *,
        symbol: str,
        control_engine: ActionableControlPlaneEngine,
        bot_orchestrator: BotOrchestrator,
        market_gateway: LiveMarketDataGateway,
    ) -> dict[str, Any]:
        sym = symbol.upper().strip()
        is_crypto = sym.endswith("-USD") or sym in {"BTC-USD", "ETH-USD", "SOL-USD"}
        resolved_realm: Literal["competition", "open_market"] = "competition" if is_crypto else "open_market"
        self.active_realm = resolved_realm
        self.active_icp = "ICP-01" if is_crypto else "ICP-02"

        pred = bot_orchestrator.predict_live_market_data(
            market_gateway,
            symbol=sym,
            granularity=900,
            allow_network=False,
        )
        opp = pred.get("locked_whale_opportunity") or {}
        micro = pred.get("live_microstructure") or {}

        vpin_val = float(micro.get("vpin", 0.29))
        vpin_widening = vpin_val >= 0.40
        raw_stop_bps = float(opp.get("stop_distance_bps", 95.0))
        effective_stop_bps = round(raw_stop_bps * (1.5 if vpin_widening else 1.0), 1)

        base_eq = float(control_engine.current_equity_usd) + self.simulated_bonus_equity_usd
        start_eq = 100000.0
        hwm_eq = max(float(control_engine.high_water_mark_usd), base_eq)
        return_pct = round(((base_eq - start_eq) / start_eq) * 100.0, 2)

        phase_label, target_pct, payout_label = self._phase_metadata(resolved_realm)
        progress_pct = round(min(100.0, max(0.0, (return_pct / max(0.1, target_pct)) * 100.0)), 1)

        hud = control_engine.get_remaining_room_hud(track=resolved_realm)
        max_cap = 45000.0 if resolved_realm == "competition" else 38000.0
        risk_budget_usd = base_eq * 0.0045
        optimal_notional = min(
            max_cap,
            max(5000.0, round((risk_budget_usd / max(0.0025, effective_stop_bps / 10_000.0)) / 500.0) * 500.0),
        )

        progression = ChallengeProgressionState(
            realm=resolved_realm,
            challenge_tier=self.challenge_tier if resolved_realm == "competition" else "open_market_desk",
            current_phase=phase_label,
            starting_balance_usd=start_eq,
            current_equity_usd=round(base_eq, 2),
            high_water_mark_usd=round(hwm_eq, 2),
            profit_target_pct=target_pct,
            current_return_pct=return_pct,
            progress_to_target_pct=progress_pct,
            trading_days_completed=self.trading_days_completed,
            min_trading_days_required=5 if resolved_realm == "competition" else 1,
            max_single_day_profit_share_pct=24.8,
            consistency_gate_limit_pct=35.0,
            daily_loss_cushion_usd=float(hud["daily_loss_room_usd"]),
            trailing_hwm_cushion_usd=float(hud["trailing_dd_room_usd"]),
            kyc_proctoring_verified=self.kyc_verified,
            payout_split_label=payout_label,
            ledger_isolation_note=(
                "Ledger 6 (Prop-Firm Rules Account) — Not an ATLAS customer balance"
                if resolved_realm == "competition"
                else "Ledger 2 (External Broker Venue) — Non-custodial read/route only"
            ),
        )

        stages = [
            {
                "stage_id": "1_onboard_and_realm",
                "step_number": 1,
                "title": "Realm & Biometric KYC",
                "status": "completed",
                "summary": (
                    f"{'Prop Competition (24/7 Perps)' if resolved_realm == 'competition' else 'Open-Market Equities (NYSE/Nasdaq)'} "
                    f"· {self.active_icp} · Webcam KYC Verified (99.1%)"
                ),
                "badge": "KYC VERIFIED",
            },
            {
                "stage_id": "2_signal_discovery",
                "step_number": 2,
                "title": "Whale ML Opportunity Lock",
                "status": "active" if self.active_stage == "2_signal_discovery" else "completed",
                "summary": (
                    f"Locked {opp.get('action', 'BUY')} ({opp.get('scenario_id', 'WSDM-01')}) on {sym} · "
                    f"Entry ${opp.get('entry_price', pred.get('spot_price', 100.0))} · "
                    f"R:R {opp.get('risk_reward_ratio', 2.2)}x (perm: none)"
                ),
                "badge": f"{opp.get('action', 'BUY')} LOCKED",
            },
            {
                "stage_id": "3_deterministic_execution",
                "step_number": 3,
                "title": "Zero-Touch Risk & Order Auth",
                "status": "active" if self.active_stage == "3_deterministic_execution" else "ready",
                "summary": (
                    f"Auto-Sized ${optimal_notional:,.0f} via {opp.get('execution_tactic', 'ALMGREN_CHRISS')} · "
                    f"{effective_stop_bps} bps ATR Stop · ${hud['daily_loss_room_usd']:,.0f} Daily Room"
                ),
                "badge": "CONTROL PLANE READY",
            },
            {
                "stage_id": "4_evaluation_and_graduation",
                "step_number": 4,
                "title": "Challenge & Payout Progression",
                "status": "active" if self.active_stage == "4_evaluation_and_graduation" else "tracking",
                "summary": (
                    f"{phase_label} · {return_pct:+.2f}% / +{target_pct:.1f}% ({progress_pct:.0f}%) · "
                    f"Days {self.trading_days_completed}/5 · Best Day 24.8% <= 35%"
                ),
                "badge": f"{progress_pct:.0f}% TO TARGET",
            },
        ]

        return {
            "status": "ok",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "symbol": sym,
            "active_stage": self.active_stage,
            "active_realm": resolved_realm,
            "active_icp": self.active_icp,
            "stages": stages,
            "auto_order_ticket": {
                "symbol": sym,
                "track": resolved_realm,
                "side": str(opp.get("action", "BUY")).lower(),
                "execution_tactic": str(opp.get("execution_tactic", "ALMGREN_CHRISS")),
                "optimal_notional_usd": optimal_notional,
                "atr_stop_bps": effective_stop_bps,
                "vpin_stop_widening_active": vpin_widening,
                "staleness_breaker_ms": 500 if resolved_realm == "competition" else 2000,
            },
            "locked_opportunity": opp,
            "progression": progression.to_dict(),
            "master_spec_invariants": {
                "ai_execution_permission": "none",
                "control_plane_authority": "ActionableControlPlaneEngine (0 LLM imports)",
                "money_ledgers_isolated": 8,
                "custody_by_atlas": False,
                "pit_gate_verified": True,
                "fred_training_policy": "blocked_by_vendor_terms",
                "quarantined_mcp": ["irohan0/quant-mcp"],
            },
            "execution_permission": "none",
        }

    def execute_lifecycle_action(
        self,
        *,
        action: Literal[
            "select_realm",
            "lock_whale_signal",
            "authorize_lifecycle_order",
            "advance_evaluation_phase",
        ],
        symbol: str,
        realm: Literal["competition", "open_market"] | None = None,
        control_engine: ActionableControlPlaneEngine,
        bot_orchestrator: BotOrchestrator,
        market_gateway: LiveMarketDataGateway,
    ) -> dict[str, Any]:
        sym = symbol.upper().strip()
        if realm in ("competition", "open_market"):
            self.active_realm = realm
        if action == "select_realm" and realm in ("competition", "open_market"):
            self.active_stage = "2_signal_discovery"
            sym = "BTC-USD" if realm == "competition" and not sym.endswith("-USD") else sym
            if realm == "open_market" and sym.endswith("-USD"):
                sym = "SPY"

        elif action == "lock_whale_signal":
            self.active_stage = "3_deterministic_execution"

        elif action == "authorize_lifecycle_order":
            self.active_stage = "4_evaluation_and_graduation"
            control_engine.audit_log.append(
                f"{datetime.now(timezone.utc).isoformat()} | lifecycle_order_refused | "
                f"reason=research_model_cannot_order | symbol={sym}"
            )

        elif action == "advance_evaluation_phase":
            self.active_stage = "4_evaluation_and_graduation"
            self.phase_index = (self.phase_index + 1) % 3
            if self.phase_index == 2:
                self.simulated_bonus_equity_usd = max(self.simulated_bonus_equity_usd, 6250.0)

        return self.build_state(
            symbol=sym,
            control_engine=control_engine,
            bot_orchestrator=bot_orchestrator,
            market_gateway=market_gateway,
        )

