"""Registry of the same-named ML helpers that are actually different functions.

Five helper names existed twice with different signatures and behaviour (see
``docs/architecture/ML_HELPERS.md``). Each variant now has a descriptive name; the old
names stay as aliases so nothing changes at runtime. This module only stores import
strings, so listing it never imports the heavy modules. ``resolve`` imports one on demand.

Variants inside files owned by other workers (``atlas.ml``, ``atlas.feeds``,
``atlas.api.udf``) are registered here under their descriptive name but not renamed in
place (``renamed_in_place=False``).
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from typing import Any

EXECUTION_PERMISSION = "none"


@dataclass(frozen=True)
class HelperVariant:
    id: str  # descriptive name
    family: str  # the shared legacy name
    target: str  # "module:attribute" of the implementation
    legacy: str  # "module:attribute" of the old name (alias, or the original when not renamed)
    signature: str
    purpose: str
    key_difference: str
    used_by_modules: tuple[str, ...]
    used_by_components: tuple[str, ...]  # atlas.ai.node REGISTRY names
    pipelines: tuple[str, ...] = ()
    genome_options: tuple[str, ...] = ()
    renamed_in_place: bool = True
    notes: str = ""


HELPERS: tuple[HelperVariant, ...] = (
    HelperVariant(
        "bars_frame_ohlcv_range_index", "bars_frame", "atlas.ai.ml.features:bars_frame", "atlas.ai.ml.features:bars_frame",
        "(bars: Sequence[Bar]) -> DataFrame[start, end, open, high, low, close, volume]",
        "Turn feed bars into the OHLCV frame that the ML feature pipeline builds every feature from.",
        "Keeps all OHLCV columns plus integer start/end times on a plain RangeIndex.",
        ("atlas.ai.ml.features.bar_features", "atlas.ai.ml.dataset", "atlas.ai.ml.selector"),
        ("ml_pipeline", "evolution", "selector_regime"),
        pipelines=("ml dataset build (scripts/ml_refresh.py)", "evolution runs (scripts/evolve_models.py)", "selector evidence"),
        genome_options=("features: full, no_setup, no_signed, no_time, bar_only",
                        "bar_type: time, heikin_ashi, renko_atr, range_atr, volume, dollar, kagi_atr, pnf_atr"),
        renamed_in_place=False, notes="Registered under atlas.ai.ml.features (atlas.ml aliased)."),
    HelperVariant(
        "bars_frame_close_volume_time_index", "bars_frame",
        "atlas.ai.models.quant.features:bars_frame_close_volume_time_index", "atlas.ai.models.quant.features:bars_frame",
        "(bars) -> DataFrame[close, volume] indexed by DatetimeIndex(bar.ts)",
        "Turn bars into the close/volume panel that the quant retrain dataset is built from.",
        "Keeps only close and volume, indexed by timestamp; no OHLC columns.",
        ("atlas.ai.models.quant.retrain",), ("quant_models",),
        pipelines=("atlas-ml retrain CLI (atlas.ai.models.quant.retrain:main)",)),
    HelperVariant(
        "purged_walk_forward_splits_by_time", "purged_walk_forward",
        "atlas.ai.models.quant.cv:purged_walk_forward_splits_by_time", "atlas.ai.models.quant.cv:purged_walk_forward",
        "(times, n_splits=5, horizon=5, embargo=0, min_train_frac=0.3) -> Iterator[(train_idx, test_idx)]",
        "Cross-validation splitter: expanding-window folds over unique timestamps, purging training rows whose label "
        "(horizon unique timestamps ahead) plus embargo reaches into the test window.",
        "Only yields index arrays (fits nothing). Folds are cut on unique time ranks and apply both horizon purge and embargo.",
        ("atlas.ai.models.quant.evaluate", "atlas.ai.models.quant.sleeves"), ("quant_models",),
        pipelines=("quant model evaluation", "sleeve backtests")),
    HelperVariant(
        "purged_walk_forward_model_selection_by_rows", "purged_walk_forward",
        "atlas.research.vertical_slice:purged_walk_forward_model_selection_by_rows",
        "atlas.research.vertical_slice:purged_walk_forward",
        "(rows: Sequence[FeatureRow], symbol, *, cost_bps, config: SliceConfig, feature_names=FEATURE_NAMES, "
        "collect_rows=False) -> dict",
        "Full model-selection run for the research vertical slice: fits the frequency baseline, softmax and optional "
        "XGBoost candidates per fold and returns pooled out-of-sample metrics.",
        "Fits and scores models (returns a report dict, not splits). Folds are fixed-size blocks of resolved rows "
        "after config.min_train_rows, not time ranks.",
        ("atlas.research.vertical_slice (baseline, feature ablation, service run)",), ("vertical_slice",),
        pipelines=("vertical-slice research run (/api/research/vertical-slice)", "feature ablation"),
        notes="Callers use the old global name so tests that monkeypatch it keep working."),
    HelperVariant(
        "PointInTimeFeatureStoreSQLite", "FeatureStore",
        "atlas.marketdata.pit.featurestore:PointInTimeFeatureStoreSQLite", "atlas.marketdata.pit.featurestore:FeatureStore",
        "(path=':memory:'); put / put_frame / get(as_of) / frame(times)",
        "Point-in-time store: each value has event_ts and available_at, and reads as of t only see values knowable "
        "by t, so training frames cannot leak future or revised data.",
        "SQLite; keyed by entity/feature-set/time; revisions are new rows; tz-aware timestamps required.",
        ("tests only (founder M-M foundation, alt-data)",), (),
        notes="No production ML model uses it yet."),
    HelperVariant(
        "VersionedFeatureStoreDuckDBParquet", "FeatureStore",
        "atlas.features.feature_store:VersionedFeatureStoreDuckDBParquet", "atlas.features.feature_store:FeatureStore",
        "(store_id, db_path, parquet_dir)",
        "Versioned feature artifact store: Parquet files with sha256, lineage and per-model feature importance in DuckDB.",
        "Stores whole feature versions and metadata, not point-in-time values; no as-of reads.",
        ("atlas.main", "atlas.api.advanced_ml", "atlas.features.pa_integration"), ("serving",),
        pipelines=("advanced ML API (/api/advanced-ml)", "price-action feature integration")),
    HelperVariant(
        "compute_hawkes_intensity_causal_report", "compute_hawkes_intensity",
        "atlas.marketdata.microstructure:compute_hawkes_intensity_causal_report",
        "atlas.marketdata.microstructure:compute_hawkes_intensity",
        "(event_times_sec, *, eval_time_sec, mu_0=0.5, alpha=0.8, beta=1.2, clustering_threshold=1.5) -> HawkesIntensityReport",
        "Causal Hawkes intensity lambda(t) = mu_0 + sum alpha*exp(-beta*(t - t_i)) over events strictly before t.",
        "Takes absolute event times and returns a typed report (branching ratio, stationarity, event count); "
        "validates parameters.",
        ("atlas.features.microstructure", "atlas.features.toxicity", "atlas.regime.hawkes_detector"),
        ("selector_regime",),
        pipelines=("regime Hawkes detector", "toxicity features", "WF-07 via compute_hawkes_child_order_intensity")),
    HelperVariant(
        "compute_hawkes_intensity_from_deltas_summary", "compute_hawkes_intensity",
        "atlas.whale_saas_az:compute_hawkes_intensity_from_deltas_summary", "atlas.whale_saas_az:compute_hawkes_intensity",
        "(event_deltas_sec, mu_0=0.5, alpha=0.85, beta=1.2) -> dict",
        "WF-07 hidden-liquidity summary: converts 'seconds ago' deltas to times at a fixed t=100 and delegates to the "
        "causal report (via atlas.features.microstructure).",
        "Takes deltas, not absolute times; returns a rounded dict with a fixed 1.85 clustering threshold and "
        "execution_permission none.",
        ("atlas.ai.models.whale_factor_ml", "atlas.api.app (whale SaaS endpoint)"), ("challengers",),
        pipelines=("whale factor ML (WF-07)",)),
    HelperVariant(
        "symbol_info_feed_instrument", "symbol_info", "atlas.feeds.udf:symbol_info", "atlas.feeds.udf:symbol_info",
        "(symbol, feed: AtlasFeed | None = None) -> dict",
        "TradingView UDF symbol metadata for an instrument in the live ATLAS feed.",
        "Reads the feed instrument (venue, tick size -> pricescale, session map, UTC); an unknown symbol raises "
        "(no error dict); resolutions 15/60/1D only.",
        ("tests/feeds/test_feeds.py",), (), renamed_in_place=False,
        notes="atlas.feeds is integrations-owned; registered, not renamed."),
    HelperVariant(
        "symbol_info_desk_catalog", "symbol_info", "atlas.api.udf:symbol_info", "atlas.api.udf:symbol_info",
        "(symbol) -> dict",
        "TradingView UDF symbol metadata for a desk symbol from the global asset catalog (served at /api/udf/symbols).",
        "Reads GLOBAL_ASSET_CATALOG; returns an error dict for unknown symbols; New York session; pulsed data.",
        ("atlas.api.udf",), (), renamed_in_place=False,
        notes="Chart area; registered, not renamed."),
)


def _load(ref: str) -> Any:
    mod, _, attr = ref.partition(":")
    return getattr(importlib.import_module(mod), attr)


def variant(helper_id: str) -> HelperVariant:
    for h in HELPERS:
        if h.id == helper_id:
            return h
    raise KeyError(helper_id)


def resolve(helper_id: str) -> Any:
    """Import and return the implementation behind a descriptive helper name."""
    return _load(variant(helper_id).target)


def helpers_for(component_name: str) -> list[str]:
    return [h.id for h in HELPERS if component_name in h.used_by_components]


def families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for h in HELPERS:
        out.setdefault(h.family, []).append(h.id)
    return out


def as_dict(h: HelperVariant) -> dict[str, Any]:
    return asdict(h) | {"execution_permission": EXECUTION_PERMISSION}
