"""Real-time Solana RPC & WebSocket event indexer with deduplication, slot ordering, chain-reorg rollback, and freshness tracking."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from atlas.feeds.core import RateLimiter

ConfirmationLevel = str  # "processed" | "confirmed" | "finalized"
CONFIRMATION_RANK = {"processed": 1, "confirmed": 2, "finalized": 3}


@dataclass(frozen=True)
class IndexedChainEvent:
    """One normalized on-chain Solana / Pump.fun / PumpSwap event."""
    signature: str
    slot: int
    tx_index: int
    instruction_index: int
    event_type: str  # "token_create" | "curve_trade" | "curve_complete" | "post_complete_buy" | "pool_create" | "pool_swap" | "account_update"
    mint: str
    program_id: str
    event_time: float
    receipt_time: float
    confirmation: ConfirmationLevel = "confirmed"
    parent_slot: int = 0
    block_hash: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> tuple[str, int, str]:
        return (self.signature, self.instruction_index, self.event_type)

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.slot, self.tx_index, self.instruction_index)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_rpc_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "atlas-solana-indexer/1.0", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read()


class SolanaRPCIndexer:
    """Authorized Solana JSON-RPC + event stream indexer with slot-reorg handling and rate limiting."""

    def __init__(
        self,
        rpc_url: str | None = None,
        ws_url: str | None = None,
        *,
        transport: Callable[[str, bytes, Mapping[str, str]], tuple[int, bytes]] | None = None,
        clock: Callable[[], float] = time.time,
        rate_per_sec: float = 10.0,
    ) -> None:
        self.rpc_url = (rpc_url or os.environ.get("SOLANA_RPC_URL") or "").strip()
        self.ws_url = (ws_url or os.environ.get("SOLANA_WS_URL") or "").strip()
        self.transport = transport or _default_rpc_transport
        self.clock = clock
        self.limiter = RateLimiter(rate_per_sec, 1.0, sleep=lambda _s: None)
        self._seen_keys: dict[tuple[str, int, str], IndexedChainEvent] = {}
        self._slot_hashes: dict[int, str] = {}
        self._events_by_slot: dict[int, list[IndexedChainEvent]] = {}
        self.reorg_rollbacks: list[dict[str, Any]] = []
        self.missed_slot_backfills: list[dict[str, Any]] = []
        self.reconnect_count: int = 0
        self.rpc_requests: int = 0
        self.rpc_errors: int = 0
        self.last_slot: int = 0
        self.last_event_receipt_ts: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.rpc_url)

    def rpc_call(self, method: str, params: list[Any] | None = None) -> Any:
        """Execute a JSON-RPC 2.0 call against the configured Solana RPC endpoint."""
        if not self.rpc_url:
            raise RuntimeError("SOLANA_RPC_URL is not configured")
        self.limiter.acquire()
        self.rpc_requests += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self.rpc_requests, "method": method, "params": params or []}).encode()
        try:
            status, raw = self.transport(self.rpc_url, payload, {})
        except Exception as exc:
            self.rpc_errors += 1
            raise RuntimeError(f"Solana RPC transport error on {method}: {exc}") from exc
        if status != 200:
            self.rpc_errors += 1
            raise RuntimeError(f"Solana RPC HTTP {status} on {method}")
        parsed = json.loads(raw.decode("utf-8"))
        if "error" in parsed and parsed["error"]:
            self.rpc_errors += 1
            raise RuntimeError(f"Solana RPC error on {method}: {parsed['error']}")
        return parsed.get("result")

    def ingest_event(self, event: IndexedChainEvent) -> bool:
        """Ingest one event with deduplication, slot-gap detection, and chain-reorg rollback."""
        # Detect chain reorganization on unfinalized slots if block_hash changed for an existing slot
        prev_hash = self._slot_hashes.get(event.slot)
        if prev_hash and event.block_hash and prev_hash != event.block_hash:
            self._rollback_from_slot(event.slot, reason=f"block_hash mismatch {prev_hash} != {event.block_hash}")

        # Detect missed slot gap
        if self.last_slot > 0 and event.slot > self.last_slot + 1:
            self.missed_slot_backfills.append(
                {"from_slot": self.last_slot + 1, "to_slot": event.slot - 1, "detected_at": self.clock()}
            )

        existing = self._seen_keys.get(event.dedup_key)
        if existing is not None:
            # Upgrade confirmation level if higher (e.g. processed -> confirmed -> finalized)
            if CONFIRMATION_RANK.get(event.confirmation, 0) > CONFIRMATION_RANK.get(existing.confirmation, 0):
                self._seen_keys[event.dedup_key] = event
                slot_list = self._events_by_slot.get(event.slot, [])
                for i, e in enumerate(slot_list):
                    if e.dedup_key == event.dedup_key:
                        slot_list[i] = event
            return False

        self._seen_keys[event.dedup_key] = event
        if event.block_hash:
            self._slot_hashes[event.slot] = event.block_hash
        self._events_by_slot.setdefault(event.slot, []).append(event)
        self._events_by_slot[event.slot].sort(key=lambda e: e.sort_key)
        self.last_slot = max(self.last_slot, int(event.slot))
        self.last_event_receipt_ts = max(self.last_event_receipt_ts, float(event.receipt_time))
        return True

    def _rollback_from_slot(self, fork_slot: int, *, reason: str) -> int:
        """Roll back unfinalized events at or after ``fork_slot`` when a slot fork/reorg occurs."""
        removed = 0
        for s in [s for s in list(self._events_by_slot) if s >= fork_slot]:
            kept: list[IndexedChainEvent] = []
            for ev in self._events_by_slot[s]:
                if ev.confirmation == "finalized":
                    kept.append(ev)
                else:
                    self._seen_keys.pop(ev.dedup_key, None)
                    removed += 1
            if kept:
                self._events_by_slot[s] = kept
            else:
                self._events_by_slot.pop(s, None)
                self._slot_hashes.pop(s, None)
        self.reorg_rollbacks.append({"fork_slot": fork_slot, "removed_events": removed, "reason": reason, "ts": self.clock()})
        return removed

    def record_reconnect(self) -> None:
        self.reconnect_count += 1

    def ordered_events(
        self,
        *,
        mint: str | None = None,
        min_confirmation: ConfirmationLevel = "processed",
        up_to_time: float | None = None,
    ) -> list[IndexedChainEvent]:
        """Return deterministically slot-ordered events filtered by mint, confirmation, and point-in-time cutoff."""
        min_rank = CONFIRMATION_RANK.get(min_confirmation, 1)
        out: list[IndexedChainEvent] = []
        for slot in sorted(self._events_by_slot):
            for ev in self._events_by_slot[slot]:
                if CONFIRMATION_RANK.get(ev.confirmation, 0) < min_rank:
                    continue
                if mint is not None and ev.mint != mint:
                    continue
                if up_to_time is not None and ev.event_time > up_to_time:
                    continue
                out.append(ev)
        return out

    def events_for_mint(self, mint: str, *, min_confirmation: ConfirmationLevel = "processed") -> list[IndexedChainEvent]:
        return self.ordered_events(mint=mint, min_confirmation=min_confirmation)

    def freshness(self, now: float | None = None, max_age_seconds: float = 30.0) -> dict[str, Any]:
        now_ts = float(self.clock() if now is None else now)
        if self.last_event_receipt_ts <= 0:
            return {"fresh": False, "age_seconds": None, "last_slot": self.last_slot, "status": "no_events"}
        age = max(0.0, now_ts - self.last_event_receipt_ts)
        return {
            "fresh": age <= max_age_seconds,
            "age_seconds": round(age, 3),
            "last_slot": self.last_slot,
            "status": "fresh" if age <= max_age_seconds else "stale",
            "reorg_rollbacks": len(self.reorg_rollbacks),
            "missed_slot_backfills": len(self.missed_slot_backfills),
            "reconnect_count": self.reconnect_count,
        }

