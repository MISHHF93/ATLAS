# ML helpers with shared names

Five helper names were defined twice in ATLAS, and each pair did different things. Each variant now has a descriptive name.
The old names are kept as aliases with a deprecation comment, so runtime behaviour is unchanged.
The machine-readable source is `src/atlas/ai/helpers_registry.py`. It is served at `GET /api/ai/helpers` (filters: `?family=`, `?component=`).
Each AI node component in `/api/ai/components` lists the variants it depends on under `helpers`.

Variants in files owned by other workstreams (`atlas.ml`, `atlas.feeds`, `atlas.api.udf`) are registered under a descriptive id but are not renamed in place.
All entries are `execution_permission: none`.

## `bars_frame`

### `bars_frame_ohlcv_range_index`

- Implementation: `atlas.ml.features:bars_frame` (registered, not renamed)
- Old name: `atlas.ml.features:bars_frame`
- Signature: `(bars: Sequence[Bar]) -> DataFrame[start, end, open, high, low, close, volume]`
- Purpose: Turn feed bars into the OHLCV frame that the ML feature pipeline builds every feature from.
- Key difference: Keeps all OHLCV columns plus integer start/end times on a plain RangeIndex.
- Used by modules: `atlas.ml.features.bar_features`, `atlas.ml.dataset`, `atlas.ml.selector`
- AI node components: `ml_pipeline`, `evolution`, `selector_regime`
- Pipelines: ml dataset build (scripts/ml_refresh.py); evolution runs (scripts/evolve_models.py); selector evidence
- Evolution genome options: features: full, no_setup, no_signed, no_time, bar_only; bar_type: time, heikin_ashi, renko_atr, range_atr, volume, dollar, kagi_atr, pnf_atr
- Notes: atlas.ml is owned by the evo workers; registered, not renamed.

### `bars_frame_close_volume_time_index`

- Implementation: `atlas.ai.models.quant.features:bars_frame_close_volume_time_index`
- Old name: `atlas.ai.models.quant.features:bars_frame`
- Signature: `(bars) -> DataFrame[close, volume] indexed by DatetimeIndex(bar.ts)`
- Purpose: Turn bars into the close/volume panel that the quant retrain dataset is built from.
- Key difference: Keeps only close and volume, indexed by timestamp; no OHLC columns.
- Used by modules: `atlas.ai.models.quant.retrain`
- AI node components: `quant_models`
- Pipelines: atlas-ml retrain CLI (atlas.ai.models.quant.retrain:main)

## `purged_walk_forward`

### `purged_walk_forward_splits_by_time`

- Implementation: `atlas.ai.models.quant.cv:purged_walk_forward_splits_by_time`
- Old name: `atlas.ai.models.quant.cv:purged_walk_forward`
- Signature: `(times, n_splits=5, horizon=5, embargo=0, min_train_frac=0.3) -> Iterator[(train_idx, test_idx)]`
- Purpose: Cross-validation splitter: expanding-window folds over unique timestamps, purging training rows whose label (horizon unique timestamps ahead) plus embargo reaches into the test window.
- Key difference: Only yields index arrays (fits nothing). Folds are cut on unique time ranks and apply both horizon purge and embargo.
- Used by modules: `atlas.ai.models.quant.evaluate`, `atlas.ai.models.quant.sleeves`
- AI node components: `quant_models`
- Pipelines: quant model evaluation; sleeve backtests

### `purged_walk_forward_model_selection_by_rows`

- Implementation: `atlas.research.vertical_slice:purged_walk_forward_model_selection_by_rows`
- Old name: `atlas.research.vertical_slice:purged_walk_forward`
- Signature: `(rows: Sequence[FeatureRow], symbol, *, cost_bps, config: SliceConfig, feature_names=FEATURE_NAMES, collect_rows=False) -> dict`
- Purpose: Full model-selection run for the research vertical slice: fits the frequency baseline, softmax and optional XGBoost candidates per fold and returns pooled out-of-sample metrics.
- Key difference: Fits and scores models (returns a report dict, not splits). Folds are fixed-size blocks of resolved rows after config.min_train_rows, not time ranks.
- Used by modules: `atlas.research.vertical_slice (baseline, feature ablation, service run)`
- AI node components: `vertical_slice`
- Pipelines: vertical-slice research run (/api/research/vertical-slice); feature ablation
- Notes: Callers use the old global name so tests that monkeypatch it keep working.

## `FeatureStore`

### `PointInTimeFeatureStoreSQLite`

- Implementation: `atlas.marketdata.pit.featurestore:PointInTimeFeatureStoreSQLite`
- Old name: `atlas.marketdata.pit.featurestore:FeatureStore`
- Signature: `(path=':memory:'); put / put_frame / get(as_of) / frame(times)`
- Purpose: Point-in-time store: each value has event_ts and available_at, and reads as of t only see values knowable by t, so training frames cannot leak future or revised data.
- Key difference: SQLite; keyed by entity/feature-set/time; revisions are new rows; tz-aware timestamps required.
- Used by modules: `tests only (founder M-M foundation, alt-data)`
- AI node components: none
- Notes: No production ML model uses it yet.

### `VersionedFeatureStoreDuckDBParquet`

- Implementation: `atlas.features.feature_store:VersionedFeatureStoreDuckDBParquet`
- Old name: `atlas.features.feature_store:FeatureStore`
- Signature: `(store_id, db_path, parquet_dir)`
- Purpose: Versioned feature artifact store: Parquet files with sha256, lineage and per-model feature importance in DuckDB.
- Key difference: Stores whole feature versions and metadata, not point-in-time values; no as-of reads.
- Used by modules: `atlas.main`, `atlas.api.advanced_ml`, `atlas.features.pa_integration`
- AI node components: `serving`
- Pipelines: advanced ML API (/api/advanced-ml); price-action feature integration

## `compute_hawkes_intensity`

### `compute_hawkes_intensity_causal_report`

- Implementation: `atlas.marketdata.microstructure:compute_hawkes_intensity_causal_report`
- Old name: `atlas.marketdata.microstructure:compute_hawkes_intensity`
- Signature: `(event_times_sec, *, eval_time_sec, mu_0=0.5, alpha=0.8, beta=1.2, clustering_threshold=1.5) -> HawkesIntensityReport`
- Purpose: Causal Hawkes intensity lambda(t) = mu_0 + sum alpha*exp(-beta*(t - t_i)) over events strictly before t.
- Key difference: Takes absolute event times and returns a typed report (branching ratio, stationarity, event count); validates parameters.
- Used by modules: `atlas.features.microstructure`, `atlas.features.toxicity`, `atlas.regime.hawkes_detector`
- AI node components: `selector_regime`
- Pipelines: regime Hawkes detector; toxicity features; WF-07 via compute_hawkes_child_order_intensity

### `compute_hawkes_intensity_from_deltas_summary`

- Implementation: `atlas.whale_saas_az:compute_hawkes_intensity_from_deltas_summary`
- Old name: `atlas.whale_saas_az:compute_hawkes_intensity`
- Signature: `(event_deltas_sec, mu_0=0.5, alpha=0.85, beta=1.2) -> dict`
- Purpose: WF-07 hidden-liquidity summary: converts 'seconds ago' deltas to times at a fixed t=100 and delegates to the causal report (via atlas.features.microstructure).
- Key difference: Takes deltas, not absolute times; returns a rounded dict with a fixed 1.85 clustering threshold and execution_permission none.
- Used by modules: `atlas.ai.models.whale_factor_ml`, `atlas.api.app (whale SaaS endpoint)`
- AI node components: `challengers`
- Pipelines: whale factor ML (WF-07)

## `symbol_info`

### `symbol_info_feed_instrument`

- Implementation: `atlas.feeds.udf:symbol_info` (registered, not renamed)
- Old name: `atlas.feeds.udf:symbol_info`
- Signature: `(symbol, feed: AtlasFeed | None = None) -> dict`
- Purpose: TradingView UDF symbol metadata for an instrument in the live ATLAS feed.
- Key difference: Reads the feed instrument (venue, tick size -> pricescale, session map, UTC); an unknown symbol raises (no error dict); resolutions 15/60/1D only.
- Used by modules: `tests/feeds/test_feeds.py`
- AI node components: none
- Notes: atlas.feeds is integrations-owned; registered, not renamed.

### `symbol_info_desk_catalog`

- Implementation: `atlas.api.udf:symbol_info` (registered, not renamed)
- Old name: `atlas.api.udf:symbol_info`
- Signature: `(symbol) -> dict`
- Purpose: TradingView UDF symbol metadata for a desk symbol from the global asset catalog (served at /api/udf/symbols).
- Key difference: Reads GLOBAL_ASSET_CATALOG; returns an error dict for unknown symbols; New York session; pulsed data.
- Used by modules: `atlas.api.udf`
- AI node components: none
- Notes: Chart area; registered, not renamed.

## Notes

- Evolution cross-validation uses `atlas.ml.cv.walk_forward_splits`, which is neither `purged_walk_forward` variant. Evolution depends only on `bars_frame_ohlcv_range_index`, through every features/bar_type genome option.
- `purged_walk_forward_splits_by_time` applies both `horizon` purge and `embargo` unique time steps before each test fold (`purged_kfold` also applies `embargo` after each test fold).
- `atlas.research.vertical_slice` keeps calling the old global name `purged_walk_forward` so that tests which monkeypatch it still work.
