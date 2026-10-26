"""SQLite forecast ledger, paper-engine state serialization, and forecast resolution for the vertical slice."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from atlas.control.advanced_integration import (
    EnhancedControlPlaneEngine,
    create_enhanced_control_plane,
)
from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableOrderDecision,
    ActionableOrderRequest,
    ActionablePositionRecord,
)
from atlas.control.uncertainty_gating import UncertaintyGatingConfig
from atlas.research.vertical_slice_features import (
    CLASS_INDEX,
    CLASS_NAMES,
    DEFAULT_DB_PATH,
    PAPER_ENGINE_ID,
    PAPER_STATE_KEY,
    PATH_ID,
    ROUND_TRIP_BPS,
    Candle,
    SliceConfig,
    _classify,
    _utc,
)
from atlas.strategies.base import StrategySignal

# ---------------------------------------------------------------------------
# Persistent ledger
# ---------------------------------------------------------------------------


class ForecastLedger:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    path_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    model_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forecasts (
                    forecast_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    track TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    decision_time TEXT NOT NULL,
                    target_time TEXT NOT NULL,
                    bucket_seconds INTEGER,
                    horizon_steps INTEGER,
                    reference_price REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    probabilities_json TEXT NOT NULL,
                    predicted_class TEXT NOT NULL,
                    action TEXT NOT NULL,
                    action_reason TEXT,
                    confidence REAL NOT NULL,
                    edge REAL NOT NULL,
                    interval_low REAL,
                    interval_high REAL,
                    cost_bps REAL NOT NULL,
                    status TEXT NOT NULL,
                    realized_return REAL,
                    realized_class TEXT,
                    brier_score REAL,
                    resolved_at TEXT,
                    execution_permission TEXT NOT NULL DEFAULT 'none'
                );
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id TEXT PRIMARY KEY,
                    forecast_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    track TEXT NOT NULL,
                    side TEXT NOT NULL,
                    requested_notional_usd REAL NOT NULL,
                    authorized_notional_usd REAL,
                    control_plane_decision TEXT NOT NULL,
                    position_id TEXT,
                    order_id TEXT,
                    gate_scale REAL,
                    gate_reason TEXT,
                    violations_json TEXT NOT NULL,
                    stop_distance_bps REAL,
                    entry_price REAL,
                    status TEXT NOT NULL,
                    realized_return_net REAL,
                    realized_pnl_usd REAL,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    execution_permission TEXT NOT NULL DEFAULT 'none'
                );
                CREATE TABLE IF NOT EXISTS paper_state (
                    engine_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_forecasts_status ON forecasts(status, target_time);
                CREATE INDEX IF NOT EXISTS idx_forecasts_symbol ON forecasts(symbol, decision_time);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON paper_trades(status, forecast_id);
                """
            )
            existing = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(forecasts)").fetchall()
            }
            for column in ("bucket_seconds", "horizon_steps"):
                if column not in existing:
                    self._connection.execute(
                        f"ALTER TABLE forecasts ADD COLUMN {column} INTEGER"
                    )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record_run(self, run_id: str, created_at: datetime, config: SliceConfig, report: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO runs(run_id, created_at, path_id, config_json, report_json) VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    created_at.isoformat(),
                    PATH_ID,
                    json.dumps(config.as_dict(), sort_keys=True),
                    json.dumps(report, sort_keys=True, default=str),
                ),
            )

    def save_model(
        self,
        model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel,
        symbol: str,
        created_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO models(model_id, created_at, symbol, dataset_hash, model_json) VALUES (?, ?, ?, ?, ?)",
                (
                    model.model_id,
                    created_at.isoformat(),
                    symbol,
                    model.dataset_hash,
                    json.dumps(model.to_dict(), sort_keys=True),
                ),
            )

    def load_model(
        self, model_id: str
    ) -> SoftmaxModel | XGBoostModel | ConstantProbabilityModel | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT model_json FROM models WHERE model_id = ?", (model_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["model_json"])
        if payload.get("model_family") == XGBOOST_FAMILY:
            return XGBoostModel.from_dict(payload)
        return SoftmaxModel.from_dict(payload)

    def insert_forecast(self, payload: dict[str, Any]) -> bool:
        columns = (
            "forecast_id",
            "run_id",
            "symbol",
            "track",
            "model_id",
            "model_revision",
            "dataset_hash",
            "decision_time",
            "target_time",
            "bucket_seconds",
            "horizon_steps",
            "reference_price",
            "features_json",
            "probabilities_json",
            "predicted_class",
            "action",
            "action_reason",
            "confidence",
            "edge",
            "interval_low",
            "interval_high",
            "cost_bps",
            "status",
            "execution_permission",
        )
        values = tuple(payload.get(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"INSERT OR IGNORE INTO forecasts({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return cursor.rowcount > 0

    def insert_trade(self, payload: dict[str, Any]) -> bool:
        columns = (
            "trade_id",
            "forecast_id",
            "symbol",
            "track",
            "side",
            "requested_notional_usd",
            "authorized_notional_usd",
            "control_plane_decision",
            "position_id",
            "order_id",
            "gate_scale",
            "gate_reason",
            "violations_json",
            "stop_distance_bps",
            "entry_price",
            "status",
            "created_at",
            "execution_permission",
        )
        values = tuple(payload.get(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"INSERT OR IGNORE INTO paper_trades({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return cursor.rowcount > 0

    def open_forecasts(self, as_of: datetime) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM forecasts WHERE status = 'open' AND target_time <= ? ORDER BY target_time",
                (as_of.isoformat(),),
            ).fetchall()
        return [_decode_forecast(dict(row)) for row in rows]

    def resolve_forecast(
        self,
        forecast_id: str,
        *,
        realized_return: float,
        realized_class: str,
        brier_score: float,
        resolved_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE forecasts SET status = 'resolved', realized_return = ?,
                    realized_class = ?, brier_score = ?, resolved_at = ?
                WHERE forecast_id = ? AND status = 'open'
                """,
                (
                    realized_return,
                    realized_class,
                    brier_score,
                    resolved_at.isoformat(),
                    forecast_id,
                ),
            )

    def trade_for_forecast(self, forecast_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM paper_trades WHERE forecast_id = ?", (forecast_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def resolve_trade(
        self,
        trade_id: str,
        *,
        realized_return_net: float,
        realized_pnl_usd: float,
        resolved_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE paper_trades SET status = 'resolved', realized_return_net = ?,
                    realized_pnl_usd = ?, resolved_at = ?
                WHERE trade_id = ?
                """,
                (realized_return_net, realized_pnl_usd, resolved_at.isoformat(), trade_id),
            )

    def recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_forecasts(self, limit: int = 50, *, status: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM forecasts"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY decision_time DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [_decode_forecast(dict(row)) for row in rows]

    def latest_forecast_decision(
        self,
        symbol: str,
        horizon_steps: int | None = None,
    ) -> str | None:
        query = "SELECT decision_time FROM forecasts WHERE symbol = ?"
        params: list[Any] = [symbol.upper()]
        if horizon_steps is not None:
            query += " AND COALESCE(horizon_steps, 1) = ?"
            params.append(int(horizon_steps))
        query += " ORDER BY decision_time DESC LIMIT 1"
        with self._lock:
            row = self._connection.execute(query, tuple(params)).fetchone()
        return None if row is None else str(row["decision_time"])

    def state_keys(self, prefix: str) -> list[str]:
        escaped = (
            prefix.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._lock:
            rows = self._connection.execute(
                "SELECT engine_id FROM paper_state "
                "WHERE engine_id = ? OR engine_id LIKE ? ESCAPE '\\' "
                "ORDER BY engine_id",
                (prefix, f"{escaped}%"),
            ).fetchall()
        return [str(row["engine_id"]) for row in rows]

    def save_state(self, key: str, state: dict[str, Any], updated_at: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO paper_state(engine_id, updated_at, state_json) VALUES (?, ?, ?)",
                (key, updated_at.isoformat(), json.dumps(state, sort_keys=True, default=str)),
            )

    def load_state(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM paper_state WHERE engine_id = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row["state_json"])

    def latest_run_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._connection.execute(
                "SELECT report_json FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["report_json"]) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            total = self._connection.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
            resolved = self._connection.execute(
                "SELECT COUNT(*) AS n FROM forecasts WHERE status = 'resolved'"
            ).fetchone()["n"]
            open_rows = self._connection.execute(
                "SELECT COUNT(*) AS n FROM forecasts WHERE status = 'open'"
            ).fetchone()["n"]
            trades = [dict(row) for row in self._connection.execute(
                "SELECT * FROM paper_trades"
            ).fetchall()]
            runs = self._connection.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
            latest_run = self._connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        resolved_rows = self.recent_forecasts(500, status="resolved")
        brier_values = [row["brier_score"] for row in resolved_rows if row.get("brier_score") is not None]
        brier = float(np.mean(brier_values)) if brier_values else None
        taken = [row for row in resolved_rows if row.get("action") in ("long", "short")]
        hits = 0
        for row in taken:
            sign = 1.0 if row["action"] == "long" else -1.0
            if sign * float(row.get("realized_return") or 0.0) > 0:
                hits += 1
        authorized = [trade for trade in trades if trade["control_plane_decision"] == "authorized_paper"]
        rejected = [trade for trade in trades if trade["control_plane_decision"] != "authorized_paper"]
        resolved_trades = [trade for trade in trades if trade["status"] == "resolved"]
        pnl_values = [
            float(trade["realized_pnl_usd"])
            for trade in resolved_trades
            if trade.get("realized_pnl_usd") is not None
        ]
        report = None if latest_run is None else json.loads(latest_run["report_json"])
        return {
            "path_id": PATH_ID,
            "database": str(self.path),
            "runs": runs,
            "forecasts": {"total": total, "open": open_rows, "resolved": resolved},
            "resolved_direction_accuracy": round(hits / len(taken), 6) if taken else None,
            "resolved_taken": len(taken),
            "mean_brier_score": None if brier is None else round(brier, 8),
            "paper_trades": {
                "proposed": len([trade for trade in trades if trade["status"] != "not_proposed"]),
                "authorized": len(authorized),
                "rejected_or_not_proposed": len(rejected),
                "resolved": len(resolved_trades),
                "net_pnl_usd": round(sum(pnl_values), 2) if pnl_values else None,
                "wins": len([value for value in pnl_values if value > 0]),
                "losses": len([value for value in pnl_values if value < 0]),
            },
            "latest_run": report,
            "execution_permission": "none",
        }


def _decode_forecast(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key in ("features_json", "probabilities_json"):
        if key in decoded and isinstance(decoded[key], str):
            decoded[key.removesuffix("_json")] = json.loads(decoded[key])
            del decoded[key]
    return decoded


# ---------------------------------------------------------------------------
# Paper authorization
# ---------------------------------------------------------------------------


def build_paper_engine(
    engine_id: str = PAPER_ENGINE_ID,
    config: SliceConfig | None = None,
) -> EnhancedControlPlaneEngine:
    cfg = config or SliceConfig()
    base = ActionableControlPlaneEngine()
    base.current_equity_usd = cfg.starting_equity_usd
    base.high_water_mark_usd = cfg.starting_equity_usd
    base.start_of_day_equity_usd = cfg.starting_equity_usd
    base.gross_notional_usd = Decimal("0")
    base.correlated_exposure_usd = Decimal("0")
    base.sector_exposure_usd = Decimal("0")
    base.open_positions = []
    base.order_history = []
    base.audit_log = []
    base.completed_trading_days = max(5, base.completed_trading_days)
    base.best_day_profit_usd = Decimal("0")
    base.total_cumulative_profit_usd = Decimal("0")
    return create_enhanced_control_plane(
        engine_id,
        base,
        UncertaintyGatingConfig(
            confidence_threshold=cfg.confidence_threshold,
            interval_width_threshold=0.25,
            max_position_scale=1.0,
            min_position_scale=0.1,
        ),
    )


def _decimal_text(value: Decimal) -> str:
    return str(value)


def _max_sequence(values: Sequence[str | None], prefix: str, default: int = 1) -> int:
    highest = default
    for value in values:
        if not value or not value.startswith(prefix):
            continue
        try:
            highest = max(highest, int(value.removeprefix(prefix)))
        except ValueError:
            continue
    return highest


def serialize_paper_state(
    engine: EnhancedControlPlaneEngine,
    *,
    updated_at: datetime,
    engine_id: str = PAPER_ENGINE_ID,
) -> dict[str, Any]:
    """Serialize only the state needed to resume paper authorization.

    Closed positions are not restored; their outcomes live in the ledger. Open
    positions retain the matching order history entry because the engine reads
    entry price from ``order_history`` when it books an exit.
    """
    base = engine.base_engine
    open_positions = [position for position in base.open_positions if position.status == "open"]
    open_ids = {position.position_id for position in open_positions}
    orders = [
        order
        for order in base.order_history
        if order.position_id in open_ids and order.entry_price is not None
    ]
    return {
        "engine_id": engine_id,
        "updated_at": updated_at.isoformat(),
        "account": {
            "current_equity_usd": _decimal_text(base.current_equity_usd),
            "high_water_mark_usd": _decimal_text(base.high_water_mark_usd),
            "start_of_day_equity_usd": _decimal_text(base.start_of_day_equity_usd),
            "gross_notional_usd": _decimal_text(base.gross_notional_usd),
            "correlated_exposure_usd": _decimal_text(base.correlated_exposure_usd),
            "sector_exposure_usd": _decimal_text(base.sector_exposure_usd),
            "best_day_profit_usd": _decimal_text(base.best_day_profit_usd),
            "total_cumulative_profit_usd": _decimal_text(base.total_cumulative_profit_usd),
            "completed_trading_days": base.completed_trading_days,
        },
        "active_track": base.active_track,
        "kill_switch_engaged": base.kill_switch_engaged,
        "active_champion_model": base.active_champion_model,
        "active_challenger_model": base.active_challenger_model,
        "challenger_approved": base.challenger_approved,
        "training_runs_completed": base.training_runs_completed,
        "sequence": {"order": base._order_seq, "position": base._pos_seq},
        "open_positions": [position.model_dump(mode="json") for position in open_positions],
        "order_history": [order.model_dump(mode="json") for order in orders],
        "audit_tail": list(base.audit_log[-20:]),
        "execution_permission": "none",
    }


def restore_paper_state(engine: EnhancedControlPlaneEngine, state: dict[str, Any]) -> dict[str, Any]:
    """Restore a previously serialized paper state in place.

    Unknown or malformed sections are ignored rather than fabricated. Returns a
    small report so callers can surface what was restored.
    """
    base = engine.base_engine
    account = state.get("account") or {}
    decimal_fields = (
        "current_equity_usd",
        "high_water_mark_usd",
        "start_of_day_equity_usd",
        "gross_notional_usd",
        "correlated_exposure_usd",
        "sector_exposure_usd",
        "best_day_profit_usd",
        "total_cumulative_profit_usd",
    )
    restored_fields: list[str] = []
    for name in decimal_fields:
        raw = account.get(name)
        if raw is None:
            continue
        try:
            setattr(base, name, Decimal(str(raw)))
            restored_fields.append(name)
        except (ArithmeticError, ValueError):
            continue
    if isinstance(account.get("completed_trading_days"), int):
        base.completed_trading_days = account["completed_trading_days"]
        restored_fields.append("completed_trading_days")
    if state.get("active_track") in ("competition", "open_market"):
        base.active_track = state["active_track"]
    if isinstance(state.get("kill_switch_engaged"), bool):
        base.kill_switch_engaged = state["kill_switch_engaged"]
    for name in ("active_champion_model", "active_challenger_model"):
        if isinstance(state.get(name), str) and state[name]:
            setattr(base, name, state[name])
    if isinstance(state.get("challenger_approved"), bool):
        base.challenger_approved = state["challenger_approved"]
    if isinstance(state.get("training_runs_completed"), int):
        base.training_runs_completed = state["training_runs_completed"]

    positions: list[ActionablePositionRecord] = []
    orders: list[ActionableOrderDecision] = []
    try:
        for row in state.get("open_positions") or []:
            position = ActionablePositionRecord.model_validate(row)
            if position.status == "open":
                positions.append(position)
    except (ValueError, TypeError):
        positions = []
    open_ids = {position.position_id for position in positions}
    try:
        for row in state.get("order_history") or []:
            order = ActionableOrderDecision.model_validate(row)
            if order.position_id in open_ids:
                orders.append(order)
    except (ValueError, TypeError):
        orders = []
    base.open_positions = positions
    base.order_history = orders
    base.audit_log = [str(line) for line in (state.get("audit_tail") or [])][-20:]
    sequence = state.get("sequence") or {}
    base._order_seq = _max_sequence(
        [order.order_id for order in orders],
        "ord-",
        default=max(1, int(sequence.get("order") or 1)),
    )
    base._pos_seq = _max_sequence(
        [position.position_id for position in positions],
        "pos-",
        default=max(1, int(sequence.get("position") or 1)),
    )
    return {
        "restored": True,
        "fields": restored_fields,
        "open_positions": len(positions),
        "orders": len(orders),
        "updated_at": state.get("updated_at"),
        "execution_permission": "none",
    }


def _forecast_id(symbol: str, model_id: str, decision_time: datetime, target_time: datetime, track: str) -> str:
    raw = f"{symbol}|{track}|{model_id}|{decision_time.isoformat()}|{target_time.isoformat()}"
    return "fc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _instrument_id(track: str, symbol: str) -> str:
    if track == "competition":
        return f"comp:{symbol.lower().replace('-usd', '')}-perp:v1"
    return f"open:{symbol.lower()}-eq:v1"


def execute_forecast_paper_trade(
    forecast: dict[str, Any],
    engine: EnhancedControlPlaneEngine,
    config: SliceConfig,
) -> dict[str, Any]:
    """Convert a research action into a gated paper order.

    The engine is the sole authorization boundary. An abstain never reaches it.
    """
    action = forecast.get("action")
    trade_id = "tr_" + hashlib.sha256(str(forecast["forecast_id"]).encode("utf-8")).hexdigest()[:24]
    request_id = forecast["forecast_id"]
    base_payload: dict[str, Any] = {
        "trade_id": trade_id,
        "forecast_id": request_id,
        "symbol": forecast["symbol"],
        "track": forecast["track"],
        "side": "none",
        "requested_notional_usd": 0.0,
        "authorized_notional_usd": None,
        "control_plane_decision": "abstained",
        "position_id": None,
        "order_id": None,
        "gate_scale": None,
        "gate_reason": None,
        "violations_json": "[]",
        "stop_distance_bps": None,
        "entry_price": None,
        "status": "not_proposed",
        "created_at": forecast["decision_time"],
        "execution_permission": "none",
    }
    if action not in ("long", "short"):
        base_payload["gate_reason"] = forecast.get("action_reason") or "abstain"
        return base_payload
    price = float(forecast["reference_price"])
    stop_bps = _stop_distance(forecast)
    risk_budget = float(engine.base_engine.current_equity_usd) * config.risk_fraction
    requested = min(
        float(config.max_notional_usd),
        risk_budget / max(stop_bps / 10_000.0, 1e-6),
    )
    stop = price * (1.0 - stop_bps / 10_000.0) if action == "long" else price * (1.0 + stop_bps / 10_000.0)
    take = price * (1.0 + 2.0 * stop_bps / 10_000.0) if action == "long" else price * (1.0 - 2.0 * stop_bps / 10_000.0)
    signal = StrategySignal(
        strategy_id="VERTICAL_SLICE_SOFTMAX",
        symbol=forecast["symbol"],
        direction="BUY" if action == "long" else "SELL",
        target_conviction=float(forecast["confidence"]),
        conviction=float(forecast["confidence"]),
        suggested_stop_loss=stop,
        suggested_take_profit=take,
        reference_price=price,
        target_entry_price=price,
        rationale=str(forecast.get("action_reason") or ""),
        telemetry={"model_id": forecast["model_id"], "edge": forecast["edge"]},
    )
    instrument_id = _instrument_id(forecast["track"], forecast["symbol"])
    expected = float(forecast.get("expected_return") or 0.0)
    prediction = price * (1.0 + expected)
    lower = price * (1.0 + float(forecast.get("interval_low") or expected))
    upper = price * (1.0 + float(forecast.get("interval_high") or expected))
    gate = engine.uncertainty_gating.evaluate_trade(
        model_id=forecast["model_id"],
        instrument_id=instrument_id,
        prediction=prediction,
        lower=lower,
        upper=upper,
        confidence=float(forecast["confidence"]),
        current_price=price,
        proposed_position=requested,
    )
    now = _utc(forecast["decision_time"])
    if not gate.trade_allowed:
        request = ActionableOrderRequest(
            track=forecast["track"],
            instrument_id=instrument_id,
            side="buy" if action == "long" else "sell",
            notional_usd=Decimal(str(round(requested, 2))),
            stop_kind="atr",
            stop_distance_bps=Decimal(str(round(stop_bps, 2))),
            holding_horizon_seconds=config.bucket_seconds * config.horizon_steps,
            vpin_toxicity=0.0,
            data_age_ms=config.data_age_ms,
        )
        decision = engine.base_engine.submit_order(
            request,
            now=now,
            intake_violations=(
                "uncertainty_gating: " + (gate.rejection_reason or "trade not allowed"),
            ),
        )
        base_payload.update(
            {
                "side": action,
                "requested_notional_usd": round(requested, 2),
                "control_plane_decision": "rejected_by_uncertainty_gate",
                "position_id": None,
                "order_id": decision.order_id,
                "violations_json": json.dumps(list(decision.violations)),
                "stop_distance_bps": round(stop_bps, 2),
                "entry_price": price,
                "gate_scale": round(gate.position_scale, 6),
                "gate_reason": gate.rejection_reason,
            }
        )
        return base_payload
    authorized = Decimal(str(round(requested, 2))) * Decimal(str(gate.position_scale))
    authorized = authorized.quantize(Decimal("0.01"))
    intake = engine.base_engine.ingest_whale_policy_signal(
        signal,
        track=forecast["track"],
        desired_notional_usd=authorized,
        data_age_ms=config.data_age_ms,
        require_connector=False,
        now=now,
    )
    decision = intake.decision
    violations = list(decision.violations)
    if decision.position_id is None:
        base_payload.update(
            {
                "side": action,
                "requested_notional_usd": round(requested, 2),
                "authorized_notional_usd": float(authorized),
                "control_plane_decision": decision.control_plane_decision,
                "order_id": decision.order_id,
                "violations_json": json.dumps(violations),
                "stop_distance_bps": round(stop_bps, 2),
                "entry_price": price,
                "gate_scale": round(gate.position_scale, 6),
                "gate_reason": "control_plane_rejected",
            }
        )
        return base_payload
    base_payload.update(
        {
            "side": action,
            "requested_notional_usd": round(requested, 2),
            "authorized_notional_usd": float(decision.notional_usd),
            "control_plane_decision": "authorized_paper",
            "position_id": decision.position_id,
            "order_id": decision.order_id,
            "violations_json": json.dumps(violations),
            "stop_distance_bps": round(stop_bps, 2),
            "entry_price": price,
            "gate_scale": round(gate.position_scale, 6),
            "gate_reason": gate.rejection_reason,
            "status": "open",
        }
    )
    return base_payload


def _stop_distance(forecast: dict[str, Any]) -> float:
    features = forecast.get("features") or {}
    atr = float(features.get("atr_5_pct") or 0.0)
    return float(min(300.0, max(30.0, atr * 10_000.0 * 1.5)))


def resolve_forecast(
    ledger: ForecastLedger,
    forecast: dict[str, Any],
    *,
    exit_price: float,
    resolved_at: datetime,
    engine: EnhancedControlPlaneEngine | None = None,
) -> dict[str, Any]:
    reference = float(forecast["reference_price"])
    realized = exit_price / reference - 1.0
    cost_fraction = float(forecast["cost_bps"]) / 10_000.0
    realized_class = CLASS_NAMES[_classify(realized, cost_fraction)]
    raw_probabilities = forecast["probabilities"]
    if isinstance(raw_probabilities, dict):
        probabilities = np.asarray(
            [float(raw_probabilities[name]) for name in CLASS_NAMES], dtype=np.float64
        )
    else:
        probabilities = np.asarray(raw_probabilities, dtype=np.float64)
    target = np.zeros(3)
    target[CLASS_INDEX[realized_class]] = 1.0
    brier = float(np.sum((probabilities - target) ** 2))
    ledger.resolve_forecast(
        forecast["forecast_id"],
        realized_return=realized,
        realized_class=realized_class,
        brier_score=brier,
        resolved_at=resolved_at,
    )
    trade = ledger.trade_for_forecast(forecast["forecast_id"])
    trade_result = None
    if trade and trade["status"] == "open" and trade["control_plane_decision"] == "authorized_paper":
        sign = 1.0 if trade["side"] == "long" else -1.0
        net = sign * realized - cost_fraction
        notional = float(trade["authorized_notional_usd"] or trade["requested_notional_usd"])
        pnl = net * notional
        if engine is not None and trade.get("position_id"):
            closed = engine.base_engine.close_position(
                str(trade["position_id"]),
                exit_price=exit_price,
                fee_usd=Decimal(str(round(notional * cost_fraction, 2))),
                reason="vertical_slice_resolution",
                now=resolved_at,
            )
            if closed.get("status") == "closed":
                pnl = float(closed["paper_pnl_usd"])
        ledger.resolve_trade(
            trade["trade_id"],
            realized_return_net=net,
            realized_pnl_usd=pnl,
            resolved_at=resolved_at,
        )
        trade_result = {
            "trade_id": trade["trade_id"],
            "side": trade["side"],
            "net_return": round(net, 8),
            "pnl_usd": round(pnl, 2),
        }
    return {
        "forecast_id": forecast["forecast_id"],
        "symbol": forecast["symbol"],
        "action": forecast["action"],
        "realized_return": round(realized, 8),
        "realized_class": realized_class,
        "brier_score": round(brier, 8),
        "trade": trade_result,
    }
