"""Persistent experimental observer of completed, source-backed market bars.

Predictions are scored against later observed outcomes before any update.
No execution integration or independently validated trading claim is implied.
"""
from __future__ import annotations

from copy import deepcopy
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from atlas.marketdata.live_artifacts import artifact_store

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Market timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _features(bars: list[dict[str, Any]]) -> list[float]:
    closes = [float(bar["close"]) for bar in bars]
    clip = lambda value: max(-3.0, min(3.0, value))
    last = bars[-1]
    return [clip((closes[-1] / closes[-2] - 1) * 1000),
            clip((closes[-1] / closes[-4] - 1) * 1000),
            (float(last["close"]) - float(last["open"])) / max(float(last["high"]) - float(last["low"]), 1e-9)]


def _completed_rows(bars: list[dict[str, Any]], watermark: datetime, bucket: int) -> tuple[list[dict[str, Any]], int]:
    valid = {}
    rejected = 0
    for bar in bars:
        try:
            stamp = _time(bar["timestamp"])
            prices = [float(bar[key]) for key in ("open", "high", "low", "close")]
            volume = float(bar.get("volume", 0))
            if not all(math.isfinite(value) and value > 0 for value in prices) or not math.isfinite(volume) or volume < 0:
                raise ValueError("Invalid candle values")
            open_px, high, low, close = prices
            if low > min(open_px, close) or high < max(open_px, close) or bar.get("incomplete"):
                raise ValueError("Invalid or incomplete candle")
            if stamp + timedelta(seconds=bucket) <= watermark:
                normalized = stamp.isoformat()
                valid[normalized] = {**bar, "timestamp": normalized}
        except (ValueError, TypeError, KeyError, OverflowError):
            rejected += 1
    return [valid[key] for key in sorted(valid)], rejected


def _metrics(state: dict[str, Any]) -> dict[str, Any]:
    stats = state.get("evaluation") or {}
    count = int(stats.get("count", 0))
    return {"samples_evaluated": count, "brier_score": stats.get("brier_sum", 0) / count if count else None,
            "log_loss": stats.get("log_loss_sum", 0) / count if count else None,
            "directional_accuracy": stats.get("correct", 0) / count if count else None,
            "baseline_brier_score": 0.25, "baseline_log_loss": math.log(2),
            "scope": "prequential_before_update", "validated": False,
            "notice": "Scores cover later outcomes recorded since evaluation was enabled. They are online diagnostics, not independent validation."}


def observe_public_bars(symbol: str, bars: list[dict[str, Any]], *, now: datetime | None = None,
                        bucket_seconds: int = 1, feed_origin: str = "coinbase_exchange_public",
                        learning_allowed: bool = True, pause_reason: str | None = None,
                        completed_through: datetime | None = None,
                        state_scope: str | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    bucket_seconds = max(1, int(bucket_seconds))
    watermark = min(moment, completed_through) if completed_through is not None else moment
    max_gap = 10 if bucket_seconds == 1 else bucket_seconds * 2
    stale_after = 15 if bucket_seconds == 1 else bucket_seconds * 3
    state_key = symbol if bucket_seconds == 1 and feed_origin == "coinbase_exchange_public" else f"{symbol}|{feed_origin}|{bucket_seconds}s"
    if state_scope:
        state_key += f"|permission:{state_scope}"
    store = artifact_store()
    rows, rejected = _completed_rows(bars, watermark, bucket_seconds)
    incomplete_times = set()
    for bar in bars:
        if isinstance(bar, dict) and bar.get("incomplete"):
            try:
                incomplete_times.add(_time(bar["timestamp"]))
            except (ValueError, TypeError, KeyError):
                pass
    base = {"method": "online_logistic_observer", "execution_permission": "none", "orders_submitted": 0,
            "persistence": "sqlite_checkpoint" if store else "session_only", "bucket_seconds": bucket_seconds, "feed_origin": feed_origin,
            "outcome_horizon_seconds": max_gap, "warmup_target": 8, "rejected_bars": rejected,
            "input_watermark_at": watermark.isoformat(), "data_use_scope": state_scope,
            "horizon": f"next received completed {bucket_seconds}-second bar, at most {max_gap} seconds later",
            "features_used": ["last_return_x1000_clipped", "three_bar_return_x1000_clipped", "candle_body_over_range"]}
    with _LOCK:
        if state_key not in _SESSIONS:
            _SESSIONS[state_key] = (store.restore(state_key) if store else None) or {
                "weights": [0.0, 0.0, 0.0], "bias": 0.0, "samples": 0,
                "pending": None, "history": [], "skipped": 0}
        # Do not publish a changed in-memory fit before its transaction commits.
        state = deepcopy(_SESSIONS[state_key])
        def summary(status: str, notice: str) -> dict[str, Any]:
            pending = state.get("pending") or {}
            return {**base, "status": status, "notice": notice, "candles": rows,
                    "direction": "WITHHELD", "probability_up": None,
                    "samples_learned": state["samples"], "warmup_remaining": max(0, 8 - state["samples"]),
                    "skipped_outcomes": state["skipped"], "weights": list(state["weights"]), "bias": state["bias"],
                    "prediction_at": pending.get("timestamp"), "feature_values": list(pending.get("features", [])),
                    "recent_outcomes": list(state["history"]), "metrics": _metrics(state),
                    "feed_age_seconds": (moment - _time(rows[-1]["timestamp"])).total_seconds() if rows else None}
        if not learning_allowed:
            return summary("paused", pause_reason or "Source is not healthy. Saved learning is retained; no update is made.")
        if len(rows) < 4:
            return summary("waiting", "Waiting for four completed real market bars. No fixture is substituted.")
        last_time = _time(rows[-1]["timestamp"])
        if (moment - last_time).total_seconds() > stale_after:
            return summary("stale", f"The latest real bar is over {stale_after} seconds old. Learning and interpretation are withheld; this may reflect provider delay or a closed market.")
        if any((_time(b["timestamp"]) - _time(a["timestamp"])).total_seconds() > max_gap for a, b in zip(rows[-4:], rows[-3:])):
            return summary("waiting", "The feature window contains a market-data gap. Waiting for consecutive completed inputs.")
        if any(_time(rows[-4]["timestamp"]) <= stamp <= last_time for stamp in incomplete_times):
            return summary("waiting", "Known missing trades affect the feature window. Waiting for complete source inputs.")
        pending = state["pending"]
        if pending and last_time < _time(pending["timestamp"]):
            return summary("out_of_order", "An older snapshot arrived. The newer learned state is retained without training.")
        changed = False
        artifacts = []
        if pending:
            future = [bar for bar in rows if _time(bar["timestamp"]) > _time(pending["timestamp"])]
            if future:
                target = future[0]
                changed = True
                gap = (_time(target["timestamp"]) - _time(pending["timestamp"])).total_seconds()
                contaminated = (any(_time(pending["timestamp"]) <= stamp <= _time(target["timestamp"]) for stamp in incomplete_times)
                                or any(_time(stamp) in incomplete_times for stamp in pending.get("input_timestamps", [pending["timestamp"]])))
                if not contaminated and gap <= max_gap and float(target["close"]) != pending["close"]:
                    outcome = 1.0 if float(target["close"]) > pending["close"] else 0.0
                    probability = pending["probability_up"]
                    # Score the saved forecast before adapting its coefficients.
                    stats = state.setdefault("evaluation", {"count": 0, "brier_sum": 0.0, "log_loss_sum": 0.0, "correct": 0})
                    stats["count"] += 1
                    stats["brier_sum"] += (probability - outcome) ** 2
                    clipped = max(1e-12, min(1 - 1e-12, probability))
                    stats["log_loss_sum"] += -(outcome * math.log(clipped) + (1 - outcome) * math.log(1 - clipped))
                    stats["correct"] += int((probability >= .5) == bool(outcome))
                    error = probability - outcome
                    state["weights"] = [w - 0.05 * error * feature for w, feature in zip(state["weights"], pending["features"])]
                    state["bias"] -= 0.05 * error
                    state["samples"] += 1
                    state["history"].append({"predicted_at": pending["timestamp"], "resolved_at": target["timestamp"],
                                             "probability_up": probability, "outcome": "UP" if outcome else "DOWN"})
                    state["history"] = state["history"][-12:]
                    artifacts.append(("outcome", state_key, pending["timestamp"], {**state["history"][-1], "inputs": pending,
                                      "weights_after": list(state["weights"]), "bias_after": state["bias"], "metrics": _metrics(state)}))
                else:
                    state["skipped"] += 1
                    reason = "known_missing_trades" if contaminated else "gap_over_outcome_horizon" if gap > max_gap else "unchanged_price"
                    artifacts.append(("skipped_outcome", state_key, pending["timestamp"], {"reason": reason,
                                      "outcome_horizon_seconds": max_gap, "prediction": pending, "target": target}))
                state["pending"] = None
        features = _features(rows)
        pending = state["pending"]
        if pending is None or last_time > _time(pending["timestamp"]):
            score = state["bias"] + sum(w * feature for w, feature in zip(state["weights"], features))
            probability = 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))
            state["pending"] = {"timestamp": rows[-1]["timestamp"], "close": float(rows[-1]["close"]),
                                "features": features, "probability_up": probability,
                                "input_timestamps": [bar["timestamp"] for bar in rows[-4:]]}
            changed = True
            artifacts.append(("prediction", state_key, rows[-1]["timestamp"], {**state["pending"], "symbol": symbol,
                              "feed_origin": feed_origin, "bucket_seconds": bucket_seconds, "weights": list(state["weights"]),
                              "bias": state["bias"], "model_version": "online_logistic_observer:v1", "input_bars": rows[-4:]}))
        if changed and store:
            store.commit_observation(state_key, state, artifacts)
        _SESSIONS[state_key] = state
        probability = state["pending"]["probability_up"]
        result = summary("warming_up" if state["samples"] < 8 else "learning",
                         "Experimental online fit. Eight labeled outcomes ends initialization, not validation. Probabilities remain uncalibrated.")
        result.update(probability_up=probability, direction="OBSERVING" if state["samples"] < 8 else "UP" if probability > .55 else "DOWN" if probability < .45 else "UNCERTAIN")
        return result
