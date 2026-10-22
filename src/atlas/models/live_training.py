"""Desk training path `desk-public-candle-walk-forward:v1`.

One pass, both books, in this order:

1. Read the daily public candles (Coinbase for crypto, Yahoo for equities).
   A miss stays on the labeled fixture and is named as such.
2. Label only closes that have already printed.
3. Run the purged walk-forward gate on each symbol.
4. Fit one weight vector for the competition book and one for the open-market book.
5. Score those same candles with the book vector.
6. Withhold every order. A gate pass is not a competition win and is not a live order.

The chart the operator is watching is scored separately, with these book weights,
from the public bars for the timeframe on screen.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from atlas.marketdata.bar_projection import project_symbol_bars
from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.models.schemas import Observation
from atlas.models.whale_policy import WhalePolicyModel, WhalePolicyTrainer

PATH_ID = "desk-public-candle-walk-forward:v1"
TRAINING_BUCKET_SECONDS = 86_400
COMPETITION_SYMBOLS: tuple[str, ...] = ("BTC-USD", "ETH-USD", "SOL-USD")
OPEN_MARKET_SYMBOLS: tuple[str, ...] = ("SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")
_WEIGHT_KEYS = ("ofi_z", "vpin", "hawkes_ratio", "kyles_lambda")


def observations_from_candles(candles: list[dict[str, Any]]) -> list[Observation]:
    observations: list[Observation] = []
    for bar in candles:
        stamp = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        close_px = float(bar["close"])
        if close_px <= 0:
            continue
        observations.append(Observation(event_time=stamp, available_at=stamp, value=close_px))
    return observations


def _retune_weights(model: WhalePolicyModel, candles: list[dict[str, Any]]) -> None:
    """Causal retune from closes already printed. No future bar enters the weight."""
    closes = [float(bar["close"]) for bar in candles if float(bar["close"]) > 0]
    if len(closes) < 8:
        return
    ups = sum(1 for prev, close in zip(closes, closes[1:]) if close >= prev)
    persistence = ups / max(1, len(closes) - 1)
    model.weights = {
        "ofi_z": round(0.22 + 0.20 * persistence, 4),
        "vpin": round(0.42 - 0.16 * persistence, 4),
        "hawkes_ratio": 0.18,
        "kyles_lambda": round(0.18 - 0.04 * persistence, 4),
    }


def _gate_failures(report: Any) -> list[str]:
    failures: list[str] = []
    if not report.causal_walk_forward_verified:
        failures.append("causal_walk_forward")
    if float(report.oos_sharpe_ratio) <= 1.80:
        failures.append("sharpe")
    if float(report.oos_max_drawdown_fraction) >= 0.032:
        failures.append("drawdown")
    if float(report.oos_brier_score) >= 0.180:
        failures.append("brier")
    return failures


def _average_weights(models: list[WhalePolicyModel]) -> dict[str, float]:
    if not models:
        return dict(WhalePolicyModel().weights)
    return {
        key: round(sum(float(model.weights[key]) for model in models) / len(models), 4)
        for key in _WEIGHT_KEYS
    }


def _book_model(track: str, members: list[WhalePolicyModel], *, promoted: bool) -> WhalePolicyModel:
    version = "v2" if promoted and members else "v1"
    model = WhalePolicyModel(model_id=f"whale_policy_gbdt_ac:{track}:{version}")
    model.weights = _average_weights(members)
    return model


def execute_training_path(
    gateway: LiveMarketDataGateway,
    trainer: WhalePolicyTrainer,
) -> dict[str, Any]:
    """Run the six-stage desk path once. No order is submitted."""
    datasets: dict[str, dict[str, Any]] = {}
    for sym in (*COMPETITION_SYMBOLS, *OPEN_MARKET_SYMBOLS):
        datasets[sym] = project_symbol_bars(
            gateway,
            sym,
            bucket_seconds=TRAINING_BUCKET_SECONDS,
            limit=120,
        )
    public_count = sum(1 for item in datasets.values() if item["chart_source"] == "public_market_candles")
    read_stage = {
        "name": "read_public_candles",
        "status": "done",
        "bucket_seconds": TRAINING_BUCKET_SECONDS,
        "public_symbols": public_count,
        "fixture_symbols": len(datasets) - public_count,
        "execution_permission": "none",
    }

    rows: list[dict[str, Any]] = []
    members: dict[str, list[WhalePolicyModel]] = {"competition": [], "open_market": []}
    promoted_tracks: set[str] = set()
    labeled = 0
    for sym, projected in datasets.items():
        candles = list(projected["candles"])
        data_mode = (
            "public_market_candles"
            if projected["chart_source"] == "public_market_candles"
            else "synthetic_fixture_training"
        )
        track = str(projected["track"])
        try:
            observations = observations_from_candles(candles)
            labeled += 1
            model, report = trainer.train_and_evaluate(symbol=sym, observations=observations)
            _retune_weights(model, candles)
            members[track].append(model)
            failures = _gate_failures(report)
            if report.promoted and data_mode == "public_market_candles":
                promoted_tracks.add(track)
            rows.append(
                {
                    "symbol": sym,
                    "track": track,
                    "status": "trained",
                    "data_mode": data_mode,
                    "feed_origin": projected["feed_origin"],
                    "bars": projected["bar_count"],
                    "model_id": report.model_id,
                    "promoted": bool(report.promoted),
                    "gate_failures": failures,
                    "paper_ready": bool(report.promoted) and data_mode == "public_market_candles",
                    "oos_sharpe_ratio": report.oos_sharpe_ratio,
                    "oos_brier_score": report.oos_brier_score,
                    "oos_max_drawdown_fraction": report.oos_max_drawdown_fraction,
                    "promotion_reason": report.promotion_reason,
                    "candles": candles,
                    "execution_permission": "none",
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "symbol": sym,
                    "track": track,
                    "status": "not_trained",
                    "data_mode": data_mode,
                    "feed_origin": projected["feed_origin"],
                    "bars": len(candles),
                    "gate_failures": ["not_trained"],
                    "paper_ready": False,
                    "reason": str(exc),
                    "execution_permission": "none",
                }
            )

    competition_model = _book_model(
        "competition",
        members["competition"],
        promoted="competition" in promoted_tracks,
    )
    open_model = _book_model(
        "open_market",
        members["open_market"],
        promoted="open_market" in promoted_tracks,
    )
    for row in rows:
        candles = row.pop("candles", None)
        if row["status"] != "trained" or not candles:
            continue
        book = competition_model if row["track"] == "competition" else open_model
        signal = book.predict(symbol=str(row["symbol"]), candles=candles)
        row["direction"] = signal.direction
        row["conviction"] = signal.conviction
        row["scored_with"] = book.model_id
    trained = [row for row in rows if row["status"] == "trained"]
    stages = [
        read_stage,
        {
            "name": "label_printed_closes",
            "status": "done" if labeled else "skipped",
            "symbols_labeled": labeled,
            "execution_permission": "none",
        },
        {
            "name": "walk_forward_gate",
            "status": "done" if trained else "skipped",
            "trained_symbols": len(trained),
            "promoted_symbols": sum(1 for row in trained if row["promoted"]),
            "execution_permission": "none",
        },
        {
            "name": "fit_track_weights",
            "status": "done",
            "competition_model_id": competition_model.model_id,
            "open_market_model_id": open_model.model_id,
            "execution_permission": "none",
        },
        {
            "name": "score_both_books",
            "status": "done" if trained else "skipped",
            "scored_symbols": sum(1 for row in rows if row.get("direction")),
            "execution_permission": "none",
        },
        {
            "name": "withhold_orders",
            "status": "done",
            "orders_submitted": 0,
            "paper_handoff": "withheld_until_a_public_bar_gate_pass_is_sent_through_the_control_plane",
            "execution_permission": "none",
        },
    ]
    report = {
        "status": "ok" if trained else "no_trainable_bars",
        "path_id": PATH_ID,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "stages": stages,
        "served_model_id": competition_model.model_id,
        "competition_model_id": competition_model.model_id,
        "open_market_model_id": open_model.model_id,
        "served_model": competition_model,
        "competition_model": competition_model,
        "open_market_model": open_model,
        "competition": [row for row in rows if row["track"] == "competition"],
        "open_market": [row for row in rows if row["track"] == "open_market"],
        "order_authority": "control_plane_only",
        "orders_submitted": 0,
        "paper_trading": "path scored both books and withheld every order; a gate pass is not a competition win",
        "execution_permission": "none",
    }
    _attach_outcome_ledger(report, datasets)
    return report


def _attach_outcome_ledger(report: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> None:
    """Record the daily trend ledger beside the fit. It does not change the served weights."""
    from atlas.models.outcome_ledger import build_outcome_ledger, compact_outcome_ledger

    frames = []
    for symbol, projected in datasets.items():
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
    report["outcome_ledger"] = compact_outcome_ledger(build_outcome_ledger(frames))


def train_live_books(
    gateway: LiveMarketDataGateway,
    trainer: WhalePolicyTrainer,
    *,
    served_model: WhalePolicyModel,
) -> dict[str, Any]:
    """Run the desk path. `served_model` remains the fallback book vector until the path fits one."""
    report = execute_training_path(gateway, trainer)
    if not report["competition_model"].weights:
        report["competition_model"] = served_model
        report["served_model"] = served_model
    return report
