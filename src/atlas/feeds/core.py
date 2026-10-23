"""ATLAS feed core: the normalized record types, the provider plugin interface, capability manifests, and a
rate-limited HTTP helper with retry/backoff. Every provider adapter speaks these types; nothing downstream
(charts/UDF, detectors, predict, training, replay, autopilot) sees a provider-specific payload."""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@dataclass(frozen=True)
class FeedBar:
    """One normalized OHLCV bar. ``event_time`` = bar start (UTC epoch s); ``bar_end`` = start + interval.
    ``receipt_time`` = when ATLAS received this version. ``confirmed`` is True only if received at/after bar_end
    and the provider marks it final (or, for history, it is strictly in the past)."""
    instrument: str          # ATLAS instrument id, e.g. "BTCUSDT" / "SPY"
    interval: str
    event_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    receipt_time: int
    confirmed: bool
    provider_symbol: str = ""

    @property
    def bar_end(self) -> int:
        return self.event_time + INTERVALS[self.interval]

    def valid(self) -> bool:
        vals = (self.open, self.high, self.low, self.close)
        return all(v == v and v > 0 for v in vals) and self.high >= max(self.open, self.close, self.low) \
            and self.low <= min(self.open, self.close) and self.volume >= 0


@dataclass(frozen=True)
class FeedTrade:
    instrument: str
    event_time: float
    price: float
    size: float
    provider: str
    receipt_time: float
    side: str | None = None


@dataclass(frozen=True)
class FeedQuote:
    instrument: str
    event_time: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    provider: str
    receipt_time: float


@dataclass(frozen=True)
class FeedObservation:
    """Macro/series value with ALFRED-style vintages: realtime_start is when the value became known."""
    series: str
    date: str
    value: float | None
    realtime_start: str
    provider: str
    receipt_time: int


@dataclass(frozen=True)
class Capabilities:
    """Capability manifest for one provider plugin."""
    name: str
    title: str
    status: str                              # working | interface_fixture_tested | documented_stub
    asset_classes: tuple[str, ...]
    schemas: tuple[str, ...]                 # bars | trades | quotes | series | ...
    intervals: tuple[str, ...]
    history_depth: str
    live_stream: str                         # "websocket: <url>" | "none" | "polling"
    rate_limits: str
    auth_env: tuple[str, ...]                # env var NAMES only; empty = keyless
    official_docs: tuple[str, ...]
    terms_url: str
    unofficial: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Health:
    provider: str
    enabled: bool
    reason: str | None = None                # e.g. missing_env:ALPACA_API_KEY_ID, geo_blocked
    last_ok: int | None = None
    last_error: str | None = None
    last_error_at: int | None = None
    consecutive_errors: int = 0
    requests: int = 0
    rate_limited: int = 0
    stream_connected: bool = False
    reconnects: int = 0
    last_message_at: int | None = None


class ProviderError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, retryable: bool = False, geo_blocked: bool = False):
        super().__init__(msg)
        self.status, self.retryable, self.geo_blocked = status, retryable, geo_blocked


Transport = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float = 20.0) -> tuple[int, Mapping[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-feed/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class RateLimiter:
    """Token bucket: ``rate`` requests per ``per`` seconds."""

    def __init__(self, rate: float, per: float = 1.0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate, self.per, self.clock, self.sleep = rate, per, clock, sleep
        self.tokens, self.t = rate, clock()

    def acquire(self) -> None:
        now = self.clock()
        self.tokens = min(self.rate, self.tokens + (now - self.t) * self.rate / self.per)
        self.t = now
        if self.tokens < 1:
            self.sleep((1 - self.tokens) * self.per / self.rate)
            self.tokens, self.t = 1, self.clock()
        self.tokens -= 1


def backoff_delays(base: float = 0.5, cap: float = 60.0, attempts: int = 8, jitter: Callable[[], float] = random.random) -> Iterator[float]:
    """Exponential backoff with full jitter: used by HTTP retries and websocket reconnects."""
    for i in range(attempts):
        yield min(cap, base * 2 ** i) * (0.5 + 0.5 * jitter())


class ProviderAdapter:
    """Plugin base. Subclasses set ``caps`` and implement ``_history`` (and optionally ``stream``).

    - ``history(instrument, interval, start, end)`` -> list[FeedBar], oldest first, only bars with end <= now
      marked confirmed.
    - ``stream(instruments, interval)`` -> async iterator of FeedBar/FeedTrade/FeedQuote (needs network).
    - ``health()`` -> Health.
    """
    caps: Capabilities
    symbol_map: Mapping[str, str] = {}

    def __init__(self, transport: Transport | None = None, env: Mapping[str, str] | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 limiter: RateLimiter | None = None):
        self.transport = transport or urllib_transport
        self.env = os.environ if env is None else env
        self.clock, self.sleep = clock, sleep
        self.limiter = limiter or RateLimiter(5, 1.0, sleep=sleep)
        self._health = Health(self.caps.name, enabled=False)
        missing = [k for k in self.caps.auth_env if not self.env.get(k)]
        if self.caps.status == "documented_stub":
            self._health.reason = "documented_stub"
        elif missing:
            self._health.reason = "missing_env:" + ",".join(missing)
        else:
            self._health.enabled = True

    # ---- interface ----
    @property
    def name(self) -> str:
        return self.caps.name

    @property
    def enabled(self) -> bool:
        return self._health.enabled

    def health(self) -> Health:
        return self._health

    def provider_symbol(self, instrument: str) -> str:
        return self.symbol_map.get(instrument, instrument)

    def supports(self, instrument_asset_class: str, interval: str) -> bool:
        return instrument_asset_class in self.caps.asset_classes and interval in self.caps.intervals

    def history(self, instrument: str, interval: str, start: int, end: int) -> list[FeedBar]:
        if not self.enabled:
            raise ProviderError(f"{self.name} disabled: {self._health.reason}")
        now = int(self.clock())
        bars = self._history(instrument, interval, int(start), int(min(end, now)), now)
        out = {}
        for b in bars:
            if b.valid() and start <= b.event_time < end:
                out[b.event_time] = b
        return [out[k] for k in sorted(out)]

    def _history(self, instrument: str, interval: str, start: int, end: int, now: int) -> list[FeedBar]:
        raise NotImplementedError

    async def stream(self, instruments: Sequence[str], interval: str):     # pragma: no cover - network
        raise ProviderError(f"{self.name}: live stream not implemented", retryable=False)
        yield  # noqa

    def _bar(self, instrument, interval, t, o, h, l_, c, v, now, final: bool | None = None) -> FeedBar:
        t = int(t)
        confirmed = (t + INTERVALS[interval] <= now) if final is None else (final and t + INTERVALS[interval] <= now)
        return FeedBar(instrument, interval, t, float(o), float(h), float(l_), float(c), float(v or 0), self.name, now,
                       confirmed, self.provider_symbol(instrument))

    # ---- HTTP with rate limit + retry ----
    def get_json(self, url: str, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None,
                 attempts: int = 5) -> Any:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        last: ProviderError | None = None
        delays = backoff_delays(attempts=attempts)
        for _ in range(attempts):
            self.limiter.acquire()
            self._health.requests += 1
            try:
                status, hdrs, body = self.transport(url, headers or {})
            except OSError as e:
                status, hdrs, body = None, {}, str(e).encode()
            now = int(self.clock())
            if status == 200:
                self._health.last_ok, self._health.consecutive_errors = now, 0
                return json.loads(body)
            geo = status in (451,) or (status == 403 and b"country" in (body or b"").lower())
            quota = b"quota violation" in (body or b"").lower()   # Tradier signals rate limit as HTTP 400
            retry = quota or status is None or status == 429 or status == 418 or (status is not None and status >= 500)
            if status in (429, 418) or quota:
                self._health.rate_limited += 1
            err = ProviderError(f"{self.name} HTTP {status}: {(body or b'')[:160]!r}", status, retry, geo)
            self._health.last_error, self._health.last_error_at = str(err), now
            self._health.consecutive_errors += 1
            last = err
            if not retry:
                break
            ra = (hdrs or {}).get("Retry-After") or (hdrs or {}).get("retry-after")
            d = next(delays, 30.0)
            self.sleep(float(ra) if ra and str(ra).replace(".", "").isdigit() else d)
        assert last is not None
        raise last


def chunks(start: int, end: int, step: int) -> Iterable[tuple[int, int]]:
    t = start
    while t < end:
        yield t, min(end, t + step)
        t += step
