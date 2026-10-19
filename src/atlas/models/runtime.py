"""Bounded async calls with per-adapter admission control and observable costs.

One runtime belongs to one provider/account quota scope on one event loop.
Remote cancellation is not guaranteed by a client timeout. No implicit fallback.
"""
import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

from pydantic import Field

from atlas.models.schemas import Record, Usage

T = TypeVar("T")


class TransientProviderError(RuntimeError):
    def __init__(self, message: str = "Transient provider failure", *, retry_after: float = 0) -> None:
        super().__init__(message)
        self.retry_after = max(0, retry_after)


class CircuitOpen(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class CallPolicy(Record):
    timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    attempts: int = Field(default=3, ge=1, le=5)
    requests_per_minute: int = Field(default=30, gt=0)
    tokens_per_minute: int | None = Field(default=None, gt=0)
    failure_threshold: int = Field(default=3, gt=0)
    cooldown_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    backoff_seconds: float = Field(default=0.25, ge=0, allow_inf_nan=False)


@dataclass(frozen=True)
class CallEvent:
    operation: str
    attempt: int
    latency_ms: float
    outcome: str
    usage: Usage


class ProviderRuntime:
    def __init__(self, policy: CallPolicy | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.policy = policy or CallPolicy()
        self._clock = clock
        self._lock = asyncio.Lock()
        self._requests: deque[tuple[float, int]] = deque()
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self.events: list[CallEvent] = []

    async def _admit(self, reserved_tokens: int) -> bool:
        async with self._lock:
            now = self._clock()
            probe = False
            if self._opened_at is not None:
                if now - self._opened_at < self.policy.cooldown_seconds or self._probe_in_flight:
                    raise CircuitOpen("Provider circuit is open")
                probe = True
            while self._requests and now - self._requests[0][0] >= 60:
                self._requests.popleft()
            if len(self._requests) >= self.policy.requests_per_minute:
                raise RateLimited("Local request budget exhausted")
            if self.policy.tokens_per_minute is not None:
                if reserved_tokens <= 0:
                    raise ValueError("Token-limited calls require a conservative input + max-output reservation")
                if sum(tokens for _, tokens in self._requests) + reserved_tokens > self.policy.tokens_per_minute:
                    raise RateLimited("Local token budget exhausted")
            self._requests.append((now, reserved_tokens))
            if probe:
                self._probe_in_flight = True
            return probe

    async def _finish(self, success: bool, probe: bool, provider_failure: bool) -> None:
        async with self._lock:
            if probe:
                self._probe_in_flight = False
            if success:
                # An old in-flight success must not close a newly opened circuit.
                if probe or self._opened_at is None:
                    self._failures = 0
                    self._opened_at = None
            elif provider_failure:
                self._failures += 1
                if probe or self._failures >= self.policy.failure_threshold:
                    self._opened_at = self._clock()

    async def call(
        self, operation: str, invoke: Callable[[], Awaitable[T]], *,
        retry_safe: bool = False, reserved_tokens: int = 0,
        usage: Callable[[T], Usage] | None = None,
    ) -> T:
        if reserved_tokens < 0:
            raise ValueError("Negative token reservation")
        deadline = self._clock() + self.policy.timeout_seconds
        for attempt in range(1, self.policy.attempts + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise TimeoutError("Provider call deadline exceeded")
            probe = await self._admit(reserved_tokens)
            started = self._clock()
            try:
                result = await asyncio.wait_for(invoke(), timeout=remaining)
                measured = usage(result) if usage else Usage()
            except asyncio.CancelledError:
                await self._finish(False, probe, False)
                self.events.append(CallEvent(operation, attempt, (self._clock() - started) * 1000, "cancelled", Usage()))
                raise
            except Exception as exc:
                transient = isinstance(exc, (TransientProviderError, TimeoutError))
                await self._finish(False, probe, transient)
                # Failed and timed-out attempts may still be billed: cost remains unknown.
                self.events.append(CallEvent(operation, attempt, (self._clock() - started) * 1000, type(exc).__name__, Usage()))
                if not retry_safe or not transient or attempt == self.policy.attempts:
                    raise
                delay = self.policy.backoff_seconds * 2 ** (attempt - 1) * random.uniform(0.5, 1.5)
                if isinstance(exc, TransientProviderError):
                    delay = max(delay, exc.retry_after)
                if delay >= deadline - self._clock():
                    raise TimeoutError("Retry would exceed provider deadline") from exc
                await asyncio.sleep(delay)
            else:
                await self._finish(True, probe, False)
                self.events.append(CallEvent(operation, attempt, (self._clock() - started) * 1000, "ok", measured))
                return result
        raise AssertionError("Unreachable")

    @property
    def known_cost_usd(self) -> Decimal:
        return sum((event.usage.cost_usd or Decimal(0) for event in self.events), Decimal(0))

    @property
    def unknown_cost_attempts(self) -> int:
        return sum(event.usage.cost_usd is None for event in self.events)
