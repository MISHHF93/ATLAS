"""Read the chart the desk is streaming and score it with WhalePolicyModel.

The model reads public candles for the selected symbol when that feed has
answered, then the ring buffer, then the labeled fixture. It scores the
competition book (BTC-USD, ETH-USD, SOL-USD) and the open-market book
(SPY, NVDA, AAPL, MSFT, QQQ, TSLA). The active symbol also carries a
`whale_moment` from the 12-factor lock (WSDM-01 buy through WSDM-05 buy or sell).
Every payload stays `execution_permission: none`. The model never receives order authority.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from atlas.marketdata.live_stream import LiveMarketDataGateway, LiveTickFrame
from atlas.ai.models.live_observer import observe_public_bars
from atlas.ai.models.whale_factor_ml import WhaleOpportunityFactorModel
from atlas.ai.models.whale_policy import WhalePolicyModel

_BOOK_ROW_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}

COMPETITION_SYMBOLS: tuple[str, ...] = ("BTC-USD", "ETH-USD", "SOL-USD")
OPEN_MARKET_SYMBOLS: tuple[str, ...] = ("SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")

_FIXTURE_ANCHORS: dict[str, tuple[float, float]] = {
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


def track_for_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if sym in COMPETITION_SYMBOLS or sym.endswith("-USD"):
        return "competition"
    return "open_market"


def _bucket_candles(frames: list[LiveTickFrame], bucket_seconds: int, limit: int) -> list[dict[str, Any]]:
    bucket = max(1, int(bucket_seconds))
    bars: list[dict[str, Any]] = []
    current_key: int | None = None
    for frame in frames:
        ts = frame.exchange_timestamp
        key = int(ts.timestamp()) // bucket
        price = float(frame.price)
        size = float(frame.size)
        if current_key != key or not bars:
            current_key = key
            start = datetime.fromtimestamp(key * bucket, tz=timezone.utc)
            bars.append(
                {
                    "timestamp": start.isoformat(),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": size,
                }
            )
        else:
            bar = bars[-1]
            bar["high"] = max(float(bar["high"]), price)
            bar["low"] = min(float(bar["low"]), price)
            bar["close"] = price
            bar["volume"] = float(bar["volume"]) + size
    return bars[-limit:]


def labeled_fixture_candles(symbol: str, *, limit: int = 24, granularity: int = 60, now: datetime | None = None) -> list[dict[str, Any]]:
    """In-memory bars used only when the stream has fewer than four ticks."""
    stamp = now or datetime.now(timezone.utc)
    sym = symbol.upper().strip()
    base_px, step_amp = _FIXTURE_ANCHORS.get(sym, (200.0, 0.40))
    n_bars = max(12, limit)
    sec_phase = (stamp.minute * 60 + stamp.second) / 300.0
    px = base_px - (n_bars * 0.12 * step_amp)
    candles: list[dict[str, Any]] = []
    for idx in range(n_bars):
        bar_dt = stamp - timedelta(seconds=granularity * (n_bars - 1 - idx))
        wave = math.sin(sec_phase + idx * 0.55) * step_amp + (0.18 * step_amp)
        open_px = px
        close_px = round(open_px + wave, 4)
        candles.append(
            {
                "timestamp": bar_dt.isoformat(),
                "open": round(open_px, 4),
                "high": round(max(open_px, close_px) + abs(wave) * 0.65 + 0.05 * step_amp, 4),
                "low": round(min(open_px, close_px) - abs(wave) * 0.55 - 0.05 * step_amp, 4),
                "close": close_px,
                "volume": round(1200.0 + idx * 85.0 + abs(wave) * 140.0, 2),
            }
        )
        px = close_px
    return candles


def _directory_quote_state(symbol: str) -> str:
    """quoted, unquoted directory name, or unlisted private name."""
    from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG

    asset = GLOBAL_ASSET_CATALOG.get_asset(symbol)
    if asset is None:
        return "unknown"
    if str(asset.exchange).upper() == "UNLISTED":
        return "unlisted"
    if float(asset.last_price) <= 0:
        return "unquoted"
    return "quoted"


def _observer_feed_origin(symbol: str, feed_origin: str) -> str:
    origin = str(feed_origin or "none")
    if origin not in {"", "none", "provider_observed", "unlabeled"}:
        return origin
    return "coinbase_exchange_public" if symbol.endswith("-USD") else "yahoo_chart_public"


def _mount_online_observer(
    symbol: str,
    candles: list[dict[str, Any]],
    *,
    bucket_seconds: int,
    feed_origin: str,
    chart_source: str,
    learning_allowed: bool,
    public_as_of: str | None = None,
) -> dict[str, Any] | None:
    """Attach the same online logistic observer used in live-view to candle reads."""
    if chart_source != "public_market_candles" or len(candles) < 4:
        return None
    moment = datetime.now(timezone.utc)
    watermark = moment
    if public_as_of:
        try:
            watermark = min(moment, datetime.fromisoformat(str(public_as_of).replace("Z", "+00:00")))
        except ValueError:
            watermark = moment
    last_ts = datetime.fromisoformat(str(candles[-1]["timestamp"]).replace("Z", "+00:00"))
    bar_end = last_ts + timedelta(seconds=max(1, int(bucket_seconds)))
    if bar_end <= watermark:
        watermark = bar_end
    observation = observe_public_bars(
        symbol,
        candles,
        now=moment,
        bucket_seconds=max(1, int(bucket_seconds)),
        feed_origin=_observer_feed_origin(symbol, feed_origin),
        learning_allowed=learning_allowed,
        pause_reason="Public feed is disabled or not fresh. Saved learning is retained.",
        completed_through=watermark,
    )
    observation.pop("candles", None)
    return observation


def _book_cache_ttl(bucket_seconds: int) -> float:
    return min(120.0, max(12.0, float(bucket_seconds) / 2.0))


def _resolve_candles(
    gateway: LiveMarketDataGateway,
    symbol: str,
    *,
    bucket_seconds: int,
    limit: int,
) -> tuple[list[dict[str, Any]], str, int]:
    requested = max(1, int(bucket_seconds))
    state = _directory_quote_state(symbol)
    if state == "unlisted":
        return [], "no_quote", requested
    public = gateway.public_bars(symbol, bucket_seconds) if hasattr(gateway, "public_bars") else None
    public_candles = list(public["candles"]) if public else []
    if public:
        cutoff = datetime.now(timezone.utc)
        duration = int(public["bucket_seconds"])
        public_candles = [bar for bar in public_candles
                          if datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
                          + timedelta(seconds=duration) <= cutoff]
    if len(public_candles) >= 4:
        return public_candles[-limit:], "public_market_candles", int(public["bucket_seconds"])
    now = datetime.now(timezone.utc)
    frames = gateway.ring_buffer.query_pit_records(as_of=now, symbol=symbol)
    frames = sorted(frames, key=lambda frame: frame.exchange_timestamp)
    if len(frames) >= 4:
        bucket = requested
        while bucket > 1:
            bars = _bucket_candles(frames, bucket, limit)
            if len(bars) >= 4:
                return bars, "stream_ring_buffer", bucket
            bucket = max(1, bucket // 4)
        bars = _bucket_candles(frames, 1, limit)
        if len(bars) >= 4:
            return bars, "stream_ring_buffer", 1
    if state == "unquoted":
        return [], "no_quote", requested
    return labeled_fixture_candles(symbol, limit=limit, granularity=requested, now=now), "labeled_fixture_bars", requested


def _body_contribution(bar: dict[str, Any]) -> float:
    """Signed body as a fraction of the bar's range, weighted by volume. A doji contributes nothing."""
    span = max(float(bar["high"]) - float(bar["low"]), 1e-9)
    body = (float(bar["close"]) - float(bar["open"])) / span
    volume = max(1.0, float(bar.get("volume", 1.0)))
    return body * volume


def _average_true_range(candles: list[dict[str, Any]], length: int = 14) -> float:
    if not candles:
        return 0.0
    window = candles[-max(1, length):]
    ranges: list[float] = []
    previous_close = float(window[0]["close"])
    for bar in window:
        high = float(bar["high"])
        low = float(bar["low"])
        true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range)
        previous_close = float(bar["close"])
    return sum(ranges) / len(ranges)


def causal_bar_lock(
    candles: list[dict[str, Any]],
    *,
    action: str | None,
) -> dict[str, Any]:
    """Shade the closed bars that agree with the research side, and price the swing that would invalidate it.

    The walk starts at the last closed bar and stops at the first earlier bar whose body
    opposes that side. No later bar is read. This is not an order.
    """
    rows = [bar for bar in candles if bar.get("timestamp") is not None]
    if not rows:
        return {
            "decision_timestamp": None,
            "window_timestamps": [],
            "contributions": [],
            "bars_read": 0,
            "method": "causal_swing",
            "execution_permission": "none",
            "may_propose_order": False,
            "notice": "No closed bar was available. Nothing was locked and nothing was sent.",
        }
    lookback = rows[-24:]
    side_name = str(action or "").upper()
    if side_name not in {"BUY", "SELL"}:
        total = sum(_body_contribution(bar) for bar in lookback)
        side_name = "BUY" if total >= 0 else "SELL"
    side = 1 if side_name == "BUY" else -1
    chosen: list[dict[str, Any]] = [lookback[-1]]
    for bar in reversed(lookback[:-1]):
        contrib = _body_contribution(bar)
        opposes = (side > 0 and contrib < 0) or (side < 0 and contrib > 0)
        if opposes:
            break
        chosen.append(bar)
    chosen.reverse()
    absolute = [abs(_body_contribution(bar)) for bar in chosen]
    scale = sum(absolute) or 1.0
    atr = _average_true_range(lookback)
    entry = float(lookback[-1]["close"])
    cushion = max(atr, abs(entry) * 1e-4)
    if side > 0:
        swing = min(float(bar["low"]) for bar in chosen)
        invalidation = swing - 0.25 * atr
        if invalidation >= entry:
            invalidation = entry - cushion
        risk = max(entry - invalidation, cushion)
        objective = entry + risk
    else:
        swing = max(float(bar["high"]) for bar in chosen)
        invalidation = swing + 0.25 * atr
        if invalidation <= entry:
            invalidation = entry + cushion
        risk = max(invalidation - entry, cushion)
        objective = entry - risk
    return {
        "decision_timestamp": str(lookback[-1]["timestamp"]),
        "window_timestamps": [str(bar["timestamp"]) for bar in chosen],
        "contributions": [
            {"timestamp": str(bar["timestamp"]), "share": round(weight / scale, 4)}
            for bar, weight in zip(chosen, absolute)
        ],
        "bars_in_lock": len(chosen),
        "method": "causal_swing",
        "invalidation_price": round(invalidation, 4),
        "objective_price": round(objective, 4),
        "average_true_range": round(atr, 4),
        "execution_permission": "none",
        "may_propose_order": False,
        "notice": (
            "Shaded bars are the closed bars whose body agrees with this research side, "
            "walking back from the last bar until an opposing bar. The invalidation line sits "
            "beyond that swing by a quarter of the average true range. No later bar was used. "
            "This cannot send an order."
        ),
    }


def _candle_signed_flow(candles: list[dict[str, Any]]) -> float:
    """Volume-weighted close-versus-open sign, in [-1, 1].

    The chart moment takes its side from these candles. It does not read a live book.
    """
    signed = 0.0
    weight = 0.0
    for bar in candles[-8:]:
        volume = max(1.0, float(bar.get("volume", 1.0)))
        sign = 1.0 if float(bar["close"]) >= float(bar["open"]) else -1.0
        signed += sign * volume
        weight += volume
    if weight <= 0:
        return 0.0
    return round(signed / weight, 4)


def _moment_summary(scenario_id: str, action: str, scenario_name: str) -> str:
    """Plain description of a locked scenario. Factors here are rebuilt from candles."""
    side = "Buy" if action == "BUY" else "Sell"
    notes = {
        "WSDM-01": (
            f"{side} moment from the factor lock ({scenario_name}). "
            "The side follows candles that closed up. Toxicity and Hawkes intensity were reconstructed from those candles, not from a live book."
        ),
        "WSDM-02": (
            f"{side} moment from the factor lock ({scenario_name}). "
            "The side follows candles that closed down. Toxicity and price impact were reconstructed from those candles, not from an exchange liquidation print."
        ),
        "WSDM-03": (
            f"{side} moment from the factor lock ({scenario_name}). "
            "Volume expansion was measured on these candles, not on a live book skew."
        ),
        "WSDM-04": (
            f"{side} moment from the factor lock ({scenario_name}). "
            "The value-area edge comes from these candles, not from a live stop cluster."
        ),
        "WSDM-05": (
            f"{side} moment from the factor lock ({scenario_name}). "
            "This is a one-symbol dislocation label, not a two-leg cross-market trade."
        ),
    }
    text = notes.get(
        scenario_id,
        f"{side} moment from the factor lock ({scenario_name}).",
    )
    if scenario_id == "WSDM-01":
        return text + " The decision sheet's example check is on for WSDM-01."
    return text + " The decision sheet's example check is on for WSDM-01 only. This lock still names the moment."


_ABSTAIN_TEXT = {
    "fewer_than_four_bars": "Fewer than four bars.",
    "factor_lock_unavailable": "The factor lock could not be read.",
    "fewer_than_forty_bars": "Fewer than forty printed bars.",
    "tape_is_not_a_public_print": "This tape is a fixture or a synthesizer.",
    "side_reconstructed_from_candle_bodies": "The side is reconstructed from candle bodies, not a live book.",
    "order_flow_unobserved": "Order flow was not observed on this read.",
    "hawkes_unobserved": "Hawkes clustering was not observed on this read.",
    "policy_direction_disagrees": "The causal read and the factor lock disagree.",
    "paper_session_not_armed": "No paper session is armed for this read.",
}


def decide_trade_stance(
    *,
    whale_moment: dict[str, Any],
    direction: str,
    feed_origin: str,
    ofi_observed: bool,
    hawkes_observed: bool,
    bars_read: int,
    paper_armed: bool = False,
) -> dict[str, Any]:
    """Say whether this read may be reviewed. It never proposes an order."""
    gaps: list[str] = []
    if whale_moment.get("status") != "locked":
        gaps.append(str(whale_moment.get("reason") or "moment_withheld"))
    if bars_read < 40:
        gaps.append("fewer_than_forty_bars")
    feed = str(feed_origin or "")
    if (
        "fixture" in feed
        or "synth" in feed
        or feed in {"", "unlabeled", "provider_observed"}
    ):
        gaps.append("tape_is_not_a_public_print")
    if whale_moment.get("inputs") == "candle_close_versus_open":
        gaps.append("side_reconstructed_from_candle_bodies")
    if not ofi_observed:
        gaps.append("order_flow_unobserved")
    if not hawkes_observed:
        gaps.append("hawkes_unobserved")
    hypothesis = str(whale_moment.get("action") or "").upper()
    policy = str(direction or "").upper()
    if hypothesis in {"BUY", "SELL"} and policy in {"BUY", "SELL"} and hypothesis != policy:
        gaps.append("policy_direction_disagrees")
    if not gaps and not paper_armed:
        gaps.append("paper_session_not_armed")
    if gaps:
        sentences = [_ABSTAIN_TEXT.get(item, item) for item in gaps]
        return {
            "stance": "abstain",
            "may_propose_order": False,
            "reasons": gaps,
            "summary": "Must not trade. " + " ".join(sentences),
            "hypothesis_action": hypothesis if hypothesis in {"BUY", "SELL"} else None,
            "execution_permission": "none",
        }
    return {
        "stance": "paper_review",
        "may_propose_order": False,
        "reasons": [],
        "summary": "The evidence lines up for a paper review. This read still cannot send an order.",
        "hypothesis_action": hypothesis if hypothesis in {"BUY", "SELL"} else None,
        "execution_permission": "none",
    }


def whale_moment_from_candles(symbol: str, candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Name one WSDM buy or sell from candles already loaded. Never an order."""
    if len(candles) < 4:
        return {
            "status": "withheld",
            "reason": "fewer_than_four_bars",
            "execution_permission": "none",
        }
    try:
        report = WhaleOpportunityFactorModel().evaluate_live_opportunity(
            symbol,
            candles,
            ofi_override=_candle_signed_flow(candles),
        )
    except (ValueError, ArithmeticError):
        return {
            "status": "withheld",
            "reason": "factor_lock_unavailable",
            "execution_permission": "none",
        }
    lock = report.locked_opportunity
    return {
        "status": "locked",
        "scenario_id": lock.scenario_id,
        "scenario_name": lock.scenario_name,
        "action": lock.action,
        "trigger_summary": _moment_summary(lock.scenario_id, lock.action, lock.scenario_name),
        "entry_price": lock.entry_price,
        "stop_loss_price": lock.stop_loss_price,
        "take_profit_price": lock.take_profit_price,
        "inputs": "candle_close_versus_open",
        "sheet_example_active": lock.scenario_id == "WSDM-01",
        "execution_permission": "none",
    }


def _horizons(spot: float, stop_px: float, take_px: float) -> list[dict[str, Any]]:
    move = take_px - spot
    risk = max(abs(stop_px - spot), abs(spot) * 0.0015)
    rows: list[dict[str, Any]] = []
    for label, fraction, band_scale in (("t+15m", 0.35, 0.55), ("t+1h", 0.70, 1.0), ("t+2h", 1.0, 1.35)):
        p50 = spot + move * fraction
        band = risk * band_scale
        rows.append(
            {
                "horizon": label,
                "expected_return_bps": round(((p50 - spot) / max(spot, 1e-6)) * 10_000.0, 2),
                "p10_price": round(p50 - band, 4),
                "p50_price": round(p50, 4),
                "p90_price": round(p50 + band, 4),
            }
        )
    return rows


def read_symbol_chart(
    gateway: LiveMarketDataGateway,
    model: WhalePolicyModel,
    symbol: str,
    *,
    bucket_seconds: int = 60,
    limit: int = 48,
    include_whale_moment: bool = False,
) -> dict[str, Any]:
    sym = symbol.upper().strip()
    if bucket_seconds == 1:
        from atlas.marketdata.second_tape import snapshot

        tape = snapshot(sym, sampling=gateway.public_fetch_enabled)
        health = tape.get("feed_health") or {}
        watermark = health.get("last_exchange_at")
        from atlas.marketdata.data_rights import check_data_use
        decisions = [check_data_use("coinbase_exchange_public", sym, 1, use) for use in ("training", "retention")]
        denied = [item for item in decisions if not item["allowed"]]
        observation = observe_public_bars(
            sym, list(tape.get("candles") or []),
            learning_allowed=health.get("connection") == "connected" and not denied,
            pause_reason=denied[0]["reason"] if denied else "The trade transport is not connected. Saved learning is retained.",
            completed_through=datetime.fromisoformat(str(watermark).replace("Z", "+00:00")) if watermark else None,
            state_scope=decisions[0].get("policy_sha256") if not denied else None,
        )
        if tape.get("chart_source") == "withheld" and tape.get("notice"):
            observation["notice"] = tape["notice"]
        candles = observation.pop("candles")
        age = observation.get("feed_age_seconds")
        # Learning may be paused (no recorded data-use permission) while the real tape is still fresh and displayable.
        valid = observation["status"] in {"warming_up", "learning"} or (
            observation["status"] == "paused" and bool(candles) and age is not None and age <= 30)
        return {
            "symbol": sym, "track": track_for_symbol(sym), "bucket_seconds": 1,
            "chart_source": "public_last_trade" if valid else "withheld",
            "data_mode": "observed" if valid else "withheld",
            "feed_origin": "coinbase_exchange_public" if candles else "none",
            "bars_read": len(candles), "candles": candles,
            "last_close": float(candles[-1]["close"]) if candles else None,
            "last_bar_close": (datetime.fromisoformat(str(candles[-1]["timestamp"])) + timedelta(seconds=1)).isoformat() if candles else None,
            "model_id": "online_logistic_observer:experimental",
            "direction": observation["direction"], "online_observer": observation,
            "feed_health": tape.get("feed_health", {}),
            "horizons": [], "signal": {}, "stream_inputs_observed": [],
            "notice": observation.get("notice"), "execution_permission": "none",
        }
    candles, chart_source, bucket_used = _resolve_candles(
        gateway, sym, bucket_seconds=bucket_seconds, limit=limit
    )
    if chart_source == "public_market_candles":
        from atlas.marketdata.data_rights import check_data_use
        provider = "coinbase_exchange_public" if sym.endswith("-USD") else "yahoo_chart_public"
        decision = check_data_use(provider, sym, bucket_used, "training")
        if not decision["allowed"]:
            return {"symbol": sym, "track": track_for_symbol(sym), "bucket_seconds": bucket_used,
                    "chart_source": "withheld", "data_mode": "withheld", "feed_origin": provider,
                    "model_id": "data_use_not_admitted", "bars_read": 0, "candles": [], "last_close": None,
                    "direction": "WITHHELD", "conviction": None, "horizons": [], "signal": {},
                    "stream_inputs_observed": [], "notice": decision["reason"], "data_use": decision,
                    "whale_moment": {"status": "withheld", "recommendation": {"stance": "abstain",
                                      "may_propose_order": False, "summary": decision["reason"]}},
                    "execution_permission": "none"}
    if chart_source == "no_quote":
        payload = {
            "symbol": sym,
            "track": track_for_symbol(sym),
            "chart_source": "no_quote",
            "data_mode": "withheld",
            "feed_origin": "no_quote",
            "bucket_seconds": bucket_used,
            "bars_read": 0,
            "last_close": 0.0,
            "model_id": model.model_id,
            "direction": "FLAT",
            "conviction": 0.0,
            "reference_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "horizons": [],
            "signal": {},
            "stream_inputs_observed": [],
            "notice": "This directory name has no quote. No price series is invented.",
            "execution_permission": "none",
        }
        if include_whale_moment:
            payload["whale_moment"] = {
                "status": "withheld",
                "reason": "no_quote",
                "execution_permission": "none",
                "recommendation": {
                    "stance": "abstain",
                    "may_propose_order": False,
                    "summary": "Must not trade. This name has no quote.",
                },
            }
            payload["candles"] = []
            payload["bar_lock"] = {
                "method": "causal_swing",
                "stance": "abstain",
                "may_propose_order": False,
                "bars_in_lock": 0,
                "bars_read": 0,
                "action": None,
                "invalidation_price": None,
                "objective_price": None,
                "feed_origin": "no_quote",
                "decision_timestamp": None,
                "execution_permission": "none",
                "notice": "No quote is stored for this name. No price series is invented. Nothing was sent.",
            }
        return payload
    latest = gateway.ring_buffer.latest(sym)
    observed: dict[str, float] = {}
    if chart_source == "stream_ring_buffer" and latest is not None and latest.price > 0 and latest.data_mode != "demo":
        observed["vpin"] = float(latest.vpin)
        observed["ofi_z"] = float(latest.ofi)
        observed["kyles_lambda"] = float(latest.kyles_lambda)
        observed["spread_bps"] = float(latest.spread) / float(latest.price) * 10_000.0
    signal = model.predict(symbol=sym, candles=candles, **observed)
    spot = float(signal.reference_price)
    public_as_of: str | None = None
    if chart_source == "public_market_candles":
        cached = gateway.public_bars(sym, bucket_seconds) if hasattr(gateway, "public_bars") else None
        feed_origin = str(cached["feed_source"]) if cached else "public_market_data"
        public_as_of = str(cached["as_of"]) if cached and cached.get("as_of") else None
    else:
        feed_origin = "labeled_synthetic_fixture" if gateway.demo_mode or chart_source == "labeled_fixture_bars" else "provider_observed"
        if chart_source == "stream_ring_buffer" and latest is not None:
            feed_origin = "labeled_synthetic_fixture" if latest.data_mode == "demo" or gateway.demo_mode else "provider_observed"
    payload = {
        "symbol": sym,
        "track": track_for_symbol(sym),
        "chart_source": chart_source,
        "data_mode": "synthetic" if chart_source == "labeled_fixture_bars" else "observed",
        "notice": (
            "The requested history is not available from an observed feed. These bars are a labeled synthetic fixture and are not live market data."
            if chart_source == "labeled_fixture_bars"
            else "Bars are supplied by the reported chart source."
        ),
        "feed_origin": feed_origin,
        "bucket_seconds": bucket_used,
        "bars_read": len(candles),
        "last_close": round(float(candles[-1]["close"]), 4),
        "model_id": model.model_id,
        "direction": signal.direction,
        "conviction": signal.conviction,
        "reference_price": spot,
        "stop_loss": signal.suggested_stop_loss,
        "take_profit": signal.suggested_take_profit,
        "horizons": _horizons(spot, float(signal.suggested_stop_loss), float(signal.suggested_take_profit)),
        "signal": signal.model_dump(mode="json"),
        "stream_inputs_observed": sorted(observed.keys()),
        "model_weights": dict(model.weights),
        "last_bar_open": str(candles[-1]["timestamp"]),
        "last_bar_close": (datetime.fromisoformat(str(candles[-1]["timestamp"]).replace("Z", "+00:00")) + timedelta(seconds=bucket_used)).isoformat(),
        "read_at": datetime.now(timezone.utc).isoformat(),
        "execution_permission": "none",
    }
    if include_whale_moment:
        moment = whale_moment_from_candles(sym, candles)
        telemetry = signal.telemetry if isinstance(getattr(signal, "telemetry", None), dict) else {}
        moment["recommendation"] = decide_trade_stance(
            whale_moment=moment,
            direction=str(signal.direction),
            feed_origin=feed_origin,
            ofi_observed=telemetry.get("ofi_observed") is True,
            hawkes_observed=telemetry.get("hawkes_observed") is True,
            bars_read=len(candles),
        )
        payload["whale_moment"] = moment
        payload["candles"] = [
            {
                "timestamp": str(bar.get("timestamp")),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            }
            for bar in candles
            if bar.get("timestamp") is not None
        ]
        recommendation = moment.get("recommendation") if isinstance(moment.get("recommendation"), dict) else {}
        research_action = moment.get("action") if moment.get("status") == "locked" else None
        lock = causal_bar_lock(candles, action=research_action if isinstance(research_action, str) else None)
        lock.update(
            {
                "bars_read": len(payload["candles"]),
                "action": research_action,
                "direction": str(signal.direction),
                "stop_loss_price": moment.get("stop_loss_price"),
                "take_profit_price": moment.get("take_profit_price"),
                "stance": recommendation.get("stance", "abstain"),
                "may_propose_order": False,
                "feed_origin": feed_origin,
                "execution_permission": "none",
            }
        )
        payload["bar_lock"] = lock
    observer = _mount_online_observer(
        sym,
        candles,
        bucket_seconds=bucket_used,
        feed_origin=feed_origin,
        chart_source=chart_source,
        learning_allowed=bool(getattr(gateway, "public_fetch_enabled", True)),
        public_as_of=public_as_of,
    )
    if observer is not None:
        payload["online_observer"] = observer
        payload["realtime_layer"] = {
            "method": "online_logistic_observer",
            "horizon_seconds": bucket_used,
            "probability_up": observer.get("probability_up"),
            "direction": observer.get("direction"),
            "status": observer.get("status"),
            "execution_permission": "none",
            "notice": (
                "Short-horizon online observer on the same completed public candles as the "
                "daily whale policy. Experimental; not calibrated; no order authority."
            ),
        }
    return payload


def _read_book_row(
    gateway: LiveMarketDataGateway,
    model: WhalePolicyModel,
    item: str,
    *,
    bucket_seconds: int,
    books_mode: Literal["full", "compact"],
    active_symbol: str,
) -> dict[str, Any]:
    if item == active_symbol:
        return read_symbol_chart(
            gateway,
            model,
            item,
            bucket_seconds=bucket_seconds,
            limit=120,
            include_whale_moment=True,
        )
    if books_mode == "full":
        return read_symbol_chart(
            gateway,
            model,
            item,
            bucket_seconds=bucket_seconds,
            limit=48,
            include_whale_moment=False,
        )
    key = (item, bucket_seconds)
    cached = _BOOK_ROW_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _book_cache_ttl(bucket_seconds):
        return cached[1]
    row = read_symbol_chart(
        gateway,
        model,
        item,
        bucket_seconds=bucket_seconds,
        limit=32,
        include_whale_moment=False,
    )
    _BOOK_ROW_CACHE[key] = (now, row)
    return row


def read_market_charts(
    gateway: LiveMarketDataGateway,
    model: WhalePolicyModel,
    *,
    symbol: str = "BTC-USD",
    bucket_seconds: int = 60,
    model_for: Any = None,
    books_mode: Literal["full", "compact"] = "full",
) -> dict[str, Any]:
    """Score the active chart plus both books. No order is submitted."""
    active_symbol = symbol.upper().strip()
    # A Real time viewer must not register unrelated listings as watched feeds.
    universe = ([active_symbol] if bucket_seconds == 1 else
                list(dict.fromkeys((*COMPETITION_SYMBOLS, *OPEN_MARKET_SYMBOLS, active_symbol))))

    def pick(item: str) -> WhalePolicyModel:
        if model_for is None:
            return model
        chosen = model_for(item)
        return chosen if isinstance(chosen, WhalePolicyModel) else model

    rows = [
        _read_book_row(
            gateway,
            pick(item),
            item,
            bucket_seconds=bucket_seconds,
            books_mode=books_mode,
            active_symbol=active_symbol,
        )
        for item in universe
    ]
    by_symbol = {row["symbol"]: row for row in rows}
    active = by_symbol[active_symbol]
    from atlas.marketdata.tradingview import describe_chart

    picture = describe_chart(active_symbol, bucket_seconds=bucket_seconds)
    follows = str(picture.get("model_reads") or "")
    if bucket_seconds == 1:
        relation = "same_public_trade_feed"
        track_notice = "The embedded chart and observer read the same Coinbase trade feed; only completed bars train the observer."
    elif (picture.get("available") is True and follows == "same_symbol_and_resolution_on_the_public_candle_path"
            and active.get("chart_source") == "public_market_candles"
            and active.get("bucket_seconds") == bucket_seconds):
        relation = "same_symbol_and_interval"
        track_notice = (
            "The model follows this TradingView chart's symbol and interval on the public-candle path. "
            "The widget keeps its bars. Nothing is sent."
        )
    elif picture.get("available") is True:
        relation = "picture_only"
        track_notice = "This TradingView chart has no public-candle series for the model. Nothing is sent."
    else:
        relation = "no_picture"
        track_notice = "This symbol has no TradingView chart at this interval. Nothing is sent."
    return {
        "status": "ok",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "active": active,
        "competition": [by_symbol[item] for item in COMPETITION_SYMBOLS if item in by_symbol],
        "open_market": [by_symbol[item] for item in OPEN_MARKET_SYMBOLS if item in by_symbol],
        "tradingview": picture,
        "chart_track": {
            "picture": picture.get("tradingview_symbol"),
            "interval": picture.get("interval"),
            "timeframe": picture.get("timeframe"),
            "model_symbol": picture.get("model_symbol"),
            "follows": relation,
            "bars_from_tradingview": False,
            "execution_permission": "none",
            "notice": track_notice,
        },
        "execution_permission": "none",
    }
