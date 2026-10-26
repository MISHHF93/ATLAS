"""Persistent, point-in-time research slice from bars to paper authorization.

The slice is deliberately narrow and auditable:

* bars must carry both an event time and an ``available_at`` close time;
* features and labels are built only from completed bars;
* walk-forward evaluation purges the training rows whose labels overlap the
  test decisions and adds an embargo;
* forecasts carry calibrated-ish multiclass probabilities, an empirical
  return interval, and an explicit abstain action;
* a proposed action can only become a paper position through
  :class:`ActionableControlPlaneEngine`.

Nothing in this module sends a live order. Forecast accuracy and paper P&L are
kept separate because a correct direction is not a profitable trade.
"""

from __future__ import annotations

import base64
import bisect
import functools
import hashlib
import json
import math
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

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
from atlas.marketdata.data_rights import DataUseDenied, require_data_use
from atlas.strategies.base import StrategySignal


from atlas.research.vertical_slice_features import (
    CLASS_INDEX,
    CLASS_NAMES,
    CROSS_ASSET_FEATURE_NAMES,
    DEFAULT_DB_PATH,
    FEATURE_FAMILIES,
    FEATURE_NAMES,
    MIN_BARS,
    MODEL_FAMILY,
    PAPER_ENGINE_ID,
    PAPER_STATE_KEY,
    PATH_ID,
    RESEARCH_FEATURE_NAMES,
    ROUND_TRIP_BPS,
    SCHEDULER_STATE_KEY,
    SESSION_FEATURE_NAMES,
    XGBOOST_FAMILY,
    Candle,
    FeatureRow,
    SliceConfig,
    _admit_rows,
    _blocked_data_use,
    _classify,
    _correlation,
    _default_reference_symbol,
    _feature_values,
    _finite,
    _public_rows,
    _relabel,
    _returns,
    _std,
    _utc,
    build_feature_rows,
    build_research_feature_rows,
    normalize_candles,
)
from atlas.research.vertical_slice_ledger import (
    ForecastLedger,
    _decimal_text,
    _decode_forecast,
    _forecast_id,
    _instrument_id,
    _max_sequence,
    _stop_distance,
    build_paper_engine,
    execute_forecast_paper_trade,
    resolve_forecast,
    restore_paper_state,
    serialize_paper_state,
)
from atlas.research.vertical_slice_models import (
    ConstantProbabilityModel,
    SoftmaxModel,
    XGBoostModel,
    _action,
    _bucket,
    _dataset_fingerprint,
    _drop_feature_columns,
    _frequency_baseline,
    _one_hot,
    _regime_labels,
    _regime_metrics,
    _xgboost_module,
    ablate_feature_families,
    evaluate_predictions,
    fit_softmax,
    fit_xgboost,
    optional_gbdt_status,
    purged_walk_forward,
    purged_walk_forward_model_selection_by_rows,
)
from atlas.research.vertical_slice_scheduler import (
    VerticalSliceScheduler,
    _env_int,
    _scheduler_horizons,
    _scheduler_settings,
    get_vertical_slice_scheduler,
    get_vertical_slice_service,
)

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _service_locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class VerticalSliceService:
    ledger: ForecastLedger = field(default_factory=ForecastLedger)
    config: SliceConfig = field(default_factory=SliceConfig)
    engine: EnhancedControlPlaneEngine | None = None
    engine_id: str = PAPER_ENGINE_ID
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _state_restored: bool = field(default=False, init=False, repr=False, compare=False)
    _restore_report: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)
    _engines: dict[int, EnhancedControlPlaneEngine] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.engine is None:
            self.engine = build_paper_engine(self.engine_id, config=self.config)
        self._engines = {1: self.engine}
        self._restore_paper_state()

    def _state_key(self, horizon_steps: int) -> str:
        horizon = max(1, int(horizon_steps))
        return PAPER_STATE_KEY if horizon == 1 else f"{PAPER_STATE_KEY}:h{horizon}"

    def _engine_id_for(self, horizon_steps: int) -> str:
        horizon = max(1, int(horizon_steps))
        return self.engine_id if horizon == 1 else f"{self.engine_id}:h{horizon}"

    def _engine_for(self, horizon_steps: int) -> EnhancedControlPlaneEngine:
        horizon = max(1, int(horizon_steps))
        if horizon in self._engines:
            return self._engines[horizon]
        engine = build_paper_engine(self._engine_id_for(horizon), config=self.config)
        saved = self.ledger.load_state(self._state_key(horizon))
        if saved:
            try:
                restore_paper_state(engine, saved)
            except Exception:  # noqa: BLE001 - corrupt state must not fabricate a book
                pass
        self._engines[horizon] = engine
        return engine

    def _restore_paper_state(self) -> None:
        if self.engine is None:
            self._state_restored = True
            self._restore_report = {"restored": False, "reason": "no_saved_state", "execution_permission": "none"}
            return
        engines: dict[int, EnhancedControlPlaneEngine] = {1: self.engine}
        reports: dict[str, Any] = {}
        for key in self.ledger.state_keys(PAPER_STATE_KEY):
            suffix = key.removeprefix(PAPER_STATE_KEY)
            if not suffix:
                horizon = 1
            elif suffix.startswith(":h"):
                try:
                    horizon = int(suffix[2:])
                except ValueError:
                    continue
            else:
                continue
            if horizon < 1:
                continue
            if horizon == 1:
                engine = self.engine
            else:
                engine = build_paper_engine(self._engine_id_for(horizon), config=self.config)
                engines[horizon] = engine
            state = self.ledger.load_state(key)
            if not state:
                continue
            try:
                reports[str(horizon)] = restore_paper_state(engine, state)
            except Exception as exc:  # noqa: BLE001 - corrupt state must not stop the API
                reports[str(horizon)] = {
                    "restored": False,
                    "reason": "corrupt_saved_state",
                    "error": type(exc).__name__,
                }
        self._engines = engines
        if not reports:
            self._restore_report = {
                "restored": False,
                "reason": "no_saved_state",
                "horizons": [],
                "execution_permission": "none",
            }
        else:
            self._restore_report = {
                "restored": any(report.get("restored") for report in reports.values()),
                "horizons": reports,
                "execution_permission": "none",
            }
        self._state_restored = True

    def _save_paper_state(self, now: datetime) -> None:
        for horizon, engine in self._engines.items():
            self.ledger.save_state(
                self._state_key(horizon),
                serialize_paper_state(
                    engine,
                    updated_at=now,
                    engine_id=self._engine_id_for(horizon),
                ),
                now,
            )

    def configure(
        self,
        *,
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
    ) -> SliceConfig:
        with self._lock:
            updates: dict[str, Any] = {}
            if bucket_seconds is not None:
                updates["bucket_seconds"] = int(bucket_seconds)
            if horizon_steps is not None:
                updates["horizon_steps"] = int(horizon_steps)
            if updates:
                self.config = SliceConfig(**{**self.config.__dict__, **updates})
            return self.config

    @_service_locked
    def run(
        self,
        *,
        symbols: Sequence[str] = ("BTC-USD",),
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        fetch: bool = True,
        now: datetime | None = None,
        paper: bool = True,
    ) -> dict[str, Any]:
        config = SliceConfig(
            **{
                **self.config.__dict__,
                **(
                    {"bucket_seconds": bucket_seconds}
                    if bucket_seconds is not None
                    else {}
                ),
                **(
                    {"horizon_steps": horizon_steps}
                    if horizon_steps is not None
                    else {}
                ),
            }
        )
        self.config = config
        if self.engine is None:
            self.engine = build_paper_engine(config=config)
        created_at = now or datetime.now(timezone.utc)
        run_id = "vs_" + hashlib.sha256(
            json.dumps(
                {
                    "symbols": [symbol.upper() for symbol in symbols],
                    "config": config.as_dict(),
                    "created_at": created_at.date().isoformat(),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24]
        reports: list[dict[str, Any]] = []
        for symbol in symbols:
            reports.append(
                self._run_symbol(
                    symbol.upper(),
                    config,
                    candles=candles_by_symbol.get(symbol.upper()) if candles_by_symbol else None,
                    fetch=fetch,
                    created_at=created_at,
                    run_id=run_id,
                    paper=paper,
                )
            )
        combined = _combine_reports(reports)
        report = {
            "run_id": run_id,
            "path_id": PATH_ID,
            "created_at": created_at.isoformat(),
            "config": config.as_dict(),
            "symbols": reports,
            "metrics": combined,
            "optional_challengers": optional_gbdt_status(),
            "limitations": [
                "This is research, not investment advice or a live trading record.",
                "Brier/log loss score probabilities; paper P&L includes modeled round-trip cost but no borrow, funding, slippage, or market impact.",
                "Empirical intervals are conditional return quantiles, not guaranteed coverage.",
                "Paper positions, equity, and open authorizations are restored from the local ledger after restart. They remain a local simulation, not a venue record.",
                "Public venue candles can be delayed, revised, or unavailable; unavailable data is reported as such.",
                "Model selection includes frequency and uniform baselines. When a learned model loses out of sample, the baseline is selected and the forecast may abstain.",
            ],
            "execution_permission": "none",
        }
        self.ledger.record_run(run_id, created_at, config, report)
        if paper:
            self._save_paper_state(created_at)
        return report

    def ablate_features(
        self,
        *,
        symbol: str = "BTC-USD",
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
        families: Sequence[str] | None = None,
        candles: list[dict[str, Any]] | None = None,
        fetch: bool = True,
        include_regimes: bool = False,
        include_session: bool = False,
        include_cross_asset: bool = False,
        reference_symbol: str | None = None,
        reference_candles: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run a read-only feature-family ablation on one symbol."""
        config = SliceConfig(
            **{
                **self.config.__dict__,
                **(
                    {"bucket_seconds": bucket_seconds}
                    if bucket_seconds is not None
                    else {}
                ),
                **(
                    {"horizon_steps": horizon_steps}
                    if horizon_steps is not None
                    else {}
                ),
            }
        )
        wanted = symbol.upper()
        source_rows = candles
        if source_rows is None and fetch:
            try:
                from atlas.marketdata.public_quotes import fetch_public_candles

                payload = fetch_public_candles(
                    wanted, config.bucket_seconds, limit=400, intended_use="training"
                )
                source_rows = _public_rows(payload)
            except DataUseDenied as exc:
                return _blocked_data_use(wanted, exc)
            except Exception as exc:  # noqa: BLE001 - report, never fill
                return {
                    "status": "unavailable",
                    "symbol": wanted,
                    "reason": type(exc).__name__,
                    "execution_permission": "none",
                }
        if not source_rows:
            return {
                "status": "unavailable",
                "symbol": wanted,
                "reason": "public_candles_unavailable",
                "execution_permission": "none",
            }
        moment = now or datetime.now(timezone.utc)
        try:
            normalized, quality = _admit_rows(source_rows, symbol=wanted, bucket_seconds=config.bucket_seconds, as_of=moment)
        except DataUseDenied as exc:
            return _blocked_data_use(wanted, exc)
        reference_wanted = (
            (reference_symbol or _default_reference_symbol(wanted)).upper()
        )
        if reference_wanted == wanted:
            reference_wanted = _default_reference_symbol(reference_wanted)
        reference_available = False
        reference_reason: str | None = None
        normalized_reference: list[Candle] = []
        reference_quality: dict[str, Any] | None = None
        if include_cross_asset:
            source_reference = reference_candles
            if source_reference is None and fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(
                        reference_wanted, config.bucket_seconds, limit=400, intended_use="training"
                    )
                    source_reference = _public_rows(payload)
                except DataUseDenied as exc:
                    return _blocked_data_use(reference_wanted, exc)
                except Exception as exc:  # noqa: BLE001 - report, never fill
                    reference_reason = type(exc).__name__
            elif source_reference is None:
                reference_reason = "reference_candles_not_supplied"
            if source_reference:
                try:
                    normalized_reference, reference_quality = _admit_rows(source_reference, symbol=reference_wanted, bucket_seconds=config.bucket_seconds, as_of=moment)
                except DataUseDenied as exc:
                    return _blocked_data_use(reference_wanted, exc)
            elif reference_reason is None:
                reference_reason = "reference_candles_unavailable"
        rows, feature_names, reference_available = build_research_feature_rows(
            normalized,
            config,
            reference_candles=normalized_reference,
            include_session=include_session,
            include_cross_asset=include_cross_asset,
        )
        rows = _relabel(
            rows,
            ROUND_TRIP_BPS["competition" if wanted.endswith("-USD") else "open_market"],
        )
        if not rows:
            return {
                "status": "insufficient_history",
                "symbol": wanted,
                "bars": len(normalized),
                "required_bars": MIN_BARS,
                "quality": quality,
                "execution_permission": "none",
            }
        selected_families = families or [
            family
            for family, members in FEATURE_FAMILIES.items()
            if any(name in feature_names for name in members)
        ]
        report = ablate_feature_families(
            rows,
            wanted,
            cost_bps=ROUND_TRIP_BPS[
                "competition" if wanted.endswith("-USD") else "open_market"
            ],
            config=config,
            feature_names=feature_names,
            families=selected_families,
            include_regimes=include_regimes,
        )
        return {
            **report,
            "as_of": (now or datetime.now(timezone.utc)).isoformat(),
            "bars": len(normalized),
            "quality": quality,
            "research_features": {
                "session_requested": include_session,
                "cross_asset_requested": include_cross_asset,
                "reference_symbol": reference_wanted if include_cross_asset else None,
                "reference_available": reference_available,
                "reference_reason": reference_reason,
                "reference_quality": reference_quality,
            },
            "read_only": True,
            "execution_permission": "none",
        }

    def ablate_multi(
        self,
        *,
        symbols: Sequence[str],
        bucket_seconds: int = 86_400,
        horizon_steps: Sequence[int] = (1,),
        families: Sequence[str] | None = None,
        include_regimes: bool = True,
        include_session: bool = False,
        include_cross_asset: bool = False,
        reference_symbol: str | None = None,
        reference_candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Measure feature families across symbols and horizons without writing.

        The matrix is bounded so one request cannot trigger an unbounded number
        of walk-forward retrainings. Each cell is still a separate purged
        walk-forward ablation against the same baseline as the single-symbol
        endpoint.
        """
        wanted = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        ) or ("BTC-USD",)
        horizons = tuple(
            sorted({int(step) for step in horizon_steps if 1 <= int(step) <= 24})
        ) or (1,)
        wanted = wanted[:6]
        horizons = horizons[:3]
        moment = now or datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        reference_cache: dict[str, list[dict[str, Any]] | None] = {}
        for symbol in wanted:
            candles: list[dict[str, Any]] | None = (candles_by_symbol or {}).get(symbol)
            fetch_error: str | None = None
            if candles is not None:
                candles = list(candles)
            elif fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(symbol, bucket_seconds, limit=400, intended_use="training")
                    candles = _public_rows(payload)
                except DataUseDenied as exc:
                    rows.extend({**_blocked_data_use(symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                    continue
                except Exception as exc:  # noqa: BLE001 - report, never fill
                    fetch_error = type(exc).__name__
            else:
                fetch_error = "candles_not_supplied"
            if not candles:
                for horizon in horizons:
                    rows.append(
                        {
                            "symbol": symbol,
                            "horizon_steps": horizon,
                            "status": "unavailable",
                            "reason": fetch_error or "public_candles_unavailable",
                            "execution_permission": "none",
                        }
                    )
                continue
            ref_symbol = (
                (reference_symbol or _default_reference_symbol(symbol)).upper()
            )
            if ref_symbol == symbol:
                ref_symbol = _default_reference_symbol(ref_symbol)
            ref_candles: list[dict[str, Any]] | None = None
            if include_cross_asset:
                if ref_symbol not in reference_cache:
                    source = (reference_candles_by_symbol or {}).get(ref_symbol)
                    if source is None and fetch and ref_symbol != symbol:
                        try:
                            from atlas.marketdata.public_quotes import fetch_public_candles

                            payload = fetch_public_candles(
                                ref_symbol, bucket_seconds, limit=400, intended_use="training"
                            )
                            source = _public_rows(payload)
                        except DataUseDenied as exc:
                            rows.extend({**_blocked_data_use(ref_symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                            continue
                        except Exception:  # noqa: BLE001 - report, never fill
                            source = None
                    reference_cache[ref_symbol] = source
                ref_candles = reference_cache.get(ref_symbol)
            for horizon in horizons:
                try:
                    cell = self.ablate_features(
                        symbol=symbol,
                        bucket_seconds=bucket_seconds,
                        horizon_steps=horizon,
                        families=families,
                        candles=candles,
                        fetch=False,
                        include_regimes=include_regimes,
                        include_session=include_session,
                        include_cross_asset=include_cross_asset,
                        reference_symbol=ref_symbol,
                        reference_candles=ref_candles,
                        now=moment,
                    )
                except Exception as exc:  # noqa: BLE001 - one cell must not fail the matrix
                    rows.append(
                        {
                            "symbol": symbol,
                            "horizon_steps": horizon,
                            "status": "error",
                            "error": type(exc).__name__,
                            "execution_permission": "none",
                        }
                    )
                    continue
                ablations = list(cell.get("ablations") or [])
                supported = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "removal_worsened"
                ]
                negative = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "removal_improved"
                ]
                inconclusive = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "inconclusive"
                ]
                cell_status = cell.get("status")
                rows.append(
                    {
                        "symbol": symbol,
                        "horizon_steps": horizon,
                        "status": "scored" if cell_status == "measured" else cell_status,
                        "reason": cell.get("reason"),
                        "data_use": cell.get("data_use"),
                        "bars": cell.get("bars"),
                        "baseline": cell.get("baseline"),
                        "ablations": ablations,
                        "supported_families": supported,
                        "negative_families": negative,
                        "inconclusive_families": inconclusive,
                        "research_features": cell.get("research_features"),
                        "execution_permission": "none",
                    }
                )
        scored = [row for row in rows if row.get("status") == "scored"]
        return {
            "status": "blocked" if rows and all(row.get("status") == "blocked" for row in rows) else "evaluated",
            "bucket_seconds": bucket_seconds,
            "symbols": list(wanted),
            "horizons": list(horizons),
            "families": list(families or FEATURE_FAMILIES.keys()),
            "include_regimes": include_regimes,
            "include_session": include_session,
            "include_cross_asset": include_cross_asset,
            "as_of": moment.isoformat(),
            "rows": rows,
            "scored_cells": len(scored),
            "cells": len(rows),
            "notice": (
                "Cross-symbol and cross-horizon ablation matrix. Each cell retrains "
                "on purged walk-forward folds and is read-only; no forecasts, paper "
                "trades, or order permission were created. Session and cross-asset "
                "features are research candidates built only from completed "
                "timestamps and admitted reference candles; they are not in the "
                "production feature set. Regime rows use trailing volatility/trend "
                "thresholds and are descriptive, not a validated regime classifier. "
                "Small deltas are inconclusive and do not justify changing the "
                "production feature set."
            ),
            "read_only": True,
            "execution_permission": "none",
        }

    def evaluate_multi(
        self,
        *,
        symbols: Sequence[str],
        bucket_seconds: int = 86_400,
        horizon_steps: Sequence[int] = (1,),
        now: datetime | None = None,
        fetch: bool = True,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate the same slice across symbols and horizons without paper trades.

        The evaluation uses an in-memory ledger so it cannot pollute the audited
        production ledger or create paper positions. Metrics are still
        walk-forward, purged, and baseline-compared per symbol/horizon.
        """
        wanted = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        ) or ("BTC-USD",)
        horizons = tuple(
            sorted({int(step) for step in horizon_steps if 1 <= int(step) <= 24})
        ) or (1,)
        moment = now or datetime.now(timezone.utc)
        temporary = VerticalSliceService(
            ledger=ForecastLedger(":memory:"),
            config=self.config,
        )
        rows: list[dict[str, Any]] = []
        try:
            for symbol in wanted:
                candles: list[dict[str, Any]] | None = (candles_by_symbol or {}).get(symbol)
                fetch_error: str | None = None
                if candles is not None:
                    candles = list(candles)
                elif fetch:
                    try:
                        from atlas.marketdata.public_quotes import fetch_public_candles

                        payload = fetch_public_candles(symbol, bucket_seconds, limit=400, intended_use="training")
                        candles = _public_rows(payload)
                    except DataUseDenied as exc:
                        rows.extend({**_blocked_data_use(symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        fetch_error = type(exc).__name__
                else:
                    fetch_error = "candles_not_supplied"
                if not candles:
                    for horizon in horizons:
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": "unavailable",
                                "reason": fetch_error or "public_candles_unavailable",
                                "execution_permission": "none",
                            }
                        )
                    continue
                for horizon in horizons:
                    try:
                        report = temporary.run(
                            symbols=[symbol],
                            bucket_seconds=bucket_seconds,
                            horizon_steps=horizon,
                            candles_by_symbol={symbol: candles},
                            fetch=False,
                            now=moment,
                            paper=False,
                        )
                        symbol_report = (report.get("symbols") or [{}])[0]
                        walk = symbol_report.get("walk_forward") or {}
                        primary = walk.get("primary_metrics") or {}
                        baseline = walk.get("frequency_baseline") or {}
                        challenger = walk.get("xgboost_challenger") or {}
                        challenger_metrics = challenger.get("model") or {}
                        selected = walk.get("primary_model_family") or (
                            symbol_report.get("model") or {}
                        ).get("model_family")
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": symbol_report.get("status"),
                                "reason": symbol_report.get("reason"),
                                "data_use": symbol_report.get("data_use"),
                                "bars": symbol_report.get("bars"),
                                "selected_model_family": selected,
                                "walk_forward_status": walk.get("status"),
                                "brier_score": primary.get("brier_score"),
                                "log_loss": primary.get("log_loss"),
                                "accuracy": primary.get("accuracy"),
                                "coverage": primary.get("coverage"),
                                "rows": primary.get("rows"),
                                "taken": primary.get("taken"),
                                "direction_accuracy": primary.get("direction_accuracy"),
                                "frequency_brier_score": baseline.get("brier_score"),
                                "challenger_status": challenger.get("status"),
                                "challenger_brier_score": challenger_metrics.get("brier_score"),
                                "baseline_selected": selected in {"frequency_baseline", "uniform_baseline"},
                                "execution_permission": "none",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 - one cell must not fail the matrix
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": "error",
                                "error": type(exc).__name__,
                                "execution_permission": "none",
                            }
                        )
        finally:
            temporary.ledger.close()
        scored = [row for row in rows if row.get("walk_forward_status") == "scored"]
        return {
            "status": "blocked" if rows and all(row.get("status") == "blocked" for row in rows) else "evaluated",
            "bucket_seconds": bucket_seconds,
            "symbols": list(wanted),
            "horizons": list(horizons),
            "as_of": moment.isoformat(),
            "rows": rows,
            "scored_cells": len(scored),
            "cells": len(rows),
            "notice": (
                "Evaluation-only matrix. Each cell uses purged walk-forward evidence against "
                "frequency and uniform baselines. No paper trades were created and no order permission exists."
            ),
            "execution_permission": "none",
        }

    def _run_symbol(
        self,
        symbol: str,
        config: SliceConfig,
        *,
        candles: list[dict[str, Any]] | None,
        fetch: bool,
        created_at: datetime,
        run_id: str,
        paper: bool,
    ) -> dict[str, Any]:
        track = "competition" if symbol.endswith("-USD") else "open_market"
        cost_bps = ROUND_TRIP_BPS[track]
        source_rows = candles
        fetch_error = None
        if source_rows is None:
            if not fetch:
                return _unavailable(symbol, track, "candles_not_supplied")
            try:
                from atlas.marketdata.public_quotes import fetch_public_candles

                payload = fetch_public_candles(symbol, config.bucket_seconds, limit=400, intended_use="training")
                if payload:
                    source_rows = _public_rows(payload)
            except DataUseDenied as exc:
                return {**_blocked_data_use(symbol, exc), "track": track}
            except Exception as exc:  # network/library failure is reported, never filled
                fetch_error = type(exc).__name__
        if not source_rows:
            return _unavailable(symbol, track, fetch_error or "public_candles_unavailable")
        try:
            normalized, quality = _admit_rows(source_rows, symbol=symbol, bucket_seconds=config.bucket_seconds, as_of=created_at)
        except DataUseDenied as exc:
            return {**_blocked_data_use(symbol, exc), "track": track}
        if len(normalized) < MIN_BARS:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "bars": len(normalized),
                "required_bars": MIN_BARS,
                "execution_permission": "none",
            }
        rows = _relabel(build_feature_rows(normalized, config), cost_bps)
        resolved_rows = [row for row in rows if row.resolved]
        if not resolved_rows:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "bars": len(normalized),
                "execution_permission": "none",
            }
        dataset_hash = _dataset_fingerprint(resolved_rows, symbol, config)
        walk = purged_walk_forward(resolved_rows, symbol, cost_bps=cost_bps, config=config)
        softmax = fit_softmax(
            [row.features for row in resolved_rows],
            [int(row.label) for row in resolved_rows],
            l2=config.l2,
            epochs=config.epochs,
            learning_rate=config.learning_rate,
            seed=config.seed,
            dataset_hash=dataset_hash,
        )
        model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel = softmax
        primary_family = str(walk.get("primary_model_family") or MODEL_FAMILY)
        fallback_reason = None
        if primary_family in {"frequency_baseline", "uniform_baseline"}:
            probabilities_for_baseline = (
                _frequency_baseline([int(row.label) for row in resolved_rows])
                if primary_family == "frequency_baseline"
                else np.full(3, 1.0 / 3.0, dtype=np.float64)
            )
            model = ConstantProbabilityModel(
                model_id=f"{primary_family}:{dataset_hash[:12]}:baseline",
                model_family=primary_family,
                probabilities=tuple(float(value) for value in probabilities_for_baseline),  # type: ignore[arg-type]
                feature_names=FEATURE_NAMES,
                training_rows=len(resolved_rows),
                dataset_hash=dataset_hash,
            )
        elif primary_family == XGBOOST_FAMILY:
            xgb_model = fit_xgboost(
                [row.features for row in resolved_rows],
                [int(row.label) for row in resolved_rows],
                seed=config.seed,
                dataset_hash=dataset_hash,
            )
            if xgb_model is not None:
                model = xgb_model
            else:
                primary_family = MODEL_FAMILY
                fallback_reason = "xgboost_final_fit_failed"
        walk["selected_model_id"] = model.model_id
        walk["selected_model_family"] = primary_family
        walk["selection"] = {
            **dict(walk.get("selection") or {}),
            "primary_model_family": primary_family,
            "selected_model_id": model.model_id,
            "fallback_reason": fallback_reason,
        }
        self.ledger.save_model(model, symbol, created_at)
        latest = rows[-1] if rows else None
        if latest is None:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "execution_permission": "none",
            }
        probabilities = model.predict_proba(latest.features)
        action, reason, edge = _action(probabilities, config)
        expected = _expected_return(resolved_rows, int(probabilities.argmax()))
        interval_low, interval_high = _return_interval(resolved_rows, int(probabilities.argmax()))
        feature_map = {name: value for name, value in zip(FEATURE_NAMES, latest.features)}
        contributions = _contributions(model, latest.features, int(probabilities.argmax()), feature_map)
        forecast_id = _forecast_id(symbol, model.model_id, latest.decision_time, latest.target_time, track)
        forecast = {
            "forecast_id": forecast_id,
            "run_id": run_id,
            "symbol": symbol,
            "track": track,
            "model_id": model.model_id,
            "model_revision": dataset_hash[:16],
            "dataset_hash": dataset_hash,
            "decision_time": latest.decision_time.isoformat(),
            "target_time": latest.target_time.isoformat(),
            "bucket_seconds": config.bucket_seconds,
            "horizon_steps": config.horizon_steps,
            "reference_price": latest.reference_price,
            "features_json": json.dumps(feature_map, sort_keys=True),
            "probabilities_json": json.dumps(
                {name: round(float(prob), 8) for name, prob in zip(CLASS_NAMES, probabilities)},
                sort_keys=True,
            ),
            "predicted_class": CLASS_NAMES[int(probabilities.argmax())],
            "action": action,
            "action_reason": reason,
            "confidence": round(float(probabilities.max()), 8),
            "edge": round(float(edge), 8),
            "interval_low": interval_low,
            "interval_high": interval_high,
            "cost_bps": cost_bps,
            "status": "open",
            "execution_permission": "none",
        }
        inserted = self.ledger.insert_forecast(forecast)
        trade = None
        if inserted and paper:
            forecast_for_trade = {
                **forecast,
                "features": feature_map,
                "probabilities": [float(value) for value in probabilities],
                "expected_return": expected,
            }
            trade_payload = execute_forecast_paper_trade(
                forecast_for_trade,
                self._engine_for(config.horizon_steps),
                config,
            )
            self.ledger.insert_trade(trade_payload)
            trade = trade_payload
        return {
            "symbol": symbol,
            "track": track,
            "status": "forecast_recorded" if inserted else "duplicate_forecast_skipped",
            "quality": quality,
            "bars": len(normalized),
            "dataset_hash": dataset_hash,
            "model": {
                "model_id": model.model_id,
                "model_family": primary_family,
                "training_rows": model.training_rows,
                "training_loss": getattr(
                    model, "training_loss", getattr(model, "training_log_loss", None)
                ),
                "importance": model.importance()[:6],
            },
            "chart": _chart_payload(
                normalized,
                latest,
                probabilities,
                action,
                forecast_id,
                interval=(interval_low, interval_high),
                limit=160,
            ),
            "walk_forward": walk,
            "forecast": {
                **forecast,
                "features": feature_map,
                "probabilities": {
                    name: round(float(prob), 8) for name, prob in zip(CLASS_NAMES, probabilities)
                },
                "expected_return": expected,
                "feature_contributions": contributions,
            },
            "paper_trade": trade,
            "execution_permission": "none",
        }

    def _forecast_horizon(self, forecast: dict[str, Any]) -> int:
        raw = forecast.get("horizon_steps")
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        bucket = self.config.bucket_seconds
        try:
            bucket = max(1, int(forecast.get("bucket_seconds") or bucket))
            delta = _utc(forecast["target_time"]) - _utc(forecast["decision_time"])
            return max(1, int(round(delta.total_seconds() / bucket)))
        except (KeyError, TypeError, ValueError):
            return 1

    @_service_locked
    def resolve(
        self,
        *,
        symbols: Sequence[str] = ("BTC-USD",),
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        fetch: bool = True,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        now = as_of or datetime.now(timezone.utc)
        resolutions: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for symbol in symbols:
            symbol = symbol.upper()
            source_rows = candles_by_symbol.get(symbol) if candles_by_symbol else None
            if source_rows is None and fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(symbol, self.config.bucket_seconds, limit=400, intended_use="training")
                    if payload:
                        source_rows = _public_rows(payload)
                except DataUseDenied as exc:
                    blocked.append(_blocked_data_use(symbol, exc))
                    continue
                except Exception:
                    source_rows = None
            if not source_rows:
                continue
            try:
                normalized, _ = _admit_rows(source_rows, symbol=symbol, bucket_seconds=self.config.bucket_seconds, as_of=now)
            except DataUseDenied as exc:
                blocked.append(_blocked_data_use(symbol, exc))
                continue
            by_time = {candle.available_at: candle.close for candle in normalized}
            for forecast in self.ledger.open_forecasts(now):
                if forecast["symbol"] != symbol:
                    continue
                target_time = _utc(forecast["target_time"])
                exact = by_time.get(target_time)
                if exact is None:
                    later = [stamp for stamp in by_time if stamp >= target_time]
                    if not later:
                        continue
                    exact = by_time[min(later)]
                horizon = self._forecast_horizon(forecast)
                resolutions.append(
                    resolve_forecast(
                        self.ledger,
                        forecast,
                        exit_price=exact,
                        resolved_at=now,
                        engine=self._engine_for(horizon),
                    )
                )
        if resolutions:
            self._save_paper_state(now)
        return {
            "resolved": resolutions,
            "blocked": blocked,
            "count": len(resolutions),
            "as_of": now.isoformat(),
            "execution_permission": "none",
        }

    def status(self) -> dict[str, Any]:
        summary = self.ledger.summary()
        summary["research_inputs"] = {
            "feature_names": list(FEATURE_NAMES),
            "classes": list(CLASS_NAMES),
            "optional_challengers": optional_gbdt_status(),
            "execution_permission": "none",
        }
        summary["paper_state"] = {
            "engine_id": self.engine_id,
            **self._restore_report,
        }
        summary["paper_account"] = self._paper_account_snapshot()
        return summary

    def _paper_account_snapshot(self) -> dict[str, Any]:
        if not self._engines:
            return {
                "status": "unavailable",
                "execution_permission": "none",
            }
        books: dict[str, Any] = {}
        for horizon, engine in sorted(self._engines.items()):
            base = engine.base_engine
            books[str(horizon)] = {
                "current_equity_usd": float(base.current_equity_usd),
                "high_water_mark_usd": float(base.high_water_mark_usd),
                "open_positions": sum(
                    1 for position in base.open_positions if position.status == "open"
                ),
                "gross_notional_usd": float(base.gross_notional_usd),
                "correlated_exposure_usd": float(base.correlated_exposure_usd),
                "sector_exposure_usd": float(base.sector_exposure_usd),
                "kill_switch_engaged": base.kill_switch_engaged,
            }
        return {
            "status": "available",
            "current_equity_usd": round(
                sum(book["current_equity_usd"] for book in books.values()), 6
            ),
            "high_water_mark_usd": round(
                sum(book["high_water_mark_usd"] for book in books.values()), 6
            ),
            "starting_equity_usd": float(self.config.starting_equity_usd) * len(books),
            "open_positions": sum(book["open_positions"] for book in books.values()),
            "gross_notional_usd": round(
                sum(book["gross_notional_usd"] for book in books.values()), 6
            ),
            "correlated_exposure_usd": round(
                sum(book["correlated_exposure_usd"] for book in books.values()), 6
            ),
            "sector_exposure_usd": round(
                sum(book["sector_exposure_usd"] for book in books.values()), 6
            ),
            "kill_switch_engaged": any(
                book["kill_switch_engaged"] for book in books.values()
            ),
            "books": books,
            "restored_from_disk": bool(self._restore_report.get("restored")),
            "execution_permission": "none",
        }

    def forecasts(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.ledger.recent_forecasts(limit)

    def paper_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.ledger.recent_trades(limit)

    def chart(self, symbol: str, limit: int = 160) -> dict[str, Any]:
        wanted = symbol.upper()
        for report in self.ledger.latest_run_reports():
            for row in report.get("symbols") or []:
                if str(row.get("symbol", "")).upper() != wanted:
                    continue
                chart = row.get("chart")
                if not isinstance(chart, dict):
                    break
                bars = list(chart.get("bars") or [])[-max(20, min(int(limit), 500)) :]
                return {
                    **chart,
                    "bars": bars,
                    "run_id": report.get("run_id"),
                    "created_at": report.get("created_at"),
                    "execution_permission": "none",
                }
        return {
            "symbol": wanted,
            "status": "unavailable",
            "bars": [],
            "markers": [],
                "reason": "No recorded run contains admitted research bars for this symbol.",
            "execution_permission": "none",
        }

    def lucky_moments(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.ledger.recent_forecasts(500, status="resolved")
        lucky: list[dict[str, Any]] = []
        for row in rows:
            if row.get("action") not in ("long", "short") or row.get("realized_return") is None:
                continue
            sign = 1.0 if row["action"] == "long" else -1.0
            net_gross = sign * float(row["realized_return"])
            if net_gross <= 0:
                continue
            interval_low = float(row.get("interval_low") or 0.0)
            interval_high = float(row.get("interval_high") or 0.0)
            reason = None
            if float(row.get("confidence") or 0.0) < 0.55:
                reason = "low_confidence_win"
            elif net_gross > abs(interval_high) * 1.5 and interval_high > 0:
                reason = "outside_expected_interval"
            if reason:
                lucky.append(
                    {
                        "forecast_id": row["forecast_id"],
                        "symbol": row["symbol"],
                        "decision_time": row["decision_time"],
                        "action": row["action"],
                        "confidence": row["confidence"],
                        "edge": row["edge"],
                        "realized_return": row["realized_return"],
                        "signed_gross_return": round(net_gross, 8),
                        "interval": [interval_low, interval_high],
                        "reason": reason,
                        "caution": "A favorable outcome with weak confidence may be luck, not repeatable skill.",
                    }
                )
        return lucky[: max(1, min(int(limit), 100))]


def _expected_return(rows: Sequence[FeatureRow], class_index: int) -> float:
    values = [float(row.forward_return) for row in rows if row.label == class_index and row.forward_return is not None]
    if not values:
        values = [float(row.forward_return) for row in rows if row.forward_return is not None]
    return round(sum(values) / len(values), 8) if values else 0.0


def _return_interval(rows: Sequence[FeatureRow], class_index: int) -> tuple[float | None, float | None]:
    values = sorted(float(row.forward_return) for row in rows if row.label == class_index and row.forward_return is not None)
    if len(values) < 5:
        values = sorted(float(row.forward_return) for row in rows if row.forward_return is not None)
    if len(values) < 5:
        return None, None
    low = values[int(0.05 * (len(values) - 1))]
    high = values[int(0.95 * (len(values) - 1))]
    return round(low, 8), round(high, 8)


def _contributions(
    model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel,
    features: Sequence[float],
    class_index: int,
    feature_map: dict[str, float],
) -> list[dict[str, Any]]:
    if isinstance(model, XGBoostModel):
        return model.explain(features, class_index, feature_map)
    if isinstance(model, ConstantProbabilityModel):
        return []
    mean = np.asarray(model.mean)
    scale = np.asarray(model.scale)
    weights = np.asarray(model.weights)[:, class_index]
    normalized = (np.asarray(features) - mean) / scale
    contributions = normalized * weights
    order = np.argsort(-np.abs(contributions))
    return [
        {
            "feature": FEATURE_NAMES[int(index)],
            "value": round(float(feature_map[FEATURE_NAMES[int(index)]]), 8),
            "standardized": round(float(normalized[int(index)]), 6),
            "coefficient": round(float(weights[int(index)]), 6),
            "contribution": round(float(contributions[int(index)]), 8),
            "method": "linear_logit",
        }
        for index in order[:6]
    ]


def _chart_payload(
    candles: Sequence[Candle],
    latest: FeatureRow,
    probabilities: np.ndarray,
    action: str,
    forecast_id: str,
    *,
    interval: tuple[float | None, float | None],
    limit: int,
) -> dict[str, Any]:
    window = list(candles)[-max(20, min(int(limit), 500)) :]
    return {
        "symbol": latest and window[-1].symbol if window else None,
        "bucket_seconds": (
            (window[-1].timestamp - window[-2].timestamp).total_seconds()
            if len(window) > 1
            else None
        ),
        "bars": [
            {
                "time": candle.available_at.isoformat(),
                "open": round(candle.open, 8),
                "high": round(candle.high, 8),
                "low": round(candle.low, 8),
                "close": round(candle.close, 8),
                "volume": round(candle.volume, 8),
            }
            for candle in window
        ],
        "markers": [
            {
                "forecast_id": forecast_id,
                "time": latest.decision_time.isoformat(),
                "target_time": latest.target_time.isoformat(),
                "price": round(latest.reference_price, 8),
                "action": action,
                "predicted_class": CLASS_NAMES[int(probabilities.argmax())],
                "confidence": round(float(probabilities.max()), 8),
                "probabilities": {
                    name: round(float(prob), 8)
                    for name, prob in zip(CLASS_NAMES, probabilities)
                },
                "interval_low": interval[0],
                "interval_high": interval[1],
            }
        ],
        "notice": (
            "Bars are the research observations used by the model. Data-use admission is reported separately. The marker "
            "is the recorded decision time, not an exchange-native TradingView marker."
        ),
        "execution_permission": "none",
    }


def _unavailable(symbol: str, track: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "track": track,
        "status": "unavailable",
        "reason": reason,
        "notice": "No forecast was fabricated from missing or unauthorized data.",
        "execution_permission": "none",
    }


def _combine_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        report["walk_forward"]
        for report in reports
        if report.get("walk_forward", {}).get("status") == "scored"
    ]
    if not scored:
        return {
            "status": "insufficient_history",
            "symbols_scored": 0,
            "notice": "No symbol had enough purged walk-forward rows to score.",
        }
    selected = [
        (item.get("primary_model_family") or "softmax_logistic", item.get("primary_metrics") or item["model"])
        for item in scored
    ]
    rows = sum(int(metrics["rows"]) for _, metrics in selected)
    brier = sum(float(metrics["brier_score"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    log_loss = sum(float(metrics["log_loss"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    accuracy = sum(float(metrics["accuracy"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    taken = sum(int(metrics["taken"]) for _, metrics in selected)
    hits = sum(int(metrics["direction_hits"]) for _, metrics in selected)
    families: dict[str, int] = {}
    for family, _ in selected:
        families[family] = families.get(family, 0) + 1
    return {
        "status": "scored",
        "symbols_scored": len(selected),
        "selected_model_families": families,
        "rows": rows,
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "accuracy": round(accuracy, 6),
        "coverage": round(taken / rows, 6) if rows else 0.0,
        "taken": taken,
        "direction_accuracy": round(hits / taken, 6) if taken else None,
        "notice": (
            "Aggregated selected-model metrics across symbols with unequal row counts. "
            "Baselines can win; a learned model that loses out of sample is not selected. "
            "Inspect each symbol before drawing conclusions."
        ),
    }
