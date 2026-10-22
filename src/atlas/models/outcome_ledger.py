"""Daily trend ledger.

One open forecast per symbol and horizon. The primary side is the sign of the
last 20 daily closes. A logistic fit on earlier closes has to agree with that
side and sit outside the abstain band, or the forecast is recorded and not
scored. Abstentions are coverage. Fixture rows are shown and left out of the
proof set. Nothing here submits an order.

The lookback is the short end of the 1-to-12-month trend band in Moskowitz,
Ooi, and Pedersen (Journal of Financial Economics, 2012). The filter is the
side-versus-size split in López de Prado, Advances in Financial Machine
Learning (2018), chapter 3: the rule picks the side, and the logistic model
may set the size to zero. Round-trip costs match the range garden: twice the
fee plus the half spread.
"""

from __future__ import annotations

import random
import time
from typing import Any

from atlas.models.whale_policy import WhalePolicyTrainer

PATH_ID = "daily-trend-outcome-ledger:v1"
HORIZON_ID = "next_daily_close"
LOOKBACK_BARS = 20
MIN_FILTER_ROWS = 12
ABSTAIN_LOW = 0.45
ABSTAIN_HIGH = 0.55
MIN_RESOLVED_TO_JUDGE = 60
MIN_CALIBRATION_ROWS = 30
CALIBRATION_BINS = 5
LOGISTIC_ITERATIONS = 40
COMPETITION_SYMBOLS = ("BTC-USD", "ETH-USD", "SOL-USD")
OPEN_MARKET_SYMBOLS = ("SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")
ROUND_TRIP_BPS = {"competition": 16.0, "open_market": 4.0}
_CACHE: dict[str, Any] = {"key": None, "report": None, "at": 0.0}


def combine_stance(primary_side: str, probability: float | None) -> tuple[str, str | None]:
    """Return the research stance and, when it abstains, the reason."""
    side = primary_side.upper()
    if side not in {"BUY", "SELL"}:
        return "abstain", "no_trend"
    if probability is None:
        return "abstain", "filter_not_fit"
    if ABSTAIN_LOW <= probability <= ABSTAIN_HIGH:
        return "abstain", "uncertain"
    logistic_side = "BUY" if probability > 0.5 else "SELL"
    if logistic_side != side:
        return "abstain", "disagreed"
    return ("research_long" if side == "BUY" else "research_short"), None


def _closes(candles: list[dict[str, Any]]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for bar in candles:
        if bar.get("timestamp") is None:
            continue
        try:
            close = float(bar["close"])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        rows.append((str(bar["timestamp"]), close))
    rows.sort(key=lambda item: item[0])
    return rows


def _primary_side(closes: list[float], index: int) -> str:
    if index < LOOKBACK_BARS:
        return "FLAT"
    earlier = closes[index - LOOKBACK_BARS]
    if earlier <= 0:
        return "FLAT"
    change = closes[index] / earlier - 1.0
    if change > 0:
        return "BUY"
    if change < 0:
        return "SELL"
    return "FLAT"


def _fit_probability(closes: list[float], index: int) -> float | None:
    trainer = WhalePolicyTrainer
    features: list[tuple[float, ...]] = []
    outcomes: list[int] = []
    for prior in range(index):
        if prior + 1 > index:
            break
        vector = trainer._causal_feature_vector(closes, prior)
        if vector is None or prior + 1 >= len(closes):
            continue
        features.append(vector)
        outcomes.append(1 if closes[prior + 1] > closes[prior] else 0)
    if len(features) < MIN_FILTER_ROWS:
        return None
    weights, intercept = trainer._fit_policy_weights(
        features,
        outcomes,
        iterations=LOGISTIC_ITERATIONS,
    )
    current = trainer._causal_feature_vector(closes, index)
    if current is None:
        return None
    score = intercept + sum(weight * value for weight, value in zip(weights, current))
    return trainer._sigmoid(score)


def _net_return(side: str, entry: float, exit_price: float, cost_fraction: float) -> float:
    gross = exit_price / entry - 1.0
    signed = gross if side == "BUY" else -gross
    return signed - cost_fraction


def _walk_symbol(frame: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(frame.get("symbol") or "").upper()
    track = str(frame.get("track") or ("competition" if symbol.endswith("-USD") else "open_market"))
    if track not in ROUND_TRIP_BPS:
        track = "open_market"
    data_mode = str(frame.get("data_mode") or "unlabeled")
    feed_origin = str(frame.get("feed_origin") or "unlabeled")
    series = _closes(list(frame.get("candles") or []))
    if len(series) <= LOOKBACK_BARS:
        return []
    stamps = [item[0] for item in series]
    closes = [item[1] for item in series]
    cost_fraction = ROUND_TRIP_BPS[track] / 10_000.0
    decisions: list[dict[str, Any]] = []
    last = len(closes) - 1
    for index in range(LOOKBACK_BARS, len(closes)):
        primary = _primary_side(closes, index)
        probability = _fit_probability(closes, index)
        stance, reason = combine_stance(primary, probability)
        resolved = index < last
        entry = closes[index]
        exit_price = closes[index + 1] if resolved else None
        taken = stance in {"research_long", "research_short"}
        net = (
            _net_return(primary, entry, float(exit_price), cost_fraction)
            if resolved and taken and exit_price is not None
            else None
        )
        decisions.append(
            {
                "symbol": symbol,
                "track": track,
                "horizon_id": HORIZON_ID,
                "decision_timestamp": stamps[index],
                "resolve_timestamp": stamps[index + 1] if resolved else None,
                "status": "resolved" if resolved else "open",
                "primary_side": primary,
                "filter_probability": None if probability is None else round(probability, 6),
                "stance": stance,
                "abstain_reason": reason,
                "entry_close": entry,
                "exit_close": exit_price,
                "cost_bps": ROUND_TRIP_BPS[track],
                "net_return": None if net is None else round(net, 8),
                "data_mode": data_mode,
                "feed_origin": feed_origin,
                "counts_toward_proof": data_mode == "public_market_candles" and taken and resolved,
                "execution_permission": "none",
                "may_propose_order": False,
            }
        )
    return decisions


def _bootstrap_mean(values: list[float]) -> tuple[float, float]:
    rng = random.Random(0)
    samples = 200
    block_size = 2
    boots: list[float] = []
    width = len(values)
    for _ in range(samples):
        drawn: list[float] = []
        while len(drawn) < width:
            start = rng.randrange(width)
            drawn.extend(values[(start + offset) % width] for offset in range(block_size))
        piece = drawn[:width]
        boots.append(sum(piece) / len(piece))
    boots.sort()
    return boots[int(0.025 * samples)], boots[min(samples - 1, int(0.975 * samples))]


def _reliability(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate the next-close direction, the costed trade, and execution.

    The filter probability is a claim that the next close is higher. Brier
    scores that claim on public rows whose close has already printed. It does
    not refit the logistic model and it does not change the costed judgment.
    """
    public = [
        row for row in decisions
        if row["status"] == "resolved"
        and row["data_mode"] == "public_market_candles"
        and row.get("exit_close") is not None
        and row.get("entry_close")
    ]
    taken = [row for row in public if row["counts_toward_proof"]]
    direction_hits = 0
    for row in taken:
        gross = float(row["exit_close"]) / float(row["entry_close"]) - 1.0
        signed = gross if row["primary_side"] == "BUY" else -gross
        if signed > 0:
            direction_hits += 1
    scored: list[tuple[float, int]] = []
    for row in public:
        probability = row.get("filter_probability")
        if probability is None:
            continue
        scored.append((float(probability), 1 if float(row["exit_close"]) > float(row["entry_close"]) else 0))
    brier = sum((probability - outcome) ** 2 for probability, outcome in scored) / len(scored) if scored else None
    bins: list[dict[str, Any]] = []
    if scored:
        counts = [0] * CALIBRATION_BINS
        predicted = [0.0] * CALIBRATION_BINS
        observed = [0] * CALIBRATION_BINS
        for probability, outcome in scored:
            index = min(CALIBRATION_BINS - 1, int(max(0.0, min(probability, 0.999999)) * CALIBRATION_BINS))
            counts[index] += 1
            predicted[index] += probability
            observed[index] += outcome
        for index, count in enumerate(counts):
            bins.append(
                {
                    "lower": round(index / CALIBRATION_BINS, 2),
                    "upper": round((index + 1) / CALIBRATION_BINS, 2),
                    "count": count,
                    "mean_predicted": None if count == 0 else round(predicted[index] / count, 4),
                    "observed_up_rate": None if count == 0 else round(observed[index] / count, 4),
                }
            )
    if len(scored) < MIN_CALIBRATION_ROWS:
        confidence = "too_few_to_calibrate"
        notice = (
            f"{len(scored)} public forecasts have a probability and a later close. "
            f"{MIN_CALIBRATION_ROWS} are required before that probability is treated as a confidence."
        )
    else:
        confidence = "scored"
        notice = (
            "Brier scores the filter probability against the next close being higher. "
            "A direction hit is not a profitable trade, and neither one is an execution."
        )
    return {
        "direction_hits": direction_hits,
        "direction_attempts": len(taken),
        "direction_hit_rate": None if not taken else round(direction_hits / len(taken), 4),
        "confidence": confidence,
        "brier_score": None if brier is None else round(brier, 6),
        "calibration_rows": len(scored),
        "required_calibration_rows": MIN_CALIBRATION_ROWS,
        "bins": bins,
        "execution": "not_attempted",
        "execution_notice": "No order was sent. Execution is a separate question from the forecast.",
        "notice": notice,
        "execution_permission": "none",
    }


def _judge(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    abstentions = sum(1 for row in decisions if row["status"] == "resolved" and row["stance"] == "abstain")
    proof = [row for row in decisions if row["counts_toward_proof"]]
    by_symbol: dict[str, list[float]] = {}
    for row in proof:
        by_symbol.setdefault(str(row["symbol"]), []).append(float(row["net_return"]))
    positive_symbols = [
        symbol
        for symbol, nets in by_symbol.items()
        if nets and sum(nets) / len(nets) > 0
    ]
    mean_net = sum(float(row["net_return"]) for row in proof) / len(proof) if proof else None
    interval = _bootstrap_mean([float(row["net_return"]) for row in proof]) if len(proof) >= MIN_RESOLVED_TO_JUDGE else None
    if len(proof) < MIN_RESOLVED_TO_JUDGE:
        judgment = "too_few_to_judge"
        notice = (
            f"{len(proof)} public resolved stances. {MIN_RESOLVED_TO_JUDGE} are required. "
            "Abstentions are not wins or losses. Fixture rows are not in this count."
        )
    elif (
        mean_net is not None
        and mean_net > 0
        and interval is not None
        and interval[0] > 0
        and len(positive_symbols) >= 2
    ):
        judgment = "supported_on_this_sample"
        notice = (
            "The costed edge on this public sample is above doing nothing, and at least two symbols contribute. "
            "This is not a competition result and it cannot send an order."
        )
    else:
        judgment = "not_supported"
        notice = (
            "This public sample is large enough to score and does not clear the costed, two-symbol test. "
            "Nothing is promoted and nothing is sent."
        )
    return {
        "judgment": judgment,
        "resolved_rows": sum(1 for row in decisions if row["status"] == "resolved"),
        "abstentions": abstentions,
        "public_resolved_stances": len(proof),
        "required_resolved_stances": MIN_RESOLVED_TO_JUDGE,
        "symbols_with_positive_mean": len(positive_symbols),
        "mean_net_return": None if mean_net is None else round(mean_net, 8),
        "bootstrap_interval": None if interval is None else [round(interval[0], 8), round(interval[1], 8)],
        "notice": notice,
        "reliability": _reliability(decisions),
        "execution_permission": "none",
    }


def build_outcome_ledger(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Score each frame causally. The next close is applied only after the stance is chosen."""
    decisions: list[dict[str, Any]] = []
    for frame in frames:
        decisions.extend(_walk_symbol(frame))
    decisions.sort(key=lambda row: (str(row["track"]), str(row["symbol"]), str(row["decision_timestamp"])))
    opens = [row for row in decisions if row["status"] == "open"]
    tracks = {
        track: _judge([row for row in decisions if row["track"] == track])
        for track in ("competition", "open_market")
    }
    return {
        "path_id": PATH_ID,
        "horizon_id": HORIZON_ID,
        "lookback_bars": LOOKBACK_BARS,
        "hypothesis": (
            "The sign of the last 20 daily closes continues to the next close often enough "
            "to beat the round-trip cost."
        ),
        "filter": (
            "A logistic fit on earlier closes must agree with that sign and sit outside "
            "0.45 to 0.55. Otherwise the forecast abstains."
        ),
        "cost_bps": dict(ROUND_TRIP_BPS),
        "symbols": {
            "competition": list(COMPETITION_SYMBOLS),
            "open_market": list(OPEN_MARKET_SYMBOLS),
        },
        "tracks": tracks,
        "open_forecasts": opens,
        "recent_resolved": [row for row in decisions if row["status"] == "resolved"][-12:],
        "decisions": decisions,
        "orders_submitted": 0,
        "may_propose_order": False,
        "execution_permission": "none",
        "notice": (
            "One open forecast per symbol. A later daily close resolves it. "
            "Fewer than 60 public stances on a track is too few to judge."
        ),
    }


def compact_outcome_ledger(report: dict[str, Any]) -> dict[str, Any]:
    """Drop the full decision list before the training status payload stores it."""
    kept = dict(report)
    kept.pop("decisions", None)
    return kept


def ledger_from_gateway(gateway: Any) -> dict[str, Any]:
    """Read the cached daily pages. This does not start a new public fetch."""
    from atlas.marketdata.bar_projection import project_symbol_bars

    frames: list[dict[str, Any]] = []
    key_parts: list[tuple[str, str, str, int, float]] = []
    for symbol in (*COMPETITION_SYMBOLS, *OPEN_MARKET_SYMBOLS):
        projected = project_symbol_bars(gateway, symbol, bucket_seconds=86_400, limit=120)
        candles = list(projected.get("candles") or [])
        data_mode = (
            "public_market_candles"
            if projected.get("chart_source") == "public_market_candles"
            else "synthetic_fixture_training"
        )
        frames.append(
            {
                "symbol": symbol,
                "track": projected.get("track"),
                "candles": candles,
                "data_mode": data_mode,
                "feed_origin": projected.get("feed_origin"),
            }
        )
        last = candles[-1] if candles else {}
        key_parts.append(
            (
                symbol,
                data_mode,
                str(last.get("timestamp") or ""),
                len(candles),
                float(last.get("close") or 0.0),
            )
        )
    key = tuple(key_parts)
    now = time.monotonic()
    if _CACHE["key"] == key and isinstance(_CACHE["report"], dict) and now - float(_CACHE["at"]) < 30:
        return _CACHE["report"]
    report = build_outcome_ledger(frames)
    _CACHE["key"] = key
    _CACHE["report"] = report
    _CACHE["at"] = now
    return report
