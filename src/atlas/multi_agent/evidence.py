"""Point-in-time evidence collection for the multi-agent graph.

Only evidence that existed at the run's ``as_of`` timestamp is exposed to the
analysts.  Missing data is recorded as missing; it is never estimated or
fabricated.  External text is treated as untrusted data and is scanned for
prompt-injection patterns before it can reach an optional LLM analyst.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Sequence

from .config import MultiAgentConfig
from .contracts import (
    EvidenceReference,
    EvidenceSnapshot,
    MacroEvent,
    NewsItem,
    PortfolioContext,
    RunRequest,
)

FundamentalsProvider = Callable[[str, str | None], dict[str, Any]]
StrategyProvider = Callable[[str, Sequence[Any], int, int], list[dict[str, Any]]]
MLProvider = Callable[[str, str, Any, datetime], list[dict[str, Any]]]

_FUTURES = {"GC", "SI", "HG", "CL", "NG", "ES", "NQ", "YM", "RTY", "ZN", "ZB", "6E", "6J", "6B"}
_ETFS = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "IEF", "HYG", "LQD", "XLE", "XLK", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE"}

_SENTIMENT_POSITIVE = (
    "beat", "beats", "record", "growth", "upgrade", "profit", "surge", "rally", "strong",
    "raised guidance", "buyback", "demand", "approval", "partnership", "outperform",
)
_SENTIMENT_NEGATIVE = (
    "miss", "misses", "downgrade", "loss", "lawsuit", "investigation", "fraud", "halt",
    "bankruptcy", "restatement", "going concern", "recall", "guidance cut", "weak",
    "layoff", "breach", "delisting", "warning",
)
_MACRO_TERMS = (
    "cpi", "inflation", "fed", "fomc", "rate", "payroll", "unemployment", "gdp", "pmi",
    "retail sales", "consumer", "jobless", "treasury", "central bank", "ecb", "boj", "boc",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _hash(value: Any) -> str:
    import json

    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _float(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _asset_class(instrument: str, feed: Any) -> str:
    inst = instrument.upper()
    try:
        record = feed.instruments.get(inst) if feed is not None and hasattr(feed, "instruments") else None
        if record is not None and getattr(record, "asset_class", None):
            return str(record.asset_class)
    except Exception:  # noqa: BLE001 - instrument master is optional
        pass
    if inst.endswith(("USDT", "USDC", "USD")) and len(inst) > 4:
        return "crypto"
    if inst in _FUTURES:
        return "future"
    if inst in _ETFS:
        return "etf"
    if inst.startswith(("XAU", "XAG")):
        return "future"
    return "equity"


def _bar_end(bar: Any, duration: int) -> int:
    start = int(getattr(bar, "start", getattr(bar, "event_time", 0)))
    return start + duration


def _freshness(last_end: int | None, as_of_epoch: int, bucket: int, origin: str) -> dict[str, Any]:
    if last_end is None:
        label = "unavailable"
        age = None
    else:
        age = max(0, as_of_epoch - last_end)
        if any(k in origin.lower() for k in ("fixture", "synthetic", "simulat")):
            label = "simulated"
        elif age <= min(2 * bucket, 3600):
            label = "live"
        elif age <= 86400:
            label = "delayed"
        else:
            label = "historical"
    return {"label": label, "last_bar_end": last_end, "age_s": age, "source": origin or "unknown", "computed_at": as_of_epoch}


def _load_bars(feed: Any, instrument: str, interval: str, as_of_epoch: int, duration: int, max_bars: int = 5000) -> list[Any]:
    from atlas.ai.intel.data import load_bars

    bars = load_bars(feed, instrument, interval, max_bars=max_bars)
    return [b for b in bars if int(b.start) + duration <= as_of_epoch]


def _source(instrument: str, kind: str, observed: datetime, available: datetime, retrieved: datetime,
            payload: Any, *, source_type: str, uri: str | None = None, untrusted: bool = False) -> EvidenceReference:
    return EvidenceReference(
        source_id=f"{kind}:{instrument}:{_hash(payload)[:16]}",
        source_type=source_type,
        observed_at=observed,
        available_at=available,
        retrieved_at=retrieved,
        source_hash=_hash(payload),
        uri=uri,
        untrusted=untrusted,
    )


def _default_fundamentals(ticker: str, as_of: str | None) -> dict[str, Any]:
    from atlas.ext.edgar import fundamentals

    return fundamentals(ticker, as_of)


def _default_strategy_candidates(instrument: str, bars: Sequence[Any], duration: int, as_of_epoch: int) -> list[dict[str, Any]]:
    from atlas.features.price_action.extended_strategies import ExtendedStrategyEngine

    engine = ExtendedStrategyEngine(instrument, duration)
    result = engine.run_batch(bars, now=as_of_epoch)
    return list(result.get("candidates") or [])


def _default_ml_predictions(instrument: str, interval: str, feed: Any, as_of: datetime) -> list[dict[str, Any]]:
    from atlas.ai.ml.live_intelligence import generate_live_prediction

    class PointInTimeFeed:
        """Delegate to the feed but never expose a bar known after ``as_of``."""

        def __init__(self, inner: Any, as_of_epoch: int) -> None:
            self._inner = inner
            self._as_of_epoch = as_of_epoch

        def bars(self, *args: Any, **kwargs: Any) -> list[Any]:
            out = self._inner.bars(*args, **kwargs)
            return [b for b in out if int(getattr(b, "event_time", getattr(b, "start", 0))) <= self._as_of_epoch]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    out = generate_live_prediction(instrument, interval, feed=PointInTimeFeed(feed, int(as_of.timestamp())),
                                   now=as_of, persist=False)
    return [out] if isinstance(out, dict) else []


@dataclass
class EvidenceDependencies:
    feed: Any = None
    fundamentals: FundamentalsProvider | None = None
    strategy_candidates: StrategyProvider | None = None
    ml_predictions: MLProvider | None = None


def _liquidity(bars: Sequence[Any]) -> dict[str, Any]:
    if len(bars) < 20:
        return {"status": "insufficient_data", "bars": len(bars)}
    recent = bars[-20:]
    prior = bars[-120:-20] or recent
    vols = [_float(b.volume) or 0.0 for b in recent]
    prior_vols = [_float(b.volume) or 0.0 for b in prior]
    avg_vol = sum(vols) / len(vols)
    base_vol = sum(prior_vols) / len(prior_vols)
    ranges = [((_float(b.high) or 0.0) - (_float(b.low) or 0.0)) / max(_float(b.close) or 1e-12, 1e-12) for b in recent]
    amihud: list[float] = []
    for i in range(1, len(recent)):
        prev = _float(recent[i - 1].close) or 0.0
        cur = _float(recent[i].close) or 0.0
        dollar = abs(cur) * max(_float(recent[i].volume) or 0.0, 1e-12)
        if prev > 0 and dollar > 0:
            amihud.append(abs(cur / prev - 1.0) / dollar * 1e6)
    return {
        "status": "ok",
        "bars": len(bars),
        "avg_volume_20": round(avg_vol, 6),
        "relative_volume_20_vs_100": round(avg_vol / base_vol, 6) if base_vol > 0 else None,
        "avg_range_bps_20": round(sum(ranges) / len(ranges) * 1e4, 4),
        "amihud_illiquidity_20": round(sum(amihud) / len(amihud), 8) if amihud else None,
        "order_book_depth": "unavailable",
        "note": "OHLCV-derived liquidity proxy; no exchange depth feed is configured.",
    }


def _news_sources(items: Sequence[NewsItem], as_of: datetime, retrieved: datetime, instrument: str) -> tuple[list[NewsItem], list[EvidenceReference], list[str]]:
    kept: list[NewsItem] = []
    refs: list[EvidenceReference] = []
    flags: list[str] = []
    try:
        from atlas.ai.assistant.guard import injection_flags
    except Exception:  # noqa: BLE001
        injection_flags = lambda _text: []  # type: ignore[assignment]

    for item in items:
        if item.published_at > as_of:
            continue
        found = injection_flags(item.text)
        flags.extend(found)
        kept.append(item)
        refs.append(
            _source(
                instrument,
                "news",
                item.published_at,
                item.published_at,
                retrieved,
                {"source": item.source, "text": item.text[:4000], "category": item.category},
                source_type="untrusted_news",
                uri=item.url,
                untrusted=True,
            )
        )
    return kept, refs, sorted(set(flags))


def _macro_sources(items: Sequence[MacroEvent], as_of: datetime, retrieved: datetime, instrument: str) -> tuple[list[MacroEvent], list[EvidenceReference]]:
    kept: list[MacroEvent] = []
    refs: list[EvidenceReference] = []
    for item in items:
        if item.scheduled_at > as_of:
            continue
        kept.append(item)
        refs.append(
            _source(
                instrument,
                "macro",
                item.scheduled_at,
                item.scheduled_at,
                retrieved,
                item.model_dump(mode="json"),
                source_type="macro_event",
                untrusted=False,
            )
        )
    return kept, refs


def build_evidence_snapshot(
    request: RunRequest,
    config: MultiAgentConfig,
    *,
    dependencies: EvidenceDependencies | None = None,
    portfolio: PortfolioContext | None = None,
) -> EvidenceSnapshot:
    """Collect a point-in-time snapshot for one instrument.

    ``dependencies`` exists so tests can supply deterministic fixtures without
    touching the network.  Production callers use the ATLAS feed, SEC EDGAR,
    the extended strategy engine and the registered ML serving path.
    """

    deps = dependencies or EvidenceDependencies()
    retrieved = _now()
    as_of = _aware(request.as_of)
    as_of_epoch = int(as_of.timestamp())
    instrument = request.instrument_id.strip().upper()
    timeframe = request.timeframe

    feed = deps.feed
    if feed is None:
        try:
            from atlas.feeds import get_feed

            feed = get_feed()
        except Exception as exc:  # noqa: BLE001
            feed = None

    from atlas.ai.intel.data import TF_SECONDS

    duration = TF_SECONDS.get(timeframe, 900)
    daily_duration = TF_SECONDS["1d"]

    missing: list[str] = []
    sources: list[EvidenceReference] = []
    bars: list[Any] = []
    daily: list[Any] = []
    if feed is None:
        missing.append("market_data_feed_unavailable")
    else:
        try:
            bars = _load_bars(feed, instrument, timeframe, as_of_epoch, duration)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"intraday_bars_unavailable:{type(exc).__name__}")
        try:
            daily = _load_bars(feed, instrument, "1d", as_of_epoch, daily_duration)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"daily_bars_unavailable:{type(exc).__name__}")

    if not bars:
        missing.append("no_confirmed_intraday_bars_at_as_of")
    if not daily:
        missing.append("no_confirmed_daily_bars_at_as_of")
        daily = list(bars)

    asset_class = _asset_class(instrument, feed)
    last_bar = bars[-1] if bars else (daily[-1] if daily else None)
    last_bar_at = datetime.fromtimestamp(_bar_end(last_bar, duration), tz=timezone.utc) if last_bar is not None else None
    last_close = _float(getattr(last_bar, "close", None)) if last_bar is not None else None
    origin = "atlas_feed" if bars else "unavailable"
    freshness = _freshness(_bar_end(last_bar, duration) if last_bar is not None else None, as_of_epoch, duration, origin)

    bars_hash = _hash([[_bar_end(b, duration), b.open, b.high, b.low, b.close, b.volume] for b in (daily or bars)]) if (daily or bars) else None
    if bars_hash:
        sources.append(
            _source(
                instrument,
                "bars",
                last_bar_at or as_of,
                last_bar_at or as_of,
                retrieved,
                {"instrument": instrument, "timeframe": timeframe, "bars": len(daily or bars), "hash": bars_hash},
                source_type="market_bars",
                uri="atlas-feed",
            )
        )

    technicals: dict[str, Any] = {"status": "no_data", "bars": 0}
    conviction: dict[str, Any] = {}
    trade_levels: dict[str, Any] = {}
    zones: list[Any] = []
    profile: dict[str, Any] | None = None
    if daily:
        try:
            from atlas.ext.dossier import conviction as conviction_fn
            from atlas.ext.dossier import technicals as technicals_fn
            from atlas.ext.dossier import trade_levels as trade_levels_fn
            from atlas.ext.pricevol import sr_zones, volume_profile

            technicals = technicals_fn(daily)
            try:
                zones = sr_zones(daily, instrument)
            except Exception:  # noqa: BLE001
                zones = []
            try:
                profile = volume_profile(daily, 40)
            except Exception:  # noqa: BLE001
                profile = None
        except Exception as exc:  # noqa: BLE001
            missing.append(f"technical_engine_unavailable:{type(exc).__name__}")

    fundamentals: dict[str, Any] = {}
    fundamentals_metrics: dict[str, Any] = {}
    fundamentals_status = "not_applicable"
    if asset_class in ("equity", "etf"):
        if not config.allow_network_fundamentals:
            fundamentals_status = "disabled"
            missing.append("fundamentals_network_disabled")
        else:
            fn = deps.fundamentals or _default_fundamentals
            try:
                fundamentals = fn(instrument, as_of.date().isoformat())
                fundamentals_status = str(fundamentals.get("status") or "unavailable")
                if fundamentals_status == "ok":
                    from atlas.ext.edgar import derived_metrics

                    fundamentals_metrics = derived_metrics(fundamentals, last_close)
                    period = (fundamentals.get("periods") or [{}])[0]
                    filed = period.get("filed")
                    available = datetime.fromisoformat(filed).replace(tzinfo=timezone.utc) if filed else as_of
                    sources.append(
                        _source(
                            instrument,
                            "fundamentals",
                            available,
                            available,
                            retrieved,
                            {"period_end": period.get("period_end"), "filed": filed, "metrics": fundamentals_metrics},
                            source_type="sec_edgar_fundamentals",
                            uri="https://www.sec.gov/edgar/search/",
                        )
                    )
                else:
                    missing.append(f"fundamentals_{fundamentals_status}")
            except Exception as exc:  # noqa: BLE001
                fundamentals_status = "error"
                missing.append(f"fundamentals_error:{type(exc).__name__}")
    elif asset_class in ("crypto", "future"):
        fundamentals_status = "not_applicable"
        missing.append("corporate_fundamentals_not_applicable")

    if technicals.get("status") == "ok":
        try:
            from atlas.ext.dossier import conviction as conviction_fn
            from atlas.ext.dossier import trade_levels as trade_levels_fn

            conviction = conviction_fn(technicals, fundamentals_metrics or None, profile)
            trade_levels = trade_levels_fn(
                str(conviction.get("label")),
                float(technicals["close"]),
                _float(technicals.get("atr14")),
                zones,
                profile,
            )
        except Exception as exc:  # noqa: BLE001
            missing.append(f"dossier_scoring_unavailable:{type(exc).__name__}")
    else:
        missing.append("technicals_unavailable")

    strategy_candidates: list[dict[str, Any]] = []
    if bars:
        strategy_fn = deps.strategy_candidates or _default_strategy_candidates
        try:
            strategy_candidates = list(strategy_fn(instrument, bars, duration, as_of_epoch))[:20]
            if strategy_candidates:
                sources.append(
                    _source(
                        instrument,
                        "strategy",
                        last_bar_at or as_of,
                        last_bar_at or as_of,
                        retrieved,
                        strategy_candidates,
                        source_type="deterministic_strategy_candidates",
                        uri="atlas.features.price_action.extended_strategies",
                    )
                )
            else:
                missing.append("no_active_strategy_candidates")
        except Exception as exc:  # noqa: BLE001
            missing.append(f"strategy_engine_error:{type(exc).__name__}")
    else:
        missing.append("strategy_candidates_require_bars")

    ml_predictions: list[dict[str, Any]] = []
    if feed is not None and bars:
        ml_fn = deps.ml_predictions or _default_ml_predictions
        try:
            ml_predictions = list(ml_fn(instrument, timeframe, feed, as_of))[:5]
            if ml_predictions:
                sources.append(
                    _source(
                        instrument,
                        "ml",
                        last_bar_at or as_of,
                        last_bar_at or as_of,
                        retrieved,
                        ml_predictions,
                        source_type="registered_ml_prediction",
                        uri="atlas.ai.models.serving",
                    )
                )
            else:
                missing.append("no_registered_ml_prediction")
        except Exception as exc:  # noqa: BLE001
            missing.append(f"ml_prediction_unavailable:{type(exc).__name__}")
    else:
        missing.append("ml_prediction_requires_feed")

    news_items = list(request.news)[: config.max_news_items]
    macro_events = list(request.macro_events)[: config.max_macro_events]
    kept_news, news_refs, injection = _news_sources(news_items, as_of, retrieved, instrument)
    kept_macro, macro_refs = _macro_sources(macro_events, as_of, retrieved, instrument)
    sources.extend(news_refs)
    sources.extend(macro_refs)
    if not kept_news:
        missing.append("no_point_in_time_news_supplied")
    if not kept_macro:
        missing.append("no_point_in_time_macro_events_supplied")

    liquidity = _liquidity(bars)
    if liquidity.get("status") != "ok":
        missing.append("liquidity_requires_20_intraday_bars")

    session: dict[str, Any] = {}
    try:
        from atlas.market.sessions import evaluate_instrument_market_status

        session = evaluate_instrument_market_status(instrument, now=as_of)
    except Exception as exc:  # noqa: BLE001
        session = {"status": "unavailable", "reason": type(exc).__name__}

    payload = {
        "instrument": instrument,
        "timeframe": timeframe,
        "as_of": as_of.isoformat(),
        "bars_hash": bars_hash,
        "technicals": technicals,
        "conviction": conviction,
        "fundamentals_status": fundamentals_status,
        "strategy_candidates": strategy_candidates,
        "ml_predictions": ml_predictions,
        "news": [n.model_dump(mode="json") for n in kept_news],
        "macro": [m.model_dump(mode="json") for m in kept_macro],
        "liquidity": liquidity,
        "session": session,
    }
    snapshot_id = _hash(payload)
    data_snapshot_id = _hash({"snapshot_id": snapshot_id, "prompt_version": config.prompt_version})

    return EvidenceSnapshot(
        snapshot_id=snapshot_id,
        data_snapshot_id=data_snapshot_id,
        instrument_id=instrument,
        timeframe=timeframe,
        asset_class=asset_class,
        as_of=as_of,
        retrieved_at=retrieved,
        bars_count=len(bars),
        bars_hash=bars_hash,
        last_bar_at=last_bar_at,
        last_close=last_close,
        freshness=freshness,
        point_in_time=True,
        technicals=_jsonable(technicals),
        conviction=_jsonable(conviction),
        trade_levels=_jsonable(trade_levels),
        fundamentals_status=fundamentals_status,
        fundamentals=_jsonable(fundamentals),
        fundamentals_metrics=_jsonable(fundamentals_metrics),
        strategy_candidates=_jsonable(strategy_candidates),
        ml_predictions=_jsonable(ml_predictions),
        news_items=kept_news,
        macro_events=kept_macro,
        liquidity=_jsonable(liquidity),
        session=_jsonable(session),
        sources=sources,
        prompt_injection_flags=injection,
        missing_data=sorted(set(missing)),
    )


def keyword_sentiment(text: str) -> tuple[float, list[str], list[str]]:
    """Deterministic lexicon score for supplied headlines. Not a calibrated model."""
    lowered = (text or "").lower()
    pos = sorted({w for w in _SENTIMENT_POSITIVE if w in lowered})
    neg = sorted({w for w in _SENTIMENT_NEGATIVE if w in lowered})
    score = float(len(pos) - len(neg))
    return score, pos, neg


def is_macro_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in _MACRO_TERMS)
