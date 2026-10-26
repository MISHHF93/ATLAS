"""Confirmed transaction monitoring, reconciliation, and continuous strategy/model performance evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..indexing import CONFIRMATION_RANK, ConfirmationLevel


@dataclass
class MonitoredTransaction:
    signature: str
    client_order_id: str
    mint: str
    side: str
    submitted_slot: int
    submitted_ts: float
    confirmation_level: ConfirmationLevel = "processed"
    confirmed_slot: int | None = None
    finalized_slot: int | None = None
    on_chain_error: str | None = None
    reconciled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PumpMonitoringService:
    """Monitors transaction confirmation progression (`processed` -> `confirmed` -> `finalized`) and model/strategy KPIs."""

    def __init__(self) -> None:
        self._txs: dict[str, MonitoredTransaction] = {}
        self._outcomes: list[dict[str, Any]] = []

    def track_submission(
        self,
        *,
        signature: str,
        client_order_id: str,
        mint: str,
        side: str,
        slot: int,
        ts: float,
        initial_confirmation: ConfirmationLevel = "confirmed",
    ) -> MonitoredTransaction:
        tx = MonitoredTransaction(
            signature=signature,
            client_order_id=client_order_id,
            mint=mint,
            side=side,
            submitted_slot=int(slot),
            submitted_ts=float(ts),
            confirmation_level=initial_confirmation,
            confirmed_slot=int(slot) if CONFIRMATION_RANK.get(initial_confirmation, 0) >= 2 else None,
            finalized_slot=int(slot) if initial_confirmation == "finalized" else None,
            reconciled=CONFIRMATION_RANK.get(initial_confirmation, 0) >= 2,
        )
        self._txs[signature] = tx
        return tx

    def update_confirmation(
        self,
        signature: str,
        *,
        confirmation_level: ConfirmationLevel,
        slot: int,
        on_chain_error: str | None = None,
    ) -> MonitoredTransaction:
        tx = self._txs[signature]
        if on_chain_error:
            tx.on_chain_error = on_chain_error
            tx.reconciled = False
            return tx
        if CONFIRMATION_RANK.get(confirmation_level, 0) >= CONFIRMATION_RANK.get(tx.confirmation_level, 0):
            tx.confirmation_level = confirmation_level
        if confirmation_level == "confirmed":
            tx.confirmed_slot = int(slot)
            tx.reconciled = True
        elif confirmation_level == "finalized":
            tx.confirmed_slot = tx.confirmed_slot or int(slot)
            tx.finalized_slot = int(slot)
            tx.reconciled = True
        return tx

    def record_outcome(
        self,
        *,
        mint: str,
        strategy: str,
        predicted_prob_win: float,
        predicted_net_ev_bps: float,
        realized_net_pnl_bps: float,
        won: bool,
        ts: float,
    ) -> None:
        self._outcomes.append({
            "mint": mint,
            "strategy": strategy,
            "predicted_prob_win": float(predicted_prob_win),
            "predicted_net_ev_bps": float(predicted_net_ev_bps),
            "realized_net_pnl_bps": float(realized_net_pnl_bps),
            "won": bool(won),
            "ts": float(ts),
        })

    def performance_summary(self) -> dict[str, Any]:
        if not self._outcomes:
            return {
                "recorded_outcomes": 0,
                "win_rate": None,
                "brier_score": None,
                "mean_predicted_ev_bps": None,
                "mean_realized_net_bps": None,
                "by_strategy": {},
            }
        n = len(self._outcomes)
        wins = sum(1 for o in self._outcomes if o["won"])
        brier = sum((o["predicted_prob_win"] - (1.0 if o["won"] else 0.0)) ** 2 for o in self._outcomes) / n
        pred_ev = sum(o["predicted_net_ev_bps"] for o in self._outcomes) / n
        real_ev = sum(o["realized_net_pnl_bps"] for o in self._outcomes) / n
        by_strat: dict[str, dict[str, Any]] = {}
        for s in sorted({o["strategy"] for o in self._outcomes}):
            rows = [o for o in self._outcomes if o["strategy"] == s]
            by_strat[s] = {
                "count": len(rows),
                "win_rate": round(sum(1 for r in rows if r["won"]) / len(rows), 4),
                "mean_realized_net_bps": round(sum(r["realized_net_pnl_bps"] for r in rows) / len(rows), 2),
            }
        return {
            "recorded_outcomes": n,
            "win_rate": round(wins / n, 4),
            "brier_score": round(brier, 4),
            "mean_predicted_ev_bps": round(pred_ev, 2),
            "mean_realized_net_bps": round(real_ev, 2),
            "by_strategy": by_strat,
        }

    def transactions(self) -> list[dict[str, Any]]:
        return [t.as_dict() for t in self._txs.values()]

