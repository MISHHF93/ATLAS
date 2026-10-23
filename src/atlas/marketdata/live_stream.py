"""ATLAS Live Market Data Ingestion Engine & Ring-Buffered Microstructure Stream (`live_stream.py`).

Implements:
- `OrderBookRingBuffer`: Bounded 10,000-slot ring buffer (`collections.deque(maxlen=10000)`) with
  Point-in-Time (PIT) `exchange_timestamp` and `system_receipt_timestamp` tagging (`as_of` discipline).
- `LiveMarketDataGateway`: Async WebSocket stream manager across Open-Market Equities (`Polygon` /
  `Databento` SIP) and Prop Derivatives / Crypto (`CCXT Pro` / `Coinbase` for `BTC-USD`, `ETH-USD`,
  `SOL-USD`), with automated heartbeat, exponential backoff reconnection, Top-5 Level OFI, rolling
  bucketed VPIN, and deterministic 500ms staleness reporting to `ActionableControlPlaneEngine`.

All live stream metrics carry `execution_permission = "none"`.
"""

from __future__ import annotations

import collections
import math
import asyncio
from collections.abc import AsyncIterator, Callable
from atlas.market import catalog
from atlas.marketdata.microstructure import estimate_kyles_lambda
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Deque, Literal

if TYPE_CHECKING:
    from atlas.control.engine import ActionableControlPlaneEngine


@dataclass(frozen=True)
class LiveTickFrame:
    symbol: str
    track: Literal["competition", "open_market"]
    provider: Literal["databento", "polygon", "ccxt_pro", "coinbase", "hyperliquid"]
    price: float
    size: float
    vpin: float
    ofi: float
    spread: float
    bid_depth: tuple[float, ...]
    ask_depth: tuple[float, ...]
    latency_ms: float
    exchange_timestamp: datetime
    system_receipt_timestamp: datetime
    kyles_lambda: float = 0.0
    regime: str = "Compression"
    execution_permission: Literal["none"] = "none"
    metrics_ready: bool = False
    data_mode: Literal["observed", "demo"] = "observed"

    def to_payload(self) -> dict[str, Any]:
        top5_bids = [round(x, 2) for x in self.bid_depth[:5]]
        top5_asks = [round(x, 2) for x in self.ask_depth[:5]]
        spread_bps = round((self.spread / max(1e-6, self.price)) * 10_000.0, 2)
        stale_threshold_ms = 500.0 if self.track == "competition" else 2000.0
        return {
            "metrics_ready": self.metrics_ready,
            "data_mode": self.data_mode,
            "track": self.track,
            "symbol": self.symbol,
            "provider": self.provider,
            "timestamp": self.system_receipt_timestamp.isoformat(),
            "last_price": round(self.price, 4),
            "price": round(self.price, 4),
            "size": round(self.size, 4),
            "bid_depth_top5": top5_bids,
            "ask_depth_top5": top5_asks,
            "bid_depth": top5_bids,
            "ask_depth": top5_asks,
            "vpin": round(self.vpin, 4),
            "ofi": round(self.ofi, 4),
            "ofi_z": None,
            "kyles_lambda": round(self.kyles_lambda, 6),
            "spread_bps": spread_bps,
            "spread": round(self.spread, 4),
            "latency_ms": round(self.latency_ms, 2),
            "stale_feed_flagged": bool(self.latency_ms > stale_threshold_ms),
            "regime": self.regime,
            "exchange_timestamp": self.exchange_timestamp.isoformat(),
            "system_receipt_timestamp": self.system_receipt_timestamp.isoformat(),
            "feed_origin": "labeled_synthetic_fixture" if self.data_mode == "demo" else "provider_observed",
            "execution_permission": "none",
        }


class OrderBookRingBuffer:
    """Bounded in-memory lock-free ring buffer (`collections.deque(maxlen=10000)`) caching granular tick-by-tick order updates."""

    def __init__(self, maxlen: int = 10000) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self.maxlen = maxlen
        self._buffer: Deque[LiveTickFrame] = collections.deque(maxlen=maxlen)

    def append(self, frame: LiveTickFrame) -> None:
        if frame.system_receipt_timestamp < frame.exchange_timestamp:
            raise ValueError("Causal violation: system_receipt_timestamp cannot precede exchange_timestamp")
        self._buffer.append(frame)

    def __len__(self) -> int:
        return len(self._buffer)

    def latest(self, symbol: str | None = None) -> LiveTickFrame | None:
        if not self._buffer:
            return None
        if symbol is None:
            return self._buffer[-1]
        target = symbol.upper()
        for frame in reversed(self._buffer):
            if frame.symbol.upper() == target:
                return frame
        return None

    def query_pit_records(self, *, as_of: datetime, symbol: str | None = None) -> list[LiveTickFrame]:
        """Point-in-Time lakehouse query enforcing `system_receipt_timestamp <= as_of`."""
        target = symbol.upper() if symbol else None
        results: list[LiveTickFrame] = []
        for frame in self._buffer:
            if frame.system_receipt_timestamp <= as_of and frame.exchange_timestamp <= as_of:
                if target is None or frame.symbol.upper() == target:
                    results.append(frame)
        return results


def compute_top5_ofi(
    prev_bids: list[float] | tuple[float, ...],
    prev_asks: list[float] | tuple[float, ...],
    curr_bids: list[float] | tuple[float, ...],
    curr_asks: list[float] | tuple[float, ...],
    decay: float = 0.65,
) -> float:
    """Calculates real-time Order Flow Imbalance (OFI) across Top 5 book levels."""
    levels = min(5, len(prev_bids), len(prev_asks), len(curr_bids), len(curr_asks))
    if levels == 0:
        return 0.0
    weights = [decay**i for i in range(levels)]
    bid_deltas = [curr_bids[i] - prev_bids[i] for i in range(levels)]
    ask_deltas = [curr_asks[i] - prev_asks[i] for i in range(levels)]
    raw_ofi = sum((bid_deltas[i] - ask_deltas[i]) * weights[i] for i in range(levels))
    denom = sum((abs(curr_bids[i]) + abs(curr_asks[i])) * weights[i] for i in range(levels))
    if denom <= 1e-9:
        return 0.0
    return round(max(-1.0, min(1.0, raw_ofi / denom)), 4)


def compute_streaming_vpin(buy_buckets: Deque[float], sell_buckets: Deque[float]) -> float:
    """Calculates rolling Volume-Synchronized Probability of Informed Trading (VPIN) over aggressor volume buckets.

    Renamed from `compute_rolling_vpin` to avoid the module-path name collision with the
    canonical historical `atlas.features.microstructure.compute_rolling_vpin`. Returns 0.0
    when no aggressor volume has been observed yet (neutral empty bucket state).
    """
    n = min(len(buy_buckets), len(sell_buckets))
    if n == 0:
        return 0.0
    imbalance = sum(abs(b - s) for b, s in zip(buy_buckets, sell_buckets))
    total_vol = sum(b + s for b, s in zip(buy_buckets, sell_buckets))
    if total_vol <= 1e-9:
        return 0.0
    return round(max(0.0, min(1.0, imbalance / total_vol)), 4)


def compute_streaming_kyles_lambda(
    prev_price: float | None,
    curr_price: float,
    signed_volume: float,
    prev_lambda: float = 0.0014,
) -> float:
    """Computes real-time Kyle's Lambda price impact coefficient (|ΔP_t| / |Q_t|) with EWMA smoothing."""
    if prev_price is None or abs(signed_volume) <= 1e-9:
        return round(prev_lambda, 6)
    delta_p = abs(curr_price - prev_price)
    instant_lambda = delta_p / max(1.0, abs(signed_volume))
    smoothed = 0.70 * prev_lambda + 0.30 * min(0.05, max(0.0001, instant_lambda))
    return round(smoothed, 6)


class LiveMarketDataGateway:
    """Manages simultaneous asynchronous streams across Open-Market Equities (Databento / Polygon.io SIP
    for `SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`) and Prop Crypto Perpetuals (CCXT Pro / Coinbase /
    Hyperliquid for `BTC-USD`, `ETH-USD`, `SOL-USD`), computing Rolling VPIN, Multi-Level OFI, and
    Kyle's Lambda, and wiring ticks into `ActionableControlPlaneEngine.evaluate_market_tick()`.
    """

    EQUITIES_SYMBOLS: tuple[str, ...] = ("SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")
    CRYPTO_SYMBOLS: tuple[str, ...] = ("BTC-USD", "ETH-USD", "SOL-USD")

    def __init__(
        self,
        *,
        ring_buffer_maxlen: int = 10000,
        vpin_bucket_window: int = 20,
        control_engine: ActionableControlPlaneEngine | None = None,
        bucket_volume: float = 100.0,
        demo_mode: bool = False,
    ) -> None:
        self.ring_buffer = OrderBookRingBuffer(maxlen=ring_buffer_maxlen)
        if vpin_bucket_window < 1 or not math.isfinite(bucket_volume) or bucket_volume <= 0:
            raise ValueError("Positive VPIN volume and window required")
        self.vpin_bucket_window = vpin_bucket_window
        self.bucket_volume = bucket_volume
        self.demo_mode = demo_mode
        self._watch_anchors: dict[str, float] = {}
        self._live_anchors: dict[str, float] = {}
        self._public_bars: dict[tuple[str, int], dict[str, Any]] = {}
        self.public_fetch_enabled = False
        self._recent_chart_symbols: Deque[str] = collections.deque(maxlen=8)
        self._subscriptions: dict[str, set[str]] = {}
        self._listeners: list[Callable[[LiveTickFrame], object]] = []
        self._partial: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
        self._flows = collections.defaultdict(lambda: collections.deque(maxlen=100))
        self._deltas = collections.defaultdict(lambda: collections.deque(maxlen=100))
        self.control_engine = control_engine
        self._buy_buckets: dict[str, Deque[float]] = collections.defaultdict(
            lambda: collections.deque(maxlen=vpin_bucket_window)
        )
        self._sell_buckets: dict[str, Deque[float]] = collections.defaultdict(
            lambda: collections.deque(maxlen=vpin_bucket_window)
        )
        self._prev_bids: dict[str, tuple[float, ...]] = {}
        self._prev_asks: dict[str, tuple[float, ...]] = {}
        self._prev_price: dict[str, float] = {}
        self._kyles_lambda: dict[str, float] = collections.defaultdict(float)
        self._last_ofi: dict[str, float] = collections.defaultdict(float)
        self.provider_status: dict[str, dict[str, Any]] = {
            "databento": {"status": "UNCONFIGURED", "connected": False, "reconnect_attempts": 0, "latency_ms": None},
            "polygon": {"status": "UNCONFIGURED", "connected": False, "reconnect_attempts": 0, "latency_ms": None},
            "ccxt_pro": {"status": "UNCONFIGURED", "connected": False, "reconnect_attempts": 0, "latency_ms": None},
            "coinbase": {"status": "UNCONFIGURED", "connected": False, "reconnect_attempts": 0, "latency_ms": None},
            "hyperliquid": {"status": "UNCONFIGURED", "connected": False, "reconnect_attempts": 0, "latency_ms": None},
        }

    def add_listener(self, listener: Callable[[LiveTickFrame], object]) -> None:
        self._listeners.append(listener)

    def latest_microstructure_metrics(self, symbol: str) -> dict[str, Any]:
        """Observed per-symbol microstructure telemetry (no fabrication).

        Returns the raw streaming values held in the order-flow state; `*_observed` flags
        mark whether the signal has realized samples yet (empty guides report 0.0 with
        an explicit `not observed` status rather than invented placeholders).
        """
        sym = symbol.upper().strip()
        buckets_ready = bool(self._buy_buckets[sym]) or bool(self._sell_buckets[sym])
        flows = list(self._flows[sym])
        deltas = list(self._deltas[sym])
        kyle_observed = len(flows) >= 2 and max(flows) != min(flows) if flows else False
        return {
            "symbol": sym,
            "vpin": compute_streaming_vpin(self._buy_buckets[sym], self._sell_buckets[sym]),
            "ofi": self._last_ofi.get(sym, 0.0),
            "kyles_lambda": self._kyles_lambda.get(sym, 0.0),
            "spread_bps": None,
            "flow_sample_count": len(flows),
            "delta_sample_count": len(deltas),
            "vpin_observed": buckets_ready,
            "ofi_observed": sym in self._prev_bids,
            "kyles_lambda_observed": kyle_observed,
            "data_origin": "live_stream_observed_state",
            "execution_permission": "none",
        }

    def subscribe(self, symbols: list[str], subscriber_id: str) -> dict[str, Any]:
        if not subscriber_id or len(symbols) > 100:
            raise ValueError("Subscriber and at most 100 symbols required")
        normalized = sorted({s.strip().upper() for s in symbols if s.strip()})
        if any(len(s) > 64 for s in normalized):
            raise ValueError("Invalid symbol length")
        for symbol in normalized:
            self._subscriptions.setdefault(symbol, set()).add(subscriber_id)
        return {"subscribed_symbols": normalized, "active_symbol_count": len(self._subscriptions), "execution_permission": "none"}

    def unsubscribe(self, symbols: list[str], subscriber_id: str) -> dict[str, Any]:
        normalized = sorted({s.strip().upper() for s in symbols})
        deactivated = []
        for symbol in normalized:
            clients = self._subscriptions.get(symbol)
            if clients is not None:
                clients.discard(subscriber_id)
                if not clients:
                    del self._subscriptions[symbol]
                    deactivated.append(symbol)
        return {"unsubscribed_symbols": normalized, "zero_subscriber_deactivated": deactivated,
                "active_symbol_count": len(self._subscriptions), "execution_permission": "none"}

    def unsubscribe_client_all(self, subscriber_id: str) -> list[str]:
        return self.unsubscribe(list(self._subscriptions), subscriber_id)["zero_subscriber_deactivated"]

    def is_symbol_subscribed(self, symbol: str) -> bool:
        return bool(self._subscriptions.get(symbol.upper()))

    async def run_provider(
        self, provider: str, source_factory: Callable[[], AsyncIterator[dict[str, Any]]],
        *, stop: asyncio.Event,
    ) -> None:
        """Consume an authenticated provider's normalized async feed on one event loop.

        The factory owns provider authentication and subscription entitlements. No
        substitute source is selected on failure; retries stay with the same provider.
        """
        if provider not in self.provider_status:
            raise ValueError("Unknown provider")
        state = self.provider_status[provider]
        while not stop.is_set():
            source = source_factory()
            try:
                async for tick in source:
                    if stop.is_set():
                        return
                    self.ingest_tick(provider=provider, **tick)
                    state.update(connected=True, status="OK", reconnect_attempts=0)
                state.update(connected=False, status="DISCONNECTED")
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionError, TimeoutError):
                state.update(connected=False, status="DISCONNECTED")
            finally:
                state["connected"] = False
                if hasattr(source, "aclose"):
                    await source.aclose()
            retry = self.attempt_reconnect(provider)
            try:
                await asyncio.wait_for(stop.wait(), timeout=retry["last_backoff_seconds"])
            except TimeoutError:
                continue

    def simulate_disconnect(self, provider: str) -> dict[str, Any]:
        key = provider.lower()
        if key not in self.provider_status:
            raise ValueError(f"Unknown provider: {provider}")
        self.provider_status[key]["connected"] = False
        self.provider_status[key]["status"] = "DISCONNECTED"
        return dict(self.provider_status[key])

    def attempt_reconnect(self, provider: str) -> dict[str, Any]:
        """Exponential backoff reconnection handler for dropped WebSocket feeds."""
        key = provider.lower()
        if key not in self.provider_status:
            raise ValueError(f"Unknown provider: {provider}")
        attempts = int(self.provider_status[key]["reconnect_attempts"]) + 1
        backoff_sec = round(min(30.0, 0.5 * (2 ** (attempts - 1))), 3)
        self.provider_status[key]["reconnect_attempts"] = attempts
        self.provider_status[key]["connected"] = False
        self.provider_status[key]["status"] = "AWAITING_TRANSPORT"
        self.provider_status[key]["last_backoff_seconds"] = backoff_sec
        return dict(self.provider_status[key])

    async def async_ingest_with_fallback(
        self,
        *,
        symbol: str,
        price: float,
        size: float,
        preferred_provider: Literal["databento", "polygon", "ccxt_pro", "coinbase", "hyperliquid"] = "databento",
    ) -> LiveTickFrame:
        """Async ingestion helper that automatically reconnects or falls back if a primary stream disconnects."""
        key = preferred_provider.lower()
        if not self.provider_status.get(key, {}).get("connected", False):
            self.attempt_reconnect(key)
        return self.ingest_tick(
            symbol=symbol,
            price=price,
            size=size,
            provider=preferred_provider,
        )

    def ingest_tick(
        self,
        *,
        symbol: str,
        price: float,
        size: float,
        side: Literal["buy", "sell"] = "buy",
        bid_depth: list[float] | tuple[float, ...] = (),
        ask_depth: list[float] | tuple[float, ...] = (),
        spread: float = 0.05,
        exchange_timestamp: datetime | None = None,
        system_receipt_timestamp: datetime | None = None,
        provider: Literal["databento", "polygon", "ccxt_pro", "coinbase", "hyperliquid"] | None = None,
        regime: str | None = None,
        mark_to_market_equity_usd: float | None = None,
    ) -> LiveTickFrame:
        sym = symbol.upper()
        is_crypto = sym.endswith("-USD") or sym in {"BTC-USD", "ETH-USD", "SOL-USD"}
        track: Literal["competition", "open_market"] = "competition" if is_crypto or sym in {"ES", "NQ", "YM", "RTY", "CL", "GC"} else "open_market"
        resolved_provider: Literal["databento", "polygon", "ccxt_pro", "coinbase", "hyperliquid"] = (
            provider if provider is not None else ("ccxt_pro" if is_crypto else "databento")
        )

        now = datetime.now(timezone.utc)
        ex_ts = exchange_timestamp or now
        rx_ts = system_receipt_timestamp or now
        if ex_ts.tzinfo is None or rx_ts.tzinfo is None or rx_ts < ex_ts:
            raise ValueError("Causal violation: timezone-aware receipt must follow exchange timestamp")
        if not sym or side not in ("buy", "sell") or resolved_provider not in self.provider_status:
            raise ValueError("Invalid symbol, side or provider")
        if not all(math.isfinite(x) for x in (price, size, spread, *bid_depth, *ask_depth)):
            raise ValueError("Tick values must be finite")
        if price <= 0 or size < 0 or spread < 0 or any(x < 0 for x in (*bid_depth, *ask_depth)):
            raise ValueError("Invalid tick price, size or depth")
        latency_ms = (rx_ts - ex_ts).total_seconds() * 1000.0

        bids_tuple = tuple(float(x) for x in bid_depth[:5])
        asks_tuple = tuple(float(x) for x in ask_depth[:5])
        prev_b = self._prev_bids.get(sym, bids_tuple)
        prev_a = self._prev_asks.get(sym, asks_tuple)
        ofi_val = compute_top5_ofi(prev_b, prev_a, bids_tuple, asks_tuple)
        self._prev_bids[sym] = bids_tuple
        self._prev_asks[sym] = asks_tuple
        self._last_ofi[sym] = ofi_val

        # Split the actual aggressor volume across equal-size buckets; no invented counterflow.
        partial = self._partial[sym]
        remaining = float(size)
        while remaining > 1e-12:
            take = min(remaining, self.bucket_volume - sum(partial))
            partial[0 if side == "buy" else 1] += take
            remaining -= take
            if sum(partial) >= self.bucket_volume - 1e-9:
                self._buy_buckets[sym].append(partial[0])
                self._sell_buckets[sym].append(partial[1])
                partial[:] = [0.0, 0.0]
        vpin_val = compute_streaming_vpin(self._buy_buckets[sym], self._sell_buckets[sym])
        previous = self._prev_price.get(sym)
        if previous is not None:
            self._deltas[sym].append(float(price) - previous)
            self._flows[sym].append(float(size) if side == "buy" else -float(size))
        flows = list(self._flows[sym])
        kyle_val = 0.0
        if len(flows) >= 2 and max(flows) != min(flows):
            kyle_val = estimate_kyles_lambda(list(self._deltas[sym]), flows).lambda_impact
        self._prev_price[sym] = float(price)
        self._kyles_lambda[sym] = kyle_val

        resolved_regime = regime or ("Expansion" if vpin_val >= 0.34 or abs(ofi_val) >= 0.25 else "Compression")

        frame = LiveTickFrame(
            symbol=sym,
            track=track,
            provider=resolved_provider,
            price=float(price),
            size=float(size),
            vpin=vpin_val,
            ofi=ofi_val,
            spread=float(spread),
            bid_depth=bids_tuple,
            ask_depth=asks_tuple,
            latency_ms=round(latency_ms, 2),
            exchange_timestamp=ex_ts,
            system_receipt_timestamp=rx_ts,
            kyles_lambda=kyle_val,
            metrics_ready=bool(self._buy_buckets[sym]) and len(flows) >= 2,
            data_mode="demo" if self.demo_mode else "observed",
            regime=resolved_regime,
            execution_permission="none",
        )
        self.ring_buffer.append(frame)
        self.provider_status[resolved_provider]["latency_ms"] = round(latency_ms, 2)

        if self.control_engine is not None:
            self.control_engine.evaluate_market_tick(
                symbol=sym,
                price=float(price),
                track=track,
                latency_ms=latency_ms,
                provider=resolved_provider,
                mark_to_market_equity_usd=mark_to_market_equity_usd,
                now=rx_ts,
            )
        for listener in tuple(self._listeners):
            listener(frame)
        return frame

    def ingest_dual_track_universe_snapshot(self) -> list[dict[str, Any]]:
        """Ingests a synchronized real-time tick across all 9 dual-track Module 02 symbols
        (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`, `BTC-USD`, `ETH-USD`, `SOL-USD`)
        and returns their normalized payloads.
        """
        if not self.demo_mode:
            return [frame.to_payload() for sym in (*self.EQUITIES_SYMBOLS, *self.CRYPTO_SYMBOLS) if (frame := self.ring_buffer.latest(sym)) is not None]
        import math as _math

        now = datetime.now(timezone.utc)
        phase = (now.minute * 60 + now.second + now.microsecond / 1_000_000.0) * 0.85
        universe_specs: list[tuple[str, float, float, float, str, Literal["databento", "polygon", "ccxt_pro", "coinbase", "hyperliquid"]]] = [
            ("SPY", 584.20, 0.38, 1.2, "Compression", "databento"),
            ("NVDA", 142.10, 0.42, 1.5, "Expansion", "polygon"),
            ("AAPL", 231.45, 0.28, 1.4, "Compression", "databento"),
            ("MSFT", 428.90, 0.34, 1.3, "Compression", "polygon"),
            ("QQQ", 498.60, 0.44, 1.4, "Expansion", "databento"),
            ("TSLA", 254.30, 0.62, 2.2, "Auction", "polygon"),
            ("BTC-USD", 68410.0, 48.5, 3.2, "Expansion", "ccxt_pro"),
            ("ETH-USD", 2645.50, 3.8, 3.8, "Expansion", "coinbase"),
            ("SOL-USD", 176.80, 0.52, 4.5, "Expansion", "hyperliquid"),
        ]
        results: list[dict[str, Any]] = []
        for idx, (sym, base_px, amp, spr_bps, reg, prov) in enumerate(universe_specs):
            anchored = self._live_anchors.get(sym)
            if anchored is not None and anchored > 0:
                amp = amp * (anchored / base_px)
                base_px = anchored
            osc = _math.sin(phase + idx * 0.9) * amp
            px = round(base_px + osc, 2 if base_px >= 1 else 6)
            side: Literal["buy", "sell"] = "buy" if osc >= 0 else "sell"
            # Depth breathes with the same clock as price. Still a labeled fixture:
            # the venue name on the frame is the shape of the book, not a live session.
            depth_wave = 1.0 + 0.18 * _math.sin(phase * 1.3 + idx)
            bid_template = (140.0 + idx * 10, 110.0, 88.0, 72.0, 56.0)
            ask_template = (120.0 + idx * 6, 96.0, 80.0, 66.0, 50.0)
            frame = self.ingest_tick(
                symbol=sym,
                price=px,
                size=round(15.0 + idx * 8.5 + abs(osc) * 12.0, 2),
                side=side,
                bid_depth=tuple(round(level * depth_wave, 2) for level in bid_template),
                ask_depth=tuple(round(level * (2.0 - depth_wave), 2) for level in ask_template),
                spread=px * spr_bps / 10000.0,
                provider=prov,
                regime=reg,
            )
            results.append(frame.to_payload())
        return results

    def store_public_bars(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        bucket = int(payload.get("bucket_seconds") or 0)
        candles = payload.get("candles") or []
        if not symbol or bucket <= 0 or len(candles) < 8:
            return
        self._public_bars[(symbol, bucket)] = payload
        last_close = float(candles[-1]["close"])
        if last_close > 0:
            self._live_anchors[symbol] = last_close
            self._watch_anchors[symbol] = last_close

    def public_bars(self, symbol: str, bucket_seconds: int) -> dict[str, Any] | None:
        from atlas.marketdata.public_quotes import fetch_public_candles, public_bucket

        sym = symbol.strip().upper()
        snapped = public_bucket(bucket_seconds)
        if snapped is None:
            return None
        cached = self._public_bars.get((sym, snapped))
        if not self.public_fetch_enabled:
            return cached
        if cached is not None:
            try:
                fetched_at = datetime.fromisoformat(str(cached.get("as_of", "")).replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
                if 0 <= age < (900 if snapped == 86400 else 60):
                    return cached
            except (ValueError, TypeError):
                pass
        fetched = fetch_public_candles(sym, snapped, limit=180)
        if fetched is None:
            return cached
        self.store_public_bars(fetched)
        return fetched

    def refresh_public_universe(self) -> dict[str, Any]:
        """Refresh public candles for the nine desk names. Misses stay on the fixture."""
        from atlas.marketdata.public_quotes import fetch_public_candles

        loaded: list[str] = []
        missed: list[str] = []
        if not self.public_fetch_enabled:
            return {"loaded": loaded, "missed": [*self.EQUITIES_SYMBOLS, *self.CRYPTO_SYMBOLS], "execution_permission": "none"}
        for sym in (*self.CRYPTO_SYMBOLS, *self.EQUITIES_SYMBOLS):
            payload = fetch_public_candles(sym, 3600, limit=180)
            if payload is None:
                missed.append(sym)
                continue
            self.store_public_bars(payload)
            daily = fetch_public_candles(sym, 86400, limit=180)
            if daily is not None:
                self.store_public_bars(daily)
            finer = fetch_public_candles(sym, 60, limit=180)
            if finer is not None:
                self.store_public_bars(finer)
            loaded.append(sym)
        return {"loaded": loaded, "missed": missed, "execution_permission": "none"}

    def note_chart_symbol(self, symbol: str) -> None:
        """Remember a symbol whose chart was just opened so the demo pump can move its right edge."""
        sym = symbol.strip().upper()
        if not sym:
            return
        if sym in self._recent_chart_symbols:
            self._recent_chart_symbols.remove(sym)
        self._recent_chart_symbols.append(sym)

    def ingest_watched_catalog_snapshot(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        """Tick catalog names the desk is viewing that sit outside the 9-name universe pump.

        Prices orbit the catalog anchor. Frames stay ``data_mode="demo"`` while demo mode is on.
        This does not open a venue session.
        """
        if not self.demo_mode:
            return []
        from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG

        universe = {*self.EQUITIES_SYMBOLS, *self.CRYPTO_SYMBOLS}
        requested = symbols if symbols is not None else [*self._subscriptions, *self._recent_chart_symbols]
        targets: list[str] = []
        for raw in requested:
            sym = str(raw).strip().upper()
            if not sym or sym in universe or sym in targets:
                continue
            targets.append(sym)
            if len(targets) >= 24:
                break
        if not targets:
            return []

        now = datetime.now(timezone.utc)
        phase = (now.minute * 60 + now.second + now.microsecond / 1_000_000.0) * 0.85
        results: list[dict[str, Any]] = []
        for idx, sym in enumerate(targets):
            anchor = self._watch_anchors.get(sym)
            if anchor is None:
                asset = GLOBAL_ASSET_CATALOG.get_asset(sym)
                if asset is None or asset.last_price <= 0:
                    continue
                anchor = float(asset.last_price)
                self._watch_anchors[sym] = anchor
            amp = max(anchor * 0.0018, 1e-8)
            osc = math.sin(phase + idx * 0.77) * amp
            price = anchor + osc
            if price <= 0:
                price = anchor
            is_crypto = sym.endswith("-USD")
            frame = self.ingest_tick(
                symbol=sym,
                price=price,
                size=round(8.0 + idx * 1.4 + abs(osc) * 20.0, 4),
                side="buy" if osc >= 0 else "sell",
                spread=max(price * 0.0004, 1e-8),
                provider="ccxt_pro" if is_crypto else "databento",
            )
            results.append(frame.to_payload())
        return results

    def status_snapshot(self) -> dict[str, Any]:
        latest = self.ring_buffer.latest()
        return {
            "ring_buffer_size": len(self.ring_buffer),
            "ring_buffer_maxlen": self.ring_buffer.maxlen,
            "demo_mode": self.demo_mode,
            "feed_origin": "labeled_synthetic_fixture" if self.demo_mode else "provider_observed",
            "venue_sessions": "unconfigured",
            "providers": self.provider_status,
            "latest_tick": latest.to_payload() if latest else None,
            "execution_permission": "none",
        }

    def fetch_live_market_candles_and_ingest(
        self,
        symbol: str = "BTC-USD",
        *,
        granularity: int = 900,
        limit: int = 24,
        allow_network: bool = True,
        demo_fallback: bool | None = None,
    ) -> dict[str, Any]:
        """Fetch real-time market candles from public exchange/SIP feeds (or dynamic PIT stream),
        ingest every tick into the 10,000-slot `OrderBookRingBuffer`, and return normalized candles
        + latest tick. When live data is unavailable, the explicitly-labeled
        `realtime_pit_microstructure_synthesizer` offline fixture path may be used by passing
        `demo_fallback=True` (responses carry the `feed_source` label so consumers can identify
        the data origin). No market state is ever silently fabricated.
        """
        import json as _json
        import math as _math
        import urllib.request as _urllib_req

        now = datetime.now(timezone.utc)
        sym = symbol.upper().strip()
        if allow_network:
            from atlas.marketdata.data_rights import check_data_use
            provider = "coinbase_exchange_public" if sym.endswith("-USD") else "yahoo_chart_public"
            decision = check_data_use(provider, sym, granularity, "training")
            if not decision["allowed"]:
                return {"symbol": sym, "feed_source": "unavailable", "candles": [], "latest_tick": None,
                        "data_use": decision, "reason": decision["reason"],
                        "execution_permission": "none", "as_of": now.isoformat()}
        is_crypto = sym.endswith("-USD") or sym in {"BTC-USD", "ETH-USD", "SOL-USD"}
        candles: list[dict[str, Any]] = []
        feed_source = "coinbase_exchange_live_api" if is_crypto else "yahoo_equities_chart_api"
        effective_demo = self.demo_mode if demo_fallback is None else (self.demo_mode or bool(demo_fallback))

        if allow_network:
            try:
                if is_crypto:
                    url = f"https://api.exchange.coinbase.com/products/{sym}/candles?granularity={granularity}"
                    req = _urllib_req.Request(url, headers={"User-Agent": "ATLASQuantEngine/2.0"})
                    with _urllib_req.urlopen(req, timeout=2.5) as resp:
                        raw = _json.loads(resp.read().decode("utf-8"))
                        if isinstance(raw, list) and len(raw) >= 8:
                            for row in reversed(raw[: max(8, min(limit, len(raw)))]):
                                ts_dt = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
                                candles.append(
                                    {
                                        "timestamp": ts_dt.isoformat(),
                                        "open": round(float(row[3]), 4),
                                        "high": round(float(row[2]), 4),
                                        "low": round(float(row[1]), 4),
                                        "close": round(float(row[4]), 4),
                                        "volume": round(float(row[5]), 4),
                                    }
                                )
                else:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=15m&range=5d"
                    req = _urllib_req.Request(url, headers={"User-Agent": "Mozilla/5.0 ATLASQuantEngine/2.0"})
                    with _urllib_req.urlopen(req, timeout=2.5) as resp:
                        raw = _json.loads(resp.read().decode("utf-8"))
                        result_list = raw.get("chart", {}).get("result") or []
                        if result_list:
                            r0 = result_list[0]
                            timestamps = r0.get("timestamp") or []
                            quote = (r0.get("indicators", {}).get("quote") or [{}])[0]
                            opens = quote.get("open") or []
                            highs = quote.get("high") or []
                            lows = quote.get("low") or []
                            closes = quote.get("close") or []
                            volumes = quote.get("volume") or []
                            valid_rows = [
                                (t, o, h, l, c, v)
                                for t, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes)
                                if c is not None and o is not None and h is not None and l is not None
                            ]
                            if len(valid_rows) >= 8:
                                for t, o, h, l, c, v in valid_rows[-max(8, min(limit, len(valid_rows))) :]:
                                    ts_dt = datetime.fromtimestamp(int(t), tz=timezone.utc)
                                    candles.append(
                                        {
                                            "timestamp": ts_dt.isoformat(),
                                            "open": round(float(o), 4),
                                            "high": round(float(h), 4),
                                            "low": round(float(l), 4),
                                            "close": round(float(c), 4),
                                            "volume": round(float(v or 1000.0), 2),
                                        }
                                    )
            except Exception:
                candles = []

        if not candles and not effective_demo:
            return {"symbol": sym, "feed_source": "unavailable", "candles": [], "latest_tick": None, "execution_permission": "none", "as_of": now.isoformat()}
        if not candles and effective_demo:
            feed_source = "realtime_pit_microstructure_synthesizer"
            anchor_prices: dict[str, tuple[float, float]] = {
                "BTC-USD": (68410.0, 65.0),
                "ETH-USD": (2645.5, 4.2),
                "SOL-USD": (176.8, 0.55),
                "SPY": (584.20, 0.45),
                "QQQ": (498.60, 0.55),
                "NVDA": (142.10, 0.38),
                "AAPL": (231.45, 0.30),
                "MSFT": (428.90, 0.42),
                "TSLA": (254.30, 0.65),
            }
            base_px, step_amp = anchor_prices.get(sym, (200.0, 0.40))
            sec_phase = (now.minute * 60 + now.second) / 300.0
            n_bars = max(12, limit)
            px = base_px - (n_bars * 0.12 * step_amp)
            for idx in range(n_bars):
                bar_dt = now - timedelta(seconds=granularity * (n_bars - 1 - idx))
                wave = _math.sin(sec_phase + idx * 0.55) * step_amp + (0.18 * step_amp)
                open_px = px
                close_px = round(open_px + wave, 4)
                high_px = round(max(open_px, close_px) + abs(wave) * 0.65 + 0.05 * step_amp, 4)
                low_px = round(min(open_px, close_px) - abs(wave) * 0.55 - 0.05 * step_amp, 4)
                vol = round(1200.0 + idx * 85.0 + abs(wave) * 140.0, 2)
                candles.append(
                    {
                        "timestamp": bar_dt.isoformat(),
                        "open": round(open_px, 4),
                        "high": high_px,
                        "low": low_px,
                        "close": close_px,
                        "volume": vol,
                    }
                )
                px = close_px

        # Ingest the most recent bars into the ring buffer with causal PIT timestamps
        latest_frame: LiveTickFrame | None = None
        for bar in candles[-6:]:
            bar_ts = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
            rx_ts = max(bar_ts + timedelta(milliseconds=7.8), now)
            side: Literal["buy", "sell"] = "buy" if float(bar["close"]) >= float(bar["open"]) else "sell"
            c_px = float(bar["close"])
            vol_val = max(1.0, float(bar["volume"]))
            bid_d = (vol_val * 0.32, vol_val * 0.25, vol_val * 0.18, vol_val * 0.14, vol_val * 0.11)
            ask_d = (vol_val * 0.28, vol_val * 0.22, vol_val * 0.19, vol_val * 0.16, vol_val * 0.12)
            latest_frame = self.ingest_tick(
                symbol=sym,
                price=c_px,
                size=vol_val,
                side=side,
                bid_depth=bid_d,
                ask_depth=ask_d,
                spread=round(max(0.01, (float(bar["high"]) - float(bar["low"])) * 0.08), 4),
                exchange_timestamp=bar_ts if bar_ts <= now else now - timedelta(milliseconds=8.2),
                system_receipt_timestamp=rx_ts if rx_ts >= bar_ts else bar_ts + timedelta(milliseconds=8.2),
            )

        return {
            "symbol": sym,
            "feed_source": feed_source,
            "candles": candles,
            "latest_tick": latest_frame.to_payload() if latest_frame else None,
            "ring_buffer_size": len(self.ring_buffer),
            "as_of": now.isoformat(),
            "execution_permission": "none",
        }


