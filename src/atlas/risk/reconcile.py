"""Internal ledger (built only from fill events) vs broker state. Mismatch => halt."""
from __future__ import annotations

from dataclasses import dataclass, field

from atlas.governance.audit import AuditLog
from atlas.risk.killswitch import KillSwitch


@dataclass
class Ledger:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)

    def apply_fill(self, symbol: str, side: str, qty: float, cash_delta: float) -> None:
        q = self.positions.get(symbol, 0.0) + (qty if side == "buy" else -qty)
        if abs(q) < 1e-12:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = q
        self.cash += cash_delta


def reconcile(ledger: Ledger, broker_positions: dict[str, float], broker_cash: float, ks: KillSwitch,
              audit: AuditLog, qty_tol: float = 1e-9, cash_tol: float = 0.01) -> list[str]:
    diffs: list[str] = []
    for sym in set(ledger.positions) | set(broker_positions):
        a, b = ledger.positions.get(sym, 0.0), broker_positions.get(sym, 0.0)
        if abs(a - b) > qty_tol:
            diffs.append(f"{sym}: ledger {a} != broker {b}")
    if abs(ledger.cash - broker_cash) > cash_tol:
        diffs.append(f"cash: ledger {ledger.cash:.2f} != broker {broker_cash:.2f}")
    audit.append("reconcile", {"ok": not diffs, "diffs": diffs})
    if diffs:
        ks.engage("reconciliation mismatch: " + "; ".join(diffs[:5]), channel="reconciler")
    return diffs
