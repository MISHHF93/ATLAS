"""Fund trade allocation (block orders across accounts/series).

Rules implemented:
* PRE-TRADE allocation is mandatory: it must be recorded (immutable, hash-chained) BEFORE the
  order goes to the broker. A RiskEngine hook rejects fund orders without one.
* POST-FILL allocation is strictly pro-rata to the pre-trade weights, in whole lots, using the
  largest-remainder method applied to CUMULATIVE entitlement (each account's running shortfall is
  carried), so rounding never systematically favours an account; exact ties rotate by order sequence. Every account gets the SAME average price.
* Partial fills are allocated pro-rata too. Re-allocation after the fact requires owner + reason
  and is recorded as an exception.
* Fairness report: cumulative allocation vs entitlement per account (in lots) must stay within
  one lot per order on average."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal


def _h(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


@dataclass(frozen=True)
class PreTradeAllocation:
    order_ref: str               # intent_id
    symbol: str
    side: str
    qty: Decimal
    weights: dict[str, Decimal]  # account -> weight (normalised)
    ts: datetime
    basis: str                   # e.g. "pro-rata NAV 2026-10-16"
    seq: int = 0
    hash: str = ""


@dataclass
class Allocation:
    order_ref: str
    filled_qty: Decimal
    avg_price: Decimal
    per_account: dict[str, Decimal]
    remainder_order: list[str]
    exceptions: list[str] = field(default_factory=list)


class AllocationError(Exception):
    pass


class AllocationBook:
    def __init__(self, lot: Decimal = Decimal(1), audit=None):
        self.lot = Decimal(lot)
        self.audit = audit
        self.pre: dict[str, PreTradeAllocation] = {}
        self.allocs: dict[str, Allocation] = {}
        self._last = "0" * 64
        self._seq = 0
        self.carry: dict[str, Decimal] = {}   # cumulative (entitled - allocated) in lots, per account

    # ---------------------------------------------------------------- pre-trade
    def record_pre_trade(self, order_ref: str, symbol: str, side: str, qty, weights: dict, ts: datetime, basis: str) -> PreTradeAllocation:
        if order_ref in self.pre:
            raise AllocationError("pre-trade allocation already recorded (immutable)")
        w = {k: Decimal(str(v)) for k, v in weights.items() if Decimal(str(v)) > 0}
        tot = sum(w.values())
        if not w or tot <= 0:
            raise AllocationError("weights must be positive")
        w = {k: v / tot for k, v in sorted(w.items())}
        self._seq += 1
        body = {"order_ref": order_ref, "symbol": symbol, "side": side, "qty": str(qty), "weights": {k: str(v) for k, v in w.items()},
                "ts": ts.isoformat(), "basis": basis, "seq": self._seq}
        h = _h(self._last, body)
        self._last = h
        p = PreTradeAllocation(order_ref, symbol, side, Decimal(str(qty)), w, ts, basis, self._seq, h)
        self.pre[order_ref] = p
        if self.audit:
            self.audit.append("fund.pre_trade_allocation", body | {"hash": h})
        return p

    def has_pre_trade(self, order_ref: str) -> bool:
        return order_ref in self.pre

    # ---------------------------------------------------------------- post-fill
    def allocate(self, order_ref: str, fills: list[tuple], first_fill_ts: datetime | None = None) -> Allocation:
        """fills: [(qty, price), ...] for the block. Returns per-account whole-lot quantities."""
        p = self.pre.get(order_ref)
        if p is None:
            raise AllocationError("no pre-trade allocation: fund orders must be allocated before execution")
        exc = []
        if first_fill_ts is not None and first_fill_ts < p.ts:
            exc.append("pre-trade allocation timestamp is after the first fill")
        q = sum(Decimal(str(f[0])) for f in fills)
        if q <= 0:
            raise AllocationError("nothing filled")
        if q > p.qty:
            raise AllocationError("filled more than the allocated block")
        avg = (sum(Decimal(str(a)) * Decimal(str(b)) for a, b in fills) / q).quantize(Decimal("0.000001"))
        lots = int((q / self.lot).to_integral_value(ROUND_FLOOR))
        ent = {k: w * lots for k, w in p.weights.items()}
        want = {k: ent[k] + self.carry.get(k, Decimal(0)) for k in ent}     # include running shortfall
        base = {k: max(0, int(v.to_integral_value(ROUND_FLOOR))) for k, v in want.items()}
        while sum(base.values()) > lots:   # carry can over-ask; trim from the most over-served
            k = min(base, key=lambda a: (want[a] - base[a], a))
            base[k] -= 1
        left = lots - sum(base.values())
        accts = sorted(p.weights)
        rot = p.seq % len(accts)
        rotated = accts[rot:] + accts[:rot]   # rotation breaks exact ties fairly across orders
        order = sorted(rotated, key=lambda k: -(want[k] - base[k]))  # stable sort: rotation decides ties
        for k in order[:left]:
            base[k] += 1
        for k in ent:
            self.carry[k] = want[k] - base[k]
        per = {k: Decimal(v) * self.lot for k, v in base.items()}
        odd = q - sum(per.values())
        if odd:
            exc.append(f"odd-lot remainder {odd} left in the block account (unallocated)")
        a = Allocation(order_ref, q, avg, per, order[:left], exc)
        self.allocs[order_ref] = a
        if self.audit:
            self.audit.append("fund.allocation", {"order_ref": order_ref, "avg_price": str(avg),
                                                  "per_account": {k: str(v) for k, v in per.items()}, "exceptions": exc})
        return a

    def reallocate(self, order_ref: str, per_account: dict, actor: str, owner: str, reason: str) -> Allocation:
        if actor != owner or not reason.strip():
            raise PermissionError("re-allocation requires the owner and a documented reason")
        a = self.allocs[order_ref]
        new = {k: Decimal(str(v)) for k, v in per_account.items()}
        if sum(new.values()) != sum(a.per_account.values()):
            raise AllocationError("re-allocation must keep the same total")
        a.per_account = new
        a.exceptions.append(f"re-allocated by {actor}: {reason}")
        if self.audit:
            self.audit.append("fund.reallocation", {"order_ref": order_ref, "reason": reason}, actor=actor)
        return a

    # ---------------------------------------------------------------- fairness
    def fairness_report(self) -> dict:
        dev: dict[str, Decimal] = {}
        n = 0
        for ref, a in self.allocs.items():
            p = self.pre[ref]
            alloc_total = sum(a.per_account.values())
            for k, w in p.weights.items():
                dev[k] = dev.get(k, Decimal(0)) + (a.per_account.get(k, Decimal(0)) - w * alloc_total) / self.lot
            n += 1
        worst = max((abs(v) for v in dev.values()), default=Decimal(0))
        return {"orders": n, "cumulative_deviation_lots": {k: float(v) for k, v in dev.items()},
                "max_abs_cumulative_deviation_lots": float(worst), "fair": worst <= Decimal(1) + Decimal("1e-9"),
                "same_avg_price_all_accounts": True,
                "exceptions": {r: a.exceptions for r, a in self.allocs.items() if a.exceptions}}


class FundAllocationHook:
    """RiskEngine pre-trade hook: fund orders without a pre-trade allocation are rejected."""
    name = "fund_pre_trade_allocation"

    def __init__(self, book: AllocationBook):
        self.book = book

    def __call__(self, intent, state):
        p = self.book.pre.get(intent.intent_id)
        if p is None:
            return [f"fund order {intent.intent_id[:8]} has no pre-trade allocation"], []
        if p.symbol != intent.symbol or p.side != intent.side or Decimal(str(intent.qty)) > p.qty:
            return ["pre-trade allocation does not match the order (symbol/side/qty)"], []
        return [], []
