"""Market-data admission and actual candle availability precede all slice ML."""
from datetime import datetime, timedelta, timezone
import math

import pytest

from atlas.marketdata import public_quotes
from atlas.marketdata.data_rights import DataUseDenied
from atlas.research import vertical_slice as slice_module
from atlas.research.vertical_slice import ForecastLedger, SliceConfig, VerticalSliceScheduler, VerticalSliceService

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def rows(count=80, source=None):
    result = []
    for index in range(count):
        price = 100 + index * .1 + math.sin(index / 3)
        row = {"timestamp": (START + timedelta(days=index)).isoformat(),
               "open": price, "high": price + 1, "low": price - 1,
               "close": price + .2, "volume": 1000 + index}
        if source:
            row["source"] = source
        result.append(row)
    return result


@pytest.fixture
def service(monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_USE_POLICY", raising=False)
    ledger = ForecastLedger(":memory:")
    instance = VerticalSliceService(ledger=ledger, config=SliceConfig(epochs=8, min_train_rows=1000))
    yield instance
    ledger.close()


def assert_no_market_state(service):
    for table in ("models", "forecasts", "paper_trades"):
        assert service.ledger._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["run", "ablate", "ablate_multi", "evaluate", "resolve", "scheduler"])
def test_all_public_fetch_entrypoints_deny_before_network_and_model_work(service, monkeypatch, operation):
    def forbidden(*args, **kwargs):
        pytest.fail("Denied source reached network, model fit, evaluation, or paper execution")

    monkeypatch.setattr(public_quotes, "_get_json", forbidden)
    monkeypatch.setattr(slice_module, "fit_softmax", forbidden)
    monkeypatch.setattr(slice_module, "purged_walk_forward", forbidden)
    monkeypatch.setattr(slice_module, "execute_forecast_paper_trade", forbidden)
    if operation == "run":
        blocked = service.run(symbols=["BTC-USD"])["symbols"][0]
    elif operation == "ablate":
        blocked = service.ablate_features(symbol="BTC-USD")
    elif operation == "ablate_multi":
        blocked = service.ablate_multi(symbols=["BTC-USD"])["rows"][0]
    elif operation == "evaluate":
        blocked = service.evaluate_multi(symbols=["BTC-USD"])["rows"][0]
    elif operation == "resolve":
        report = service.resolve(symbols=["BTC-USD"])
        assert report["count"] == 0
        blocked = report["blocked"][0]
    else:
        report = VerticalSliceScheduler(service, symbols=["BTC-USD"], initial_delay_seconds=0).tick()
        assert report["runs"] == report["resolutions"] == 0
        blocked = report["details"][0]
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "data_use_denied"
    assert blocked["data_use"]["allowed"] is False
    assert_no_market_state(service)


@pytest.mark.parametrize("metadata", [
    {"source": "coinbase_exchange_public"},
    {"feed_origin": "yahoo_chart_public"},
    {"source": "public_market_candles"},
    {"license_ref": "venue_public_research_terms"},
    {"provider_id": "coinbase_exchange_live_api"},
])
def test_supplied_public_rows_cannot_bypass_admission_with_fetch_false(service, monkeypatch, metadata):
    supplied = [{**row, **metadata} for row in rows()]
    monkeypatch.setattr(slice_module, "fit_softmax", lambda *args, **kwargs: pytest.fail("Unlicensed data reached model fit"))
    report = service.run(symbols=["BTC-USD"], candles_by_symbol={"BTC-USD": supplied}, fetch=False)
    assert report["symbols"][0]["status"] == "blocked"
    assert_no_market_state(service)


def test_public_reference_data_requires_its_own_admission(service):
    report = service.ablate_features(
        symbol="BTC-USD", candles=rows(), reference_symbol="ETH-USD",
        reference_candles=rows(source="coinbase_exchange_public"),
        include_cross_asset=True, fetch=False,
    )
    assert report["status"] == "blocked"
    assert report["data_use"]["symbol"] == "ETH-USD"
    assert_no_market_state(service)


def test_retention_permission_is_required_in_addition_to_training(service, monkeypatch):
    checked = []

    def permission(provider, symbol, bucket, use):
        checked.append(use)
        decision = {"provider_id": provider, "symbol": symbol, "intended_use": use,
                    "allowed": use == "training", "reason": "retention not granted"}
        if not decision["allowed"]:
            raise DataUseDenied(decision)
        return decision

    monkeypatch.setattr(slice_module, "require_data_use", permission)
    result = service.run(symbols=["BTC-USD"], candles_by_symbol={"BTC-USD": rows(source="coinbase_exchange_public")}, fetch=False)
    assert result["symbols"][0]["status"] == "blocked"
    assert checked == ["training", "retention"]
    assert_no_market_state(service)


def test_injected_unannotated_research_is_not_declared_authorized_or_deployable(service):
    normalized, quality = slice_module._admit_rows(rows(5), symbol="BTC-USD", bucket_seconds=86400, as_of=START + timedelta(days=5))
    assert len(normalized) == 5
    assert quality["source"] == "user_supplied_unverified"
    assert quality["license_ref"] == "unknown"
    assert quality["data_use_admission"]["state"] == "unverified_user_supplied"
    assert quality["deployment_eligible"] is False


def test_forming_and_future_bars_cannot_change_a_current_fit_or_forecast(service):
    cutoff = START + timedelta(days=60, hours=12)
    supplied = rows()
    first = service.run(symbols=["BTC-USD"], candles_by_symbol={"BTC-USD": supplied}, fetch=False, now=cutoff, paper=False)["symbols"][0]
    assert first["bars"] == 60
    assert first["quality"]["rows_not_yet_available"] == 20
    assert datetime.fromisoformat(first["forecast"]["decision_time"]) <= cutoff
    mutated = [dict(row) for row in supplied]
    for row in mutated[60:]:
        for key in ("open", "high", "low", "close"):
            row[key] *= 100
    ledger = ForecastLedger(":memory:")
    try:
        second_service = VerticalSliceService(ledger=ledger, config=service.config)
        second = second_service.run(symbols=["BTC-USD"], candles_by_symbol={"BTC-USD": mutated}, fetch=False, now=cutoff, paper=False)["symbols"][0]
        assert second["dataset_hash"] == first["dataset_hash"]
        assert second["forecast"]["probabilities"] == first["forecast"]["probabilities"]
    finally:
        ledger.close()


def test_scheduler_does_not_train_on_a_forming_only_snapshot(service):
    scheduler = VerticalSliceScheduler(service, symbols=["BTC-USD"], bucket_seconds=86400, initial_delay_seconds=0)
    report = scheduler.tick(candles_by_symbol={"BTC-USD": rows(1)}, now=START + timedelta(hours=12), fetch=False)
    assert report["runs"] == report["resolutions"] == 0
    assert report["details"][0]["status"] == "no_usable_candles"
    assert report["last_bar_at"] is None
    assert_no_market_state(service)
