"""Provider adapters. ALL DISABLED BY DEFAULT and none perform network I/O.
Real integrations (IBKR, Kraken, Coinbase, Canadian banks/Payments Canada
rails) are PROPOSED; their `_live_submit` deliberately raises."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

class ProviderDisabled(RuntimeError): ...

@dataclass(frozen=True)
class Rail:
    code: str
    currencies: tuple
    max_per_txn_cad: Decimal | None
    settlement: str
    crypto: bool = False

# Limits are illustrative placeholders, not bank-confirmed values.
RAILS = {
    "EFT": Rail("EFT", ("CAD",), None, "T+1..T+3 batch (Payments Canada ACSS)"),
    "WIRE": Rail("WIRE", ("CAD", "USD"), None, "same day (Lynx for CAD / SWIFT for USD)"),
    "INTERAC": Rail("INTERAC", ("CAD",), Decimal("3000"), "near real-time; bank-set limits"),
    "LYNX": Rail("LYNX", ("CAD",), None, "real-time gross (placeholder: bank-initiated only)"),
    "RTR": Rail("RTR", ("CAD",), None, "Real-Time Rail (PLACEHOLDER: not yet generally available)"),
    "CRYPTO": Rail("CRYPTO", ("BTC", "ETH", "USDC"), None, "on-chain", crypto=True),
    "INTERNAL": Rail("INTERNAL", ("CAD", "USD"), None, "bank<->broker funding (via broker deposit instructions)"),
}

@dataclass
class Adapter:
    name: str
    rails: tuple
    enabled: bool = False
    simulate: bool = True
    submitted: list = field(default_factory=list)

    def submit(self, transfer: dict) -> str:
        if not self.enabled:
            raise ProviderDisabled(f"adapter {self.name} is disabled")
        if transfer["rail"] not in self.rails:
            raise ValueError(f"{self.name} does not support rail {transfer['rail']}")
        if not self.simulate:
            return self._live_submit(transfer)
        ref = f"SIM-{self.name}-" + hashlib.sha256(transfer["idem_key"].encode()).hexdigest()[:12]
        self.submitted.append((ref, transfer))
        return ref

    def _live_submit(self, transfer: dict) -> str:
        raise NotImplementedError("live provider calls are not implemented (simulation only)")

def default_adapters() -> dict[str, Adapter]:
    return {
        "bank": Adapter("bank", ("EFT", "WIRE", "INTERAC", "LYNX", "RTR", "INTERNAL")),
        "ibkr": Adapter("ibkr", ("INTERNAL", "WIRE")),
        "kraken": Adapter("kraken", ("INTERNAL", "WIRE", "CRYPTO")),
        "coinbase": Adapter("coinbase", ("INTERNAL", "WIRE", "CRYPTO")),
    }
