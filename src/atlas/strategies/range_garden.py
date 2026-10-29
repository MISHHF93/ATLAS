"""Range garden (`STRAT_RANGE_GARDEN`).

Watch the public tape about once a second. Buy the lower rail and sell the
upper rail only when the box pays for the round trip. The signal stays
`execution_permission: none`. Opens and closes are paper actions on the
control plane. The spec is `docs/roadmap/range_garden.md`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from atlas.strategies.base import (
    BaseStrategy,
    CandleBar,
    MicrostructureMetrics,
    OrderBookDepthSnapshot,
    StrategySignal,
)

PATH_ID = "range-garden:v1"
STRATEGY_ID = "STRAT_RANGE_GARDEN"

COMPETITION_SYMBOLS = ("BTC-USD", "ETH-USD", "SOL-USD")
OPEN_MARKET_SYMBOLS = ("SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")
GARDEN_SYMBOLS = COMPETITION_SYMBOLS + OPEN_MARKET_SYMBOLS

FEE_BPS = {"competition": 6.0, "open_market": 1.0}
HALF_SPREAD_BPS = {"competition": 2.0, "open_market": 1.0}
MIN_STOP_BPS = {"competition": 25.0, "open_market": 30.0}
FRESH_MS = {"competition": 500.0, "open_market": 2000.0}
MIN_BARS = 40
RAIL_BARS = 90
ZONE_FRACTION = 0.18
BREAK_BPS = 10.0
MAX_FULL_SPREAD_BPS = 40.0
PUBLIC_MODES = frozenset({"public_market_candles", "public_last_trade"})
OPEN_ACTIONS = frozenset({"harvest_buy", "harvest_sell", "close_long", "close_short"})


def track_for_symbol(symbol: str) -> str:
    return "competition" if symbol.strip().upper().endswith("-USD") else "open_market"


def instrument_id_for(symbol: str, track: str) -> str:
    sym = symbol.strip().upper()
    if track == "competition":
        return f"comp:{sym.lower().replace('-usd', '')}-perp:v1"
    return f"open:{sym.lower()}-eq:v1"


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def _px(value: float) -> float:
    return float(f"{value:.8f}")


def _bar_floats(candles: Sequence[dict[str, Any]]) -> list[dict[str, float]]:
    clean: list[dict[str, float]] = []
    for bar in candles:
        try:
            low = float(bar["low"])
            high = float(bar["high"])
            close = float(bar["close"])
            open_px = float(bar.get("open", close))
        except (KeyError, TypeError, ValueError):
            continue
        if min(open_px, high, low, close) <= 0 or low > high:
            continue
        clean.append({"open": open_px, "high": high, "low": low, "close": close})
    return clean[-RAIL_BARS:]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def print_age_ms(observed_at: str | None, *, now: datetime, received_at: datetime | None = None) -> float | None:
    """Age of the trade, widened by how long we have been holding a stale cache."""
    trade_time = _parse_time(observed_at)
    if trade_time is None:
        return None
    ages = [(now - trade_time).total_seconds() * 1000.0]
    if received_at is not None:
        ages.append((now - received_at).total_seconds() * 1000.0)
    return max(0.0, max(ages))


def evaluate_range_garden(
    *,
    symbol: str,
    candles: Sequence[dict[str, Any]],
    last_price: float,
    data_mode: str,
    feed_origin: str,
    data_age_ms: float | None,
    position: dict[str, Any] | None = None,
    await_mid: bool = False,
    half_spread_bps: float | None = None,
) -> dict[str, Any]:
    """Decide watch, stand down, harvest, or close. Does not call the control plane."""
    sym = symbol.strip().upper()
    track = track_for_symbol(sym)
    fee = FEE_BPS[track]
    half = HALF_SPREAD_BPS[track] if half_spread_bps is None else max(0.0, float(half_spread_bps))
    cost_bps = 2.0 * (fee + half)
    min_stop = MIN_STOP_BPS[track]
    fresh_limit = FRESH_MS[track]
    base: dict[str, Any] = {
        "symbol": sym,
        "track": track,
        "action": "stand_down",
        "reason": "not_enough_printed_bars",
        "blocked_action": None,
        "direction": "HOLD",
        "last_price": last_price if last_price and last_price > 0 else None,
        "lower_rail": None,
        "upper_rail": None,
        "mid": None,
        "width_bps": None,
        "cost_bps": round(cost_bps, 4),
        "min_stop_bps": min_stop,
        "fresh_limit_ms": fresh_limit,
        "data_age_ms": None if data_age_ms is None else round(float(data_age_ms), 2),
        "data_mode": data_mode,
        "feed_origin": feed_origin,
        "tradable": False,
        "stop": None,
        "target": None,
        "clear_await_mid": False,
        "execution_permission": "none",
    }
    bars = _bar_floats(candles)
    if len(bars) < MIN_BARS or not last_price or last_price <= 0:
        return base

    lower = _quantile([bar["low"] for bar in bars], 0.15)
    upper = _quantile([bar["high"] for bar in bars], 0.85)
    if upper <= lower:
        base["reason"] = "range_unproven"
        base["action"] = "watch"
        return base
    mid = (lower + upper) / 2.0
    span = upper - lower
    width_bps = span / mid * 10_000.0
    lower_touches = sum(1 for bar in bars if bar["low"] <= lower * 1.0015)
    upper_touches = sum(1 for bar in bars if bar["high"] >= upper * 0.9985)
    base.update(
        {
            "lower_rail": _px(lower),
            "upper_rail": _px(upper),
            "mid": _px(mid),
            "width_bps": round(width_bps, 4),
        }
    )

    if half * 2.0 > MAX_FULL_SPREAD_BPS:
        base["reason"] = "spread_too_wide"
        return base

    def finish(action: str, reason: str, *, direction: str = "HOLD", stop: float | None = None, target: float | None = None) -> dict[str, Any]:
        result = dict(base)
        result.update(
            {
                "action": action,
                "reason": reason,
                "direction": direction,
                "stop": None if stop is None else _px(stop),
                "target": None if target is None else _px(target),
            }
        )
        public = data_mode in PUBLIC_MODES and "synthetic" not in feed_origin and "fixture" not in feed_origin
        fresh = data_age_ms is not None and 0 <= float(data_age_ms) <= fresh_limit
        result["tradable"] = bool(public and fresh)
        if action in OPEN_ACTIONS and not result["tradable"]:
            result["blocked_action"] = action
            result["action"] = "stand_down"
            result["direction"] = "HOLD"
            result["reason"] = "print_older_than_track_limit" if public else "synthetic_or_unlabeled_print"
        return result

    if position:
        side = str(position.get("side") or "")
        stop_px = float(position.get("stop") or 0)
        target_px = float(position.get("target") or 0)
        if side == "buy" and stop_px > 0 and last_price <= stop_px:
            return finish("close_long", "stop", stop=stop_px, target=target_px)
        if side == "buy" and target_px > 0 and last_price >= target_px:
            return finish("close_long", "target", stop=stop_px, target=target_px)
        if side == "sell" and stop_px > 0 and last_price >= stop_px:
            return finish("close_short", "stop", stop=stop_px, target=target_px)
        if side == "sell" and target_px > 0 and last_price <= target_px:
            return finish("close_short", "target", stop=stop_px, target=target_px)
        return finish("watch", "tending_open_bracket", stop=stop_px or None, target=target_px or None)

    broken = last_price > upper * (1.0 + BREAK_BPS / 10_000.0) or last_price < lower * (1.0 - BREAK_BPS / 10_000.0)
    if broken:
        return finish("stand_down", "range_broken")
    if lower_touches < 2 or upper_touches < 2:
        return finish("watch", "range_unproven")

    full_pays = width_bps >= cost_bps + min_stop + 8.0
    half_pays = (width_bps / 2.0) >= cost_bps + min_stop
    if not full_pays and not half_pays:
        return finish("stand_down", "range_does_not_pay")

    in_middle = (lower + 0.30 * span) <= last_price <= (upper - 0.30 * span)
    if await_mid and in_middle:
        base["clear_await_mid"] = True
        return finish("watch", "inside_bed")
    in_buy = last_price <= lower + ZONE_FRACTION * span
    in_sell = last_price >= upper - ZONE_FRACTION * span
    if await_mid and (in_buy or in_sell):
        return finish("watch", "waiting_for_midline")
    if not in_buy and not in_sell:
        return finish("watch", "inside_bed")

    target = (upper if in_buy else lower) if full_pays else mid
    stop_gap = max(min_stop, 0.25 * width_bps) / 10_000.0
    rail_pad = min_stop / 10_000.0
    if in_buy:
        stop = min(last_price * (1.0 - stop_gap), lower * (1.0 - rail_pad))
        direction = "BUY"
        action = "harvest_buy"
    else:
        stop = max(last_price * (1.0 + stop_gap), upper * (1.0 + rail_pad))
        direction = "SELL"
        action = "harvest_sell"
    if in_buy and not (stop < last_price < target):
        return finish("stand_down", "harvest_does_not_clear_cost")
    if (not in_buy) and not (target < last_price < stop):
        return finish("stand_down", "harvest_does_not_clear_cost")
    room_bps = abs(target - last_price) / last_price * 10_000.0
    if room_bps <= cost_bps:
        return finish("stand_down", "harvest_does_not_clear_cost")
    return finish(action, "rail_pays_cost", direction=direction, stop=stop, target=target)


class RangeGardenStrategy(BaseStrategy):
    """Air-gapped reader. The runner is what may ask the control plane to paper a bracket."""

    def __init__(self) -> None:
        super().__init__(
            strategy_id=STRATEGY_ID,
            name="Range Garden",
            track="both",
        )

    def generate_signal(
        self,
        candle_batch: Sequence[CandleBar | dict[str, Any]],
        orderbook_depth: OrderBookDepthSnapshot | dict[str, Any],
        microstructure_metrics: MicrostructureMetrics | dict[str, Any],
    ) -> StrategySignal:
        candles = self._coerce_candles(candle_batch)
        last = candles[-1] if candles else None
        symbol = last.symbol if last else "BTC-USD"
        price = float(last.close) if last else 0.0
        raw = [
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
            }
            for bar in candles
        ]
        decision = evaluate_range_garden(
            symbol=symbol,
            candles=raw,
            last_price=price,
            data_mode="unspecified",
            feed_origin="strategy_reader",
            data_age_ms=None,
        )
        reference = price if price > 0 else 1.0
        stop = float(decision["stop"] or reference * 0.99)
        target = float(decision["target"] or reference * 1.01)
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            direction="HOLD",
            target_conviction=0.0,
            suggested_stop_loss=stop,
            suggested_take_profit=target,
            execution_tactic="LIMIT",
            reference_price=reference,
            rationale=(
                f"Range garden read {decision['action']} / {decision['reason']}. "
                "No order leaves this reader."
            ),
            telemetry={
                "path_id": PATH_ID,
                "garden_action": decision["action"],
                "garden_reason": decision["reason"],
                "blocked_action": decision["blocked_action"],
            },
            execution_permission="none",
        )


class RangeGardenBook:
    """One-second paper tender. Caller-supplied prices are for tests, not the HTTP cycle."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ledger: dict[str, dict[str, Any]] = {}
        self._await_mid: dict[str, bool] = {}
        self._bars: dict[str, dict[str, Any]] = {}
        self._tickers: dict[str, dict[str, Any]] = {}
        self._bar_cursor = 0
        self.orders_submitted = 0
        self.harvests_closed = 0
        self.realized_pnl_usd = 0.0
        self.last_cycle_at: str | None = None
        self.symbols: list[dict[str, Any]] = []
        self.status = "waiting"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "path_id": PATH_ID,
                "strategy_id": STRATEGY_ID,
                "status": self.status,
                "objective": "harvest_range_round_trips",
                "cadence_seconds": 1,
                "orders_submitted": self.orders_submitted,
                "harvests_closed": self.harvests_closed,
                "realized_pnl_usd": round(self.realized_pnl_usd, 2),
                "last_cycle_at": self.last_cycle_at,
                "symbols": list(self.symbols),
                "execution_mode": "paper",
                "execution_permission": "none",
                "order_authority": "control_plane_only",
            }

    def run_cycle(
        self,
        engine: Any,
        gateway: Any,
        *,
        now: datetime | None = None,
        prints: dict[str, dict[str, Any]] | None = None,
        candles: dict[str, list[dict[str, Any]]] | None = None,
        allow_network: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._run_cycle(
                engine,
                gateway,
                now=now or datetime.now(timezone.utc),
                prints=prints,
                candles=candles,
                allow_network=gateway.public_fetch_enabled if allow_network is None else allow_network,
            )

    def _run_cycle(
        self,
        engine: Any,
        gateway: Any,
        *,
        now: datetime,
        prints: dict[str, dict[str, Any]] | None,
        candles: dict[str, list[dict[str, Any]]] | None,
        allow_network: bool,
    ) -> dict[str, Any]:
        self.status = "running"
        self.last_cycle_at = now.isoformat()
        if prints is None and allow_network:
            self._refresh_public(gateway, now)
        rows: list[dict[str, Any]] = []
        for symbol in GARDEN_SYMBOLS:
            rows.append(
                self._tend_symbol(
                    engine,
                    symbol,
                    now=now,
                    prints=prints,
                    candles=candles,
                )
            )
        self.symbols = rows
        return self.snapshot()

    def _refresh_public(self, gateway: Any, now: datetime) -> None:
        from atlas.marketdata.public_quotes import fetch_public_candles, fetch_public_ticker

        for symbol in COMPETITION_SYMBOLS:
            ticker = fetch_public_ticker(symbol)
            if ticker is not None:
                ticker["received_at"] = now.isoformat()
                self._tickers[symbol] = ticker
        due = GARDEN_SYMBOLS[self._bar_cursor % len(GARDEN_SYMBOLS)]
        self._bar_cursor += 1
        cached = self._bars.get(due)
        cached_at = _parse_time(cached.get("fetched_at")) if cached else None
        if cached_at is not None and (now - cached_at).total_seconds() < 30:
            return
        payload = fetch_public_candles(due, 60, limit=180)
        if payload is None:
            return
        payload["fetched_at"] = now.isoformat()
        self._bars[due] = payload
        if hasattr(gateway, "store_public_bars"):
            gateway.store_public_bars(payload)

    def _tend_symbol(
        self,
        engine: Any,
        symbol: str,
        *,
        now: datetime,
        prints: dict[str, dict[str, Any]] | None,
        candles: dict[str, list[dict[str, Any]]] | None,
    ) -> dict[str, Any]:
        track = track_for_symbol(symbol)
        bar_rows = list(candles[symbol]) if candles and symbol in candles else list((self._bars.get(symbol) or {}).get("candles") or [])
        if prints and symbol in prints:
            print_row = prints[symbol]
        elif track == "competition" and symbol in self._tickers:
            print_row = self._tickers[symbol]
        elif bar_rows:
            last_bar = bar_rows[-1]
            print_row = {
                "price": float(last_bar["close"]),
                "observed_at": str(last_bar.get("timestamp") or ""),
                "received_at": (self._bars.get(symbol) or {}).get("fetched_at"),
                "data_mode": "public_market_candles",
                "feed_origin": str((self._bars.get(symbol) or {}).get("feed_source") or "yahoo_chart_public"),
            }
        else:
            print_row = {
                "price": 0.0,
                "observed_at": None,
                "data_mode": "unavailable",
                "feed_origin": "none",
            }
        observed = print_row.get("observed_at")
        received = _parse_time(str(print_row.get("received_at") or "")) if print_row.get("received_at") else None
        age = print_age_ms(str(observed) if observed else None, now=now, received_at=received)
        bid = float(print_row.get("bid") or 0)
        ask = float(print_row.get("ask") or 0)
        half: float | None = None
        if bid > 0 and ask > bid:
            mid = (ask + bid) / 2.0
            half = ((ask - bid) / mid * 10_000.0) / 2.0
        decision = evaluate_range_garden(
            symbol=symbol,
            candles=bar_rows,
            last_price=float(print_row.get("price") or 0),
            data_mode=str(print_row.get("data_mode") or "unavailable"),
            feed_origin=str(print_row.get("feed_origin") or "none"),
            data_age_ms=age,
            position=self._ledger.get(symbol),
            await_mid=self._await_mid.get(symbol, False),
            half_spread_bps=half,
        )
        if decision.get("clear_await_mid"):
            self._await_mid[symbol] = False
        return self._apply(engine, decision, now=now)

    def _apply(self, engine: Any, decision: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        action = decision["action"]
        symbol = decision["symbol"]
        if action in ("harvest_buy", "harvest_sell"):
            if getattr(engine, "cash_tracked", False):
                decision["action"] = "stand_down"
                decision["reason"] = "paper_capital_is_operator_only"
                decision["direction"] = "HOLD"
                return decision
            if getattr(engine, "kill_switch_engaged", False):
                decision["action"] = "stand_down"
                decision["reason"] = "kill_switch_engaged"
                decision["direction"] = "HOLD"
                return decision
            if symbol in self._ledger:
                decision["action"] = "watch"
                decision["reason"] = "tending_open_bracket"
                decision["direction"] = "HOLD"
                return decision
            report = self._submit(engine, decision, now=now)
            decision["order_id"] = report.order_id
            decision["control_plane_decision"] = report.decision.control_plane_decision
            decision["violations"] = list(report.decision.violations)
            if report.decision.control_plane_decision == "authorized_and_executed" and report.decision.position_id:
                self._ledger[symbol] = {
                    "position_id": report.decision.position_id,
                    "side": "buy" if action == "harvest_buy" else "sell",
                    "entry": decision["last_price"],
                    "stop": decision["stop"],
                    "target": decision["target"],
                    "notional_usd": str(report.sized_notional_usd),
                    "cost_bps": decision["cost_bps"],
                }
                self.orders_submitted += 1
            else:
                decision["blocked_action"] = action
                decision["action"] = "stand_down"
                decision["reason"] = "control_plane_rejected"
                decision["direction"] = "HOLD"
            return decision
        if action in ("close_long", "close_short"):
            bracket = self._ledger.get(symbol)
            if bracket is None:
                decision["action"] = "watch"
                decision["reason"] = "no_garden_position"
                return decision
            notional = Decimal(str(bracket["notional_usd"]))
            fee = (notional * Decimal(str(bracket["cost_bps"])) / Decimal("10000")).quantize(Decimal("0.01"))
            closed = engine.close_position(
                bracket["position_id"],
                exit_price=float(decision["last_price"]),
                fee_usd=fee,
                reason=f"range_garden:{decision['reason']}",
                now=now,
            )
            decision["close"] = {
                "status": closed["status"],
                "paper_pnl_usd": closed.get("paper_pnl_usd"),
                "reason": closed.get("reason"),
            }
            if closed["status"] == "closed":
                self._ledger.pop(symbol, None)
                self._await_mid[symbol] = True
                self.harvests_closed += 1
                self.realized_pnl_usd += float(closed.get("paper_pnl_usd") or 0)
            else:
                decision["blocked_action"] = action
                decision["action"] = "stand_down"
                decision["reason"] = str(closed.get("reason") or "close_rejected")
            return decision
        return decision

    def _submit(self, engine: Any, decision: dict[str, Any], *, now: datetime):
        signal = StrategySignal(
            strategy_id=STRATEGY_ID,
            symbol=decision["symbol"],
            direction=decision["direction"],
            target_conviction=0.62,
            suggested_stop_loss=float(decision["stop"]),
            suggested_take_profit=float(decision["target"]),
            execution_tactic="LIMIT",
            reference_price=float(decision["last_price"]),
            rationale=(
                f"Range garden {decision['action']} at {decision['last_price']} "
                f"between {decision['lower_rail']} and {decision['upper_rail']}."
            ),
            telemetry={"path_id": PATH_ID, "vpin": 0.2, "cost_bps": decision["cost_bps"]},
            execution_permission="none",
        )
        return engine.ingest_whale_policy_signal(
            signal,
            track=decision["track"],
            data_age_ms=float(decision["data_age_ms"] or 0),
            require_connector=False,
            now=now,
        )
