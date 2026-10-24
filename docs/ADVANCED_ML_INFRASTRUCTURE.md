# Advanced ML Infrastructure Documentation

This document describes the advanced ML infrastructure components added to ATLAS, including Transformer forecasting, drift detection, uncertainty quantification, and feature store capabilities.

## Overview

The advanced ML infrastructure provides:

- **Transformer-based forecasting** with multi-head attention and uncertainty quantification
- **Drift detection** using KS test and PSI for feature and performance monitoring
- **Uncertainty-aware risk gating** for position sizing and trade authorization
- **Centralized feature store** with DuckDB and Parquet compression
- **Calibration systems** for probability and interval calibration

All components maintain strict `execution_permission: "none"` and integrate with the existing control plane.

## Implementation truth (2026-10-22)

- The compact Transformer is NumPy-only. Multi-head attention, positional
  encoding, and the encoder's feed-forward projections are seeded and **fixed**;
  only the linear forecast head is trained by Adam. The code and reports say
  this explicitly. It is not end-to-end PyTorch training.
- `TransformerChallengerProvider` builds sequences from verified frozen
  observations, purges overlapping labels, and compares against a naive
  last-value baseline. It does not use `np.random` placeholders or invent
  regime labels.
- The primary research slice is
  `atlas.research.vertical_slice` (documented below). It compares multiclass
  softmax, XGBoost, class-frequency, and uniform candidates on the same purged
  walk-forward, persists forecasts/outcomes/paper trades in SQLite, and exposes
  `execution_permission: "none"` at every boundary. Baselines can win.
- `xgboost` is an optional runtime challenger. When absent it is reported as
  `unavailable`; no challenger metric is fabricated. `lightgbm` remains
  optional and is not used by the audited slice.

## Transformer Forecasting

### Basic Usage

```python
from atlas.models.transformer_forecaster import (
    TransformerConfig,
    train_transformer_forecaster,
)
import numpy as np

config = TransformerConfig(
    d_model=64,
    n_heads=4,
    n_layers=2,
    d_ff=256,
    dropout=0.1,
    sequence_length=60,
    forecast_horizon=5,
    mc_dropout_samples=100,
    confidence_level=0.90,
)

# Supply causal, point-in-time feature sequences and future targets.
features = np.asarray(point_in_time_features)  # (samples, 60, n_features)
targets = np.asarray(future_targets)           # (samples, 5)
assert np.all(np.isfinite(features)) and np.all(np.isfinite(targets))

model = train_transformer_forecaster(
    dataset_id="authorized_pit_dataset",
    features=features,
    targets=targets,
    config=config,
    seed=42,
)

test_features = np.asarray(latest_causal_sequence)[None, :, :]
mean_pred, (lower, upper) = model.forecaster.predict(
    test_features,
    mc_samples=100,
    training=True,  # MC dropout for an empirical interval
)
```

Do not use random arrays as a demonstration of model quality. Random inputs
can only test shapes and finiteness; they cannot support a research claim.

### Integration with Evaluation

```python
from atlas.models.transformer_challenger import TransformerChallengerProvider
from atlas.marketdata.frozen import FrozenDatasetBundle

provider = TransformerChallengerProvider()

# Train on frozen dataset
model = provider.train_transformer(
    dataset=frozen_dataset,
    config=config,
    seed=42,
)

# Run purged walk-forward evaluation
reports = provider.run_purged_walk_forward_study(
    dataset=frozen_dataset,
    n_splits=5,
    config=config,
    seed=42,
)

# Register model
model_record = provider.register_model(
    model=model,
    experiment_id="exp_001",
    artifact_uri="s3://models/transformer_v1.pkl",
    license_ref="CC-BY-4.0",
    store=experiment_store,
)
```

## Drift Detection

### Feature Drift Monitoring

```python
from atlas.models.drift_detection import (
    create_drift_monitor,
    DriftThresholds,
)
import numpy as np
from datetime import datetime, timezone

# Configure thresholds
thresholds = DriftThresholds(
    ks_critical=0.1,
    psi_critical=0.25,
    mae_degradation=0.2,
    accuracy_degradation=0.1,
)

# Create monitor with baseline
baseline_features = {
    "returns": np.random.randn(1000),
    "volume": np.random.randn(1000),
}
baseline_timestamps = [datetime.now(timezone.utc)] * 1000

monitor = create_drift_monitor(
    monitor_id="btc_drift_monitor",
    baseline_features=baseline_features,
    baseline_timestamps=baseline_timestamps,
    thresholds=thresholds,
)

# Check for drift
current_features = {
    "returns": np.random.randn(500),
    "volume": np.random.randn(500),
}

drift_reports = monitor.check_all_features_drift(
    current_features=current_features,
    method="both",  # KS and PSI
)

for feature_name, reports in drift_reports.items():
    for report in reports:
        if report.is_drift_detected:
            print(f"Drift detected in {feature_name}: {report.drift_type}={report.statistic:.3f}")
```

### Performance Drift Monitoring

```python
from atlas.models.drift_detection import create_performance_monitor

# Create performance monitor
perf_monitor = create_performance_monitor(
    monitor_id="model_perf_monitor",
    baseline_metrics={"mae": 0.05, "directional_accuracy": 0.60},
    thresholds=thresholds,
)

# Check performance drift
report = perf_monitor.check_performance_drift("mae", 0.07)

if report.is_drift_detected:
    print(f"MAE degraded by {report.degradation_pct:.1%}")
```

### Automated Retraining Triggers

```python
from atlas.models.drift_detection import DriftDetectionManager

# Create drift manager
manager = DriftDetectionManager(
    manager_id="drift_manager",
    drift_monitor=monitor,
    performance_monitor=perf_monitor,
)

# Evaluate drift and determine if retraining needed
trigger = manager.evaluate_drift(
    current_features=current_features,
    current_metrics={"mae": 0.07},
    model_id="transformer_v1",
)

if trigger.should_trigger_retraining():
    print(f"Retraining triggered: {trigger.priority} priority")
    # Trigger retraining pipeline
```

## Uncertainty-Aware Risk Gating

### Trade Evaluation

```python
from atlas.control.uncertainty_gating import (
    create_uncertainty_gating,
    UncertaintyGatingConfig,
)

# Configure gating
config = UncertaintyGatingConfig(
    max_position_scale=1.0,
    min_position_scale=0.1,
    interval_width_threshold=0.05,
    confidence_threshold=0.70,
)

gating = create_uncertainty_gating("uncertainty_gate", config)

# Evaluate trade proposal
decision = gating.evaluate_trade(
    model_id="transformer_v1",
    instrument_id="BTC-USD",
    prediction=68000.0,
    lower=67500.0,
    upper=68500.0,
    confidence=0.80,
    current_price=68000.0,
    proposed_position=10000.0,
)

if decision.trade_allowed:
    print(f"Trade allowed with scale: {decision.position_scale:.2f}")
else:
    print(f"Trade rejected: {decision.rejection_reason}")
```

### Position Adjustment

```python
# Adjust position based on uncertainty
adjustment = gating.adjust_position(
    model_id="transformer_v1",
    instrument_id="BTC-USD",
    original_position=10000.0,
    prediction=68000.0,
    lower=67500.0,
    upper=68500.0,
    confidence=0.80,
    current_price=68000.0,
)

print(f"Original: ${adjustment.original_position_size:,.2f}")
print(f"Adjusted: ${adjustment.adjusted_position_size:,.2f}")
print(f"Scale: {adjustment.scaling_factor:.2f}")
```

### Risk Budget Management

```python
from atlas.control.uncertainty_gating import create_budget_manager

# Create budget manager
budget_manager = create_budget_manager(
    manager_id="risk_budget",
    gating=gating,
    base_risk_budget=0.02,  # 2% of equity
)

# Adjust budget based on aggregate uncertainty
budget = budget_manager.adjust_risk_budget(decisions)

print(f"Total budget: {budget.total_risk_budget:.2%}")
print(f"Effective budget: {budget.effective_risk_budget:.2%}")
print(f"Remaining: {budget.remaining_risk:.2%}")
```

## Feature Store

### Storing Features

```python
from atlas.features.feature_store import (
    create_feature_store,
    FeatureMetadata,
    FeatureLineage,
)
import pandas as pd
from datetime import datetime, timezone

# Create feature store
store = create_feature_store(
    store_id="main_feature_store",
    db_path="data/feature_store.db",
    parquet_dir="data/parquet_features",
)

# Prepare data
timestamps = pd.date_range(start="2024-01-01", periods=1000, freq="1H")
data = pd.DataFrame({
    "timestamp": timestamps,
    "returns": np.random.randn(1000),
    "volume": np.random.randn(1000),
    "vpin": np.random.rand(1000),
})

# Define metadata
metadata = FeatureMetadata(
    feature_name="btc_returns",
    feature_type="numeric",
    description="BTC returns with microstructure features",
    source="databento",
    lineage_ref="lineage_001",
    license_ref="CC-BY-4.0",
    created_at=datetime.now(timezone.utc),
    version=1,
)

# Define lineage
lineage = FeatureLineage(
    lineage_id="lineage_001",
    feature_name="btc_returns",
    transformation_steps=(
        {"step": "compute_returns", "params": "{}"},
        {"step": "add_microstructure", "params": "{}"},
    ),
    source_features=("raw_trades", "raw_quotes"),
    created_at=datetime.now(timezone.utc),
)

# Store feature
version = store.store_feature(
    feature_name="btc_returns",
    data=data,
    metadata=metadata,
    lineage=lineage,
)
```

### Retrieving Features

```python
# Get latest version
df = store.get_feature("btc_returns")

# Get specific version
df_v1 = store.get_feature("btc_returns", version=1)

# Get point-in-time version
as_of = datetime(2024, 6, 1, tzinfo=timezone.utc)
df_pit = store.get_feature("btc_returns", as_of=as_of)
```

### Querying Multiple Features

```python
# Query multiple features with time range
result = store.query_features(
    feature_names=["btc_returns", "eth_returns", "volume"],
    start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
)
```

### Feature Importance

```python
# Register feature importance for a model
importance = {
    "returns": 0.8,
    "volume": 0.6,
    "vpin": 0.4,
    "ofi": 0.3,
}

store.register_feature_importance(
    model_id="transformer_v1",
    feature_importance=importance,
    importance_type="shap",
)

# Retrieve importance
records = store.get_feature_importance("transformer_v1", "shap")
for record in records:
    print(f"{record.feature_name}: {record.importance_score:.3f}")
```

## Control Plane Integration

### Enhanced Control Plane

```python
from atlas.control.advanced_integration import (
    create_enhanced_control_plane,
    register_model_integration,
)
from atlas.control.engine import ActionableControlPlaneEngine

# Create base control plane
base_engine = ActionableControlPlaneEngine(...)

# Create enhanced control plane with ML integration
enhanced_engine = create_enhanced_control_plane(
    engine_id="enhanced_cp",
    base_engine=base_engine,
    uncertainty_config=config,
)

# Register model integration
integration = register_model_integration(
    engine=enhanced_engine,
    model=transformer_model,
    calibration=calibration_system,
)
```

### Order Evaluation with Uncertainty

```python
from atlas.control.engine import ActionableOrderRequest

# Create order request
request = ActionableOrderRequest(
    track="competition",
    instrument_id="comp:btc-perp:v1",
    side="buy",
    notional_usd=Decimal("25000"),
    stop_kind="atr",
    stop_distance_bps=Decimal("180"),
)

# Evaluate with uncertainty gating
base_decision, uncertainty_decision = enhanced_engine.evaluate_order_with_uncertainty(
    request=request,
    prediction=68000.0,
    lower=67500.0,
    upper=68500.0,
    confidence=0.80,
)

if base_decision.control_plane_decision == "authorized_and_executed":
    print("Order authorized")
else:
    print(f"Order rejected: {base_decision.violations}")
```

## Calibration

### Probability Calibration

```python
from atlas.models.uncertainty_calibration import (
    UncertaintyAwareCalibration,
    CalibrationConfig,
)

# Fit calibration system
calibration = UncertaintyAwareCalibration.fit(
    probabilities=probabilities,
    outcomes=outcomes,
    predictions=predictions,
    actuals=actuals,
    lower_bounds=lower_bounds,
    upper_bounds=upper_bounds,
    config=CalibrationConfig(method="conformal"),
    instrument_id="BTC-USD",
    horizon_id="1h",
    model_revision="v1",
    target="return",
    unit="fraction",
    fitted_through=datetime.now(timezone.utc),
)

# Apply calibration
calibrated_prob, calibrated_lower, calibrated_upper = calibration.calibrate_forecast(
    probability_up=0.75,
    lower=67500.0,
    upper=68500.0,
    prediction=68000.0,
)
```

### Calibration Diagnostics

```python
from atlas.models.uncertainty_calibration import CalibrationDiagnostics

# Compute calibration diagnostics
diagnostics = CalibrationDiagnostics.compute(
    calibration_id="cal_001",
    predictions=predictions,
    actuals=actuals,
    lower_bounds=lower_bounds,
    upper_bounds=upper_bounds,
    expected_coverage=0.90,
)

print(f"Expected coverage: {diagnostics.expected_coverage:.2%}")
print(f"Actual coverage: {diagnostics.actual_coverage:.2%}")
print(f"Coverage error: {diagnostics.coverage_error:.3f}")
print(f"Mean interval width: {diagnostics.mean_interval_width:.3f}")
```

## Best Practices

### Model Training

1. **Always use frozen datasets** with SHA-256 verification for reproducibility
2. **Use purged walk-forward evaluation** to avoid look-ahead bias
3. **Calibrate probabilities and intervals** on validation data only
4. **Register all models** with proper metadata and lineage

### Drift Detection

1. **Establish baselines** on stable market periods
2. **Monitor both feature and performance drift** for comprehensive coverage
3. **Set appropriate thresholds** based on historical volatility
4. **Use automated triggers** for timely retraining

### Risk Gating

1. **Configure thresholds** based on risk appetite and market conditions
2. **Monitor uncertainty levels** across all active trades
3. **Adjust risk budgets** dynamically based on aggregate uncertainty
4. **Document all gating decisions** for audit and analysis

### Feature Store

1. **Use versioning** for all features to enable reproducibility
2. **Track lineage** for all transformations
3. **Use Parquet compression** for efficient storage
4. **Query with time ranges** to minimize data transfer

### Control Plane Integration

1. **Maintain strict separation** between AI research and execution
2. **All AI outputs must have `execution_permission: "none"`**
3. **Only the control plane can authorize trades**
4. **Log all decisions** for audit and compliance

## Testing

Run the test suite:

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_transformer_forecaster.py

# Run with coverage
pytest tests/ --cov=src/atlas/models --cov=src/atlas/control --cov=src/atlas/features
```

## Dependencies

New dependencies added to `requirements.txt`:

- `pandas>=2.0.0` - Data manipulation for feature store
- `pyarrow>=14.0.0` - Parquet file format support
- `numpy>=1.24.0` - Numerical computations
- `scipy>=1.11.0` - Statistical tests for drift detection

Existing dependencies used:

- `duckdb>=0.10.0` - Feature store database
- `pydantic>=2.6` - Data validation
- `pytest>=8` - Testing framework
- `fastapi>=0.115` - API framework
- `uvicorn>=0.32` - ASGI server

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Research Layer                        │
│  (execution_permission: "none")                            │
├─────────────────────────────────────────────────────────────┤
│  Transformer Forecaster  │  Drift Detection  │ Calibration  │
│  - Multi-head Attention  │  - KS Test        │  - Conformal  │
│  - MC Dropout           │  - PSI            │  - Temp Scale │
│  - Prediction Intervals │  - Performance     │              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Uncertainty-Aware Gating                    │
│  - Position Scaling    │  - Trade Filtering                 │
│  - Risk Budgeting     │  - Confidence Thresholds            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Deterministic Control Plane                    │
│  ActionableControlPlaneEngine                              │
│  - Rule Enforcement  │  - Position Management             │
│  - Risk Limits      │  - Kill Switch                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Feature Store                            │
│  DuckDB + Parquet (ZSTD)                                   │
│  - Versioning        │  - Lineage Tracking                 │
│  - PIT Queries      │  - Importance Tracking              │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### Transformer Forecasting

```bash
# Generate forecast with uncertainty
POST /api/advanced-ml/forecast
Content-Type: application/json
X-Role-Id: quant_researcher

{
  "model_id": "transformer_v1",
  "features": [[...]],  # sequence_length x n_features
  "mc_samples": 100,
  "enable_dropout": true
}
```

### Drift Detection

```bash
# Check for feature drift
POST /api/advanced-ml/drift/check
Content-Type: application/json

{
  "monitor_id": "btc_monitor",
  "feature_name": "returns",
  "current_values": [...],
  "method": "both"
}

# Get dashboard summary
GET /api/advanced-ml/drift/dashboard/summary

# Get monitor history
GET /api/advanced-ml/drift/dashboard/{monitor_id}/history?limit=50

# Evaluate drift from dashboard
POST /api/advanced-ml/drift/dashboard/{monitor_id}/evaluate
Content-Type: application/json

{
  "current_features": {"returns": [...], "volume": [...]},
  "current_metrics": {"mae": 0.07}
}
```

### Feature Store

```bash
# Store a feature
POST /api/advanced-ml/features/store
Content-Type: application/json

{
  "feature_name": "btc_returns",
  "data": [{"timestamp": "...", "value": 1.0}],
  "metadata": {
    "feature_type": "numeric",
    "description": "BTC returns",
    "source": "databento",
    "lineage_ref": "lineage_001",
    "license_ref": "CC-BY-4.0"
  }
}

# Retrieve a feature
GET /api/advanced-ml/features/{feature_name}?version=1

# List all features
GET /api/advanced-ml/features
```

### Uncertainty Gating

```bash
# Evaluate trade with uncertainty gating
POST /api/advanced-ml/uncertainty/gate
Content-Type: application/json

{
  "model_id": "transformer_v1",
  "instrument_id": "BTC-USD",
  "prediction": 68000.0,
  "lower": 67500.0,
  "upper": 68500.0,
  "confidence": 0.80,
  "current_price": 68000.0,
  "proposed_position": 10000.0
}
```

## WebSocket Support

### Drift Alerts WebSocket

```javascript
// Connect to drift alerts WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/drift-alerts');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  switch (message.type) {
    case 'connected':
      console.log('Connected:', message.client_id);
      break;
    case 'heartbeat':
      console.log('Heartbeat:', message.timestamp);
      break;
    case 'drift_alert':
      console.log('Drift detected:', message);
      break;
    case 'error':
      console.error('Error:', message.error);
      break;
  }
};
```

## Live Market Data Integration

### Live drift monitoring

The unused `atlas.marketdata.drift_integration` wrapper was removed (2026-10-24 streamline). Drift detection lives in
`atlas.models.drift_detection` and `atlas.ml.drift`, registered as the `drift` component of the AI node (`atlas.ai.node`,
`GET /api/ai/components/drift`); alerts stream on `/ws/drift-alerts`. Drift output is advisory (`execution_permission: none`).

## Next Steps

1. Train the forecast head on a larger authorized, licensed dataset and report
   the measured walk-forward result; do not describe the fixed encoder as full
   end-to-end training.
2. Feed the drift API observed feature windows from the live observer; keep
   synthetic feature vectors out of drift verdicts.
3. Add calibrated intervals and out-of-sample reliability diagrams to the
   prediction ledger.
4. Add genuine SHAP/permutation importance where the chosen library is
   installed; otherwise report the method as unavailable.
5. Add hyperparameter search only after the baseline evidence is reproducible.
6. Keep execution research separate until a deterministic, audited connector
   path exists.

## Support

For questions or issues, refer to:
- Main ATLAS documentation: `docs/ATLAS_MASTER_SPEC.md`
- Architecture decisions: `docs/architecture/DECISIONS.md`
- Universal AI ecosystem: `docs/architecture/UNIVERSAL_AI_ECOSYSTEM.md`

## Vertical research slice

`atlas.research.vertical_slice` is the end-to-end evidence path used by
`/research/prediction-ledger`.

1. Authorized public OHLCV bars are normalized with an event time and a
   conservative `available_at` bar-close time.
2. Causal features and forward labels are built only from completed bars.
3. Softmax, XGBoost, class-frequency, and uniform candidates are scored on the
   same chronological, purged, and embargoed walk-forward. The candidate with
   the lowest Brier, then log loss, is selected.
4. The latest row receives a forecast with `long`, `short`, or `abstain`, a
   multiclass probability vector, and an empirical 5�95% return interval.
5. An action is sent to `ActionableControlPlaneEngine`. The uncertainty gate
   may reject it before submission; the base rulebook remains the final
   authorization. No forecast can place a live order.
6. Forecasts, outcomes, model coefficients, paper authorizations, and measured
   limitations are stored in SQLite. Forecast Brier/log loss and paper P&L are
   reported separately.
7. "Lucky moments" lists favorable outcomes with low confidence or moves
   outside the expected interval and labels them as possible luck.

API:

```text
GET  /api/research/vertical-slice/status
GET  /api/research/vertical-slice/chart
GET  /api/research/vertical-slice/forecasts
GET  /api/research/vertical-slice/paper-trades
GET  /api/research/vertical-slice/lucky-moments
POST /api/research/vertical-slice/run
POST /api/research/vertical-slice/resolve
```

The run endpoint fetches authorized public candles. If the venue is unavailable,
the response is `unavailable`; no synthetic forecast is substituted.

## Drift dashboard status

`/research/drift-dashboard` now redirects to `/research`. The earlier page used
`Math.random()` to synthesize current features and metrics, which made its
drift verdicts meaningless. The drift research modules remain importable for
isolated experiments, but their HTTP surface is retired; any future exposure
must consume observed feature windows and live behind the audited slice.

## Paper persistence and completed-bar scheduler

The vertical slice now snapshots its paper engine into the `paper_state` table
after every run and resolution. The snapshot includes open positions, the
matching order-history entries (needed for entry price), equity, high-water
mark, exposure fields, sequence counters, and the audit tail. A new
`VerticalSliceService` restores that snapshot during construction, so open paper
positions and their authorization state survive an API restart. Closed
positions remain in the forecast/trade ledger; nothing is reconstructed from
missing data.

Each forecast horizon has its own paper book and snapshot key. Horizon 1 keeps
the original `vertical_slice_paper:v1` key; additional horizons use
`vertical_slice_paper:v1:h{n}`. Forecasts persist `bucket_seconds` and
`horizon_steps`, and the ledger migrates older databases by adding those
nullable columns. Resolution selects the matching book from the persisted
horizon, so a 5-bar forecast cannot close a 1-bar position. The API's
`paper_account` is the aggregate of the books and includes per-horizon
`books` detail.

`VerticalSliceScheduler` checks completed public bars and runs the slice only
when the latest completed bar is newer than the latest recorded forecast for
that symbol and horizon. It then resolves any forecast whose target time is
due. The scheduler persists its own counters and timestamps in the same table.
It is enabled on app startup when public data is enabled; tests and offline runs
do not start it. A SQLite-adjacent scheduler lock file prevents two API
processes from owning the loop at the same time; a second process reports
`scheduler_lock_held_elsewhere` instead of duplicating runs. Manual ticks acquire
and release the same lock, so an out-of-band tick cannot race another process.
Settings:

- `ATLAS_VERTICAL_SLICE_SYMBOLS` (default: the nine desk names)
- `ATLAS_VERTICAL_SLICE_HORIZONS` (default: `1`; comma-separated, each 1-24)
- `ATLAS_VERTICAL_SLICE_BUCKET_SECONDS` (default: `86400`)
- `ATLAS_VERTICAL_SLICE_POLL_SECONDS` (default: `300`)
- `ATLAS_VERTICAL_SLICE_INITIAL_DELAY_SECONDS` (default: `60`)
- `ATLAS_DISABLE_VERTICAL_SLICE_SCHEDULER=1` to disable the background loop

API: `GET /api/research/vertical-slice/scheduler` reports status;
`POST /api/research/vertical-slice/scheduler/tick|start|stop` controls it with
the same research authorization used by run/resolve. `GET
/api/research/vertical-slice/status` also exposes `paper_account` (equity,
open positions, gross/exposure, kill switch, restoration flag) and the scheduler
snapshot. The prediction-ledger page shows both. Every response and every paper
action remains `execution_permission: "none"`.

## Multi-horizon evaluation

`POST /api/research/vertical-slice/evaluate-multi` runs the audited slice across
up to 12 symbols and 6 horizons (1-24 bars). It fetches candles once per symbol,
then evaluates each horizon with the same purged walk-forward, model-selection,
and baseline rules. It uses an isolated in-memory ledger, so an evaluation
cannot create paper trades, mutate the production ledger, or authorize an
order. The prediction-ledger page exposes the same matrix for the selected
symbol at horizons 1, 5, and 20.

Separately, the scheduler can serve multiple horizons set by
`ATLAS_VERTICAL_SLICE_HORIZONS`. Each horizon records its own forecast and
paper book; the scheduler skips a symbol/horizon only when that horizon already
has a forecast for the completed bar. The evaluation endpoint remains isolated
and cannot create those books.

## Feature-family ablation

`POST /api/research/vertical-slice/feature-ablation` removes one feature family
at a time and retrains the softmax model on the same purged walk-forward folds.
It reports the baseline softmax metrics, each family's removed features, its
out-of-sample Brier/log-loss/accuracy, and the delta from the baseline. It is
read-only: no forecast, paper trade, or order permission is created. The
prediction ledger exposes the same experiment through **Ablate features**.

`POST /api/research/vertical-slice/feature-ablation-multi` repeats the same
experiment across up to six symbols and three horizons, with one purged
walk-forward per cell. Each row reports the selected baseline, supported,
negative, and inconclusive families. It also reports descriptive regime
breakdowns using trailing volatility and trend thresholds (`up/down` ×
`high/low` volatility) so each family can be compared inside each regime. Those
labels are causal and descriptive, but they are not a validated regime
classifier. The endpoint is bounded so a request cannot trigger unbounded
retraining, and it never writes forecasts, paper trades, or order permission.
The prediction ledger exposes it through **Ablate matrix**.

Production families are momentum (`return_1/3/5/10`), trend (`trend_10`),
volatility (`realized_vol_5`, `range_pct`, `atr_5_pct`), positioning
(`close_location`, `drawdown_5`), and volume (`volume_z_10`,
`volume_change_5`). Positive `delta_brier_removed` means removing the family
made Brier worse, so the family carried out-of-sample information. Differences
smaller than 0.005 are labeled inconclusive; the endpoint does not promote a
model or claim profitability.

Two research-only candidates can be included without changing the production
feature set:

- `include_session=true` adds `session_sin/cos` and `weekday_sin/cos`, derived
  only from the decision timestamp.
- `include_cross_asset=true` adds reference returns, relative return,
  rolling correlation, and a volatility ratio. Reference candles are aligned
  by `available_at <= decision_time`; the default reference is ETH-USD for
  BTC-USD, BTC-USD for other crypto, QQQ for SPY, and SPY otherwise. A missing
  reference is reported and produces no cross-asset columns.

These candidates are retrained and ablated exactly like the production families.
The prediction-ledger matrix enables both. They remain research candidates until
they survive independent out-of-sample folds; nothing is silently promoted.

Measured on 350 authorized daily BTC-USD bars, horizon 1, on 2026-10-22:

| Variant | Brier | Log loss | Accuracy |
| --- | ---: | ---: | ---: |
| All features (softmax) | 0.6134 | 1.0002 | 42.1% |
| Remove momentum | 0.6076 | 0.9901 | 42.1% |
| Remove trend | 0.6116 | 0.9958 | 42.1% |
| Remove volatility | 0.6073 | 0.9938 | 42.1% |
| Remove positioning | 0.6116 | 0.9974 | 42.1% |
| Remove volume | 0.6129 | 0.9982 | 42.1% |

The frequency baseline still won on this sample. Removing momentum or
volatility slightly improved the softmax Brier, while the other families were
inconclusive. These small differences are not evidence that the families are
useless across assets or regimes, and they are not evidence of profitability.
The cross-symbol/cross-horizon matrix is now available for repetition; regime
labels and non-price data are still required before changing the production
feature set.

The advanced-ML HTTP surface is retired. `GET /api/advanced-ml/status` returns
HTTP 503 with `state: "retired"` and points callers to
`/api/research/vertical-slice`. The underlying transformer, drift, feature, and
gating modules remain importable for isolated experiments; there is no longer a
second public research API. `GET /api/research/experimental-status` reports the
same retirement state.

## Measured live smoke result

On 2026-10-22 the vertical slice fetched 350 authorized daily BTC-USD bars
from Coinbase's public candles endpoint. The purged expanding walk-forward
scored these models on the same out-of-sample decisions:

| Candidate | Multiclass Brier | Log loss | Accuracy |
| --- | ---: | ---: | ---: |
| Softmax logistic | 0.6152 | 1.0035 | 42.1% |
| XGBoost multiclass | 0.6661 | 1.0837 | 47.4% |
| Class-frequency baseline | 0.5854 | 0.9500 | 46.1% |
| Uniform baseline | 0.6667 | 1.0986 | 33.3% |

The class-frequency baseline had the lowest Brier and log loss, so it was
selected. The recorded forecast abstained. This is a negative result for the
learned models on this single symbol and horizon; it is not evidence of
profitability and must not be generalized to other instruments. The important
behavior is that ATLAS compared against baselines, selected the evidence-based
candidate, and abstained instead of forcing a trade.
