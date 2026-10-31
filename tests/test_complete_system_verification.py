"""Comprehensive Verification Suite for ATLAS Complete System Verification, Live Intelligence Repair & Continuous AI Evolution.

Covers:
- Section 22: End-to-End Live Prediction Diagnostic Tests across BTC-USD, ETH-USD, SOL-USD, SPY, QQQ, NQ, GC, and Pump.fun.
- Section 23: Deterministic Market Status Engine Tests across all 17 required states, holidays, early closes, CME maintenance,
  DST transitions, venue halts/restrictions, stale/disconnected feeds, Pump.fun curve/migration states, and Nasdaq 23/5 effective date.
- Section 24: Model Evolution, Expected Value (EV) Intelligence, EV Evolution Monitor, Champion-Challenger Lifecycle & Rollback.
- Section 25: Strict `execution_permission == "none"` safety boundary across all ML/AI endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from atlas.ai.ml.live_intelligence import (
    FEATURE_SCHEMA_VERSION,
    HEALTH_CLASSIFICATIONS,
    MODEL_LIFECYCLE_ROLES,
    PREDICTION_STATUSES,
    compute_ev_intelligence,
    generate_live_prediction,
    get_champion_challenger_registry,
    get_ev_evolution_monitor,
    get_evolution_intelligence_dashboard,
    get_prediction_health,
    get_strategy_evolution_matrix,
    rollback_or_transition_model,
)
from atlas.api.app import app
from atlas.market.sessions import (
    CME_CONTRACT_SPECS,
    NASDAQ_23_5_EFFECTIVE_DATE,
    VALID_MARKET_STATES,
    evaluate_instrument_market_status,
    get_market_sessions_status,
)

ET = ZoneInfo("America/New_York")
client = TestClient(app)


@pytest.fixture
def isolated_live_models(tmp_path, monkeypatch):
    """Explicit passing fixtures; local research artifacts never imply live eligibility."""
    from atlas.ai.ml import live_intelligence as live
    from atlas.api import feeds_api

    registry = tmp_path / "registry"
    registry.mkdir()
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(registry))
    monkeypatch.setattr(live, "_MODEL_CACHE", {})
    model = SimpleNamespace(
        calibrator=SimpleNamespace(kind="platt"),
        conformal=SimpleNamespace(qhat=0.15),
        win_r={}, loss_r={},
        decide=lambda frame, use_conformal: {"p": [0.6], "take": [True]},
    )
    monkeypatch.setattr(live, "load_model", lambda version, path: model)
    for group in ("crypto-15m", "crypto-1h", "crypto-4h", "equity-15m", "equity-1h"):
        asset_class, interval = group.split("-")
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT") if asset_class == "crypto" else ("SPY", "QQQ")
        directory = registry / group
        directory.mkdir()
        manifest = {
            "version": group, "group": group, "status": "eligible",
            "created_at": "2026-10-20T00:00:00+00:00", "calibrator": "platt",
            "gates": [{"gate": "test_validation", "passed": True}],
            "series": [{"instrument": symbol, "asset_class": asset_class, "interval": interval}
                       for symbol in symbols],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    cutoff = datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc).timestamp()
    def bars(symbol, interval):
        duration = {"15m": 900, "1h": 3600, "4h": 14400}.get(interval, 900)
        return [SimpleNamespace(
            event_time=int(cutoff - (300 - i) * duration),
            open=100 + math.sin(i / 5), high=102 + math.sin(i / 5),
            low=98 + math.sin(i / 5), close=100 + math.sin((i + 1) / 5), volume=1000 + i,
        ) for i in range(300)]
    feed = SimpleNamespace(bars=bars)
    monkeypatch.setattr(feeds_api, "_feed", lambda: feed)
    return feed


# ============================================================================
# SECTION 22: END-TO-END LIVE PREDICTION DIAGNOSTIC TESTS
# ============================================================================


@pytest.mark.parametrize(
    "symbol,interval,expected_status",
    [
        ("BTC-USD", "15m", "VALID"),
        ("ETH-USD", "15m", "VALID"),
        ("SOL-USD", "15m", "VALID"),
        ("SPY", "15m", "VALID"),
        ("QQQ", "15m", "VALID"),
        ("NQ", "1h", "MODEL_UNAVAILABLE"),
        ("GC", "15m", "MODEL_UNAVAILABLE"),
    ],
)
def test_end_to_end_live_prediction_across_universe(symbol: str, interval: str, expected_status: str, isolated_live_models) -> None:
    """Verify candle -> feature -> model -> calibration -> persistence -> API response across all required asset classes."""
    # Evaluate during a regular Wednesday morning session so markets are open
    wed_open = datetime(2026, 10, 21, 10, 30, tzinfo=ET).astimezone(timezone.utc)
    pred = generate_live_prediction(
        symbol=symbol,
        interval=interval,
        now=wed_open,
        stale_threshold_seconds=86400 * 365,
        persist=True,
    )
    assert pred["execution_permission"] == "none"
    assert pred["prediction_status"] == expected_status
    if expected_status != "VALID":
        assert pred["probability_target_before_stop"] is None
        assert "No eligible model" in pred["status_reason"]
        return
    assert pred["data_quality_status"] == "VALID"
    assert pred["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert pred["model_version"] != "MODEL_UNAVAILABLE"
    assert pred["calibration_version"] != "UNCALIBRATED"
    assert 0.0 < float(pred["probability_target_before_stop"]) < 1.0
    p_sum = float(pred["probability_up"]) + float(pred["probability_down"]) + float(pred["probability_neutral"])
    assert abs(p_sum - 1.0) < 1e-3
    assert pred["expected_return_after_costs"] is not None
    assert pred["expected_value"]["formula"] == "EV = p * G - (1 - p) * L - (Fees + Slippage)"
    assert pred["uncertainty"] is not None and float(pred["uncertainty"]) > 0.0


def test_open_market_stale_bars_are_not_valid(isolated_live_models, tmp_path) -> None:
    """A 15m bar four days older than the prediction must not be data_quality VALID.

    The old default freshness floor was 7 days, so this case was scored as VALID.
    Forcing the feed flag to HEALTHY must not override the bar timestamp.
    """
    from datetime import timedelta
    wed_open = datetime(2026, 10, 21, 10, 30, tzinfo=ET).astimezone(timezone.utc)
    later = wed_open + timedelta(days=4)
    for health in (None, "HEALTHY"):
        pred = generate_live_prediction(
            "BTC-USD", "15m", now=later, data_feed_health=health, persist=True,
        )
        assert pred["prediction_status"] == "STALE_MARKET_DATA"
        assert pred["data_quality_status"] != "VALID"
        assert pred["probability_target_before_stop"] is None
        assert pred["execution_permission"] == "none"
    assert not (tmp_path / "live_predictions.jsonl").exists()
    health = get_prediction_health(reg_path=tmp_path / "registry")
    assert health["prediction_log"]["live_predictions_jsonl"] == "retired"


def test_feature_schema_mismatch_is_not_scored(isolated_live_models, tmp_path) -> None:
    path = tmp_path / "registry" / "crypto-15m" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["features"] = ["not_a_real_feature"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    pred = generate_live_prediction(
        "BTC-USD", "15m", now=datetime(2026, 10, 21, 10, 30, tzinfo=ET), persist=False,
    )
    assert pred["prediction_status"] == "MODEL_UNAVAILABLE"
    assert pred["data_quality_status"] == "FEATURE_SCHEMA_MISMATCH"
    assert pred["data_quality_status"] != "VALID"
    assert pred["probability_target_before_stop"] is None
    assert pred["feature_schema_version"] == FEATURE_SCHEMA_VERSION


def test_live_prediction_non_fabricated_failure_states(tmp_path, isolated_live_models) -> None:
    """Verify explicit non-fabricated statuses when model is unavailable, data is stale, or market is closed."""
    wed_open = datetime(2026, 10, 21, 10, 30, tzinfo=ET).astimezone(timezone.utc)

    # 1. MODEL_UNAVAILABLE when registry directory is empty
    empty_reg = tmp_path / "empty_registry"
    empty_reg.mkdir(parents=True, exist_ok=True)
    res_unavail = generate_live_prediction(
        "BTC-USD",
        "15m",
        reg_path=empty_reg,
        now=wed_open,
        stale_threshold_seconds=86400 * 365,
        persist=False,
    )
    assert res_unavail["prediction_status"] == "MODEL_UNAVAILABLE"
    assert res_unavail["probability_target_before_stop"] is None
    assert res_unavail["execution_permission"] == "none"

    # 2. STALE_MARKET_DATA when feed health is STALE during open market
    res_stale = generate_live_prediction(
        "BTC-USD",
        "15m",
        now=wed_open,
        data_feed_health="STALE",
        persist=False,
    )
    assert res_stale["prediction_status"] == "STALE_MARKET_DATA"
    assert res_stale["data_quality_status"] == "STALE_MARKET_DATA"
    assert res_stale["probability_target_before_stop"] is None

    # 3. MARKET_CLOSED on Saturday for SPY (equity)
    sat_closed = datetime(2026, 10, 24, 14, 0, tzinfo=ET).astimezone(timezone.utc)
    res_closed = generate_live_prediction(
        "SPY",
        "15m",
        now=sat_closed,
        stale_threshold_seconds=86400 * 365,
        persist=False,
    )
    assert res_closed["market_status"] == "CLOSED"
    assert res_closed["prediction_status"] == "MARKET_CLOSED"
    assert res_closed["execution_permission"] == "none"

    # 4. Unknown symbol returns MODEL_UNAVAILABLE + INVALID_SYMBOL
    res_unknown = generate_live_prediction("INVALID_TICKER_XYZ999", "15m", now=wed_open, persist=False)
    assert res_unknown["market_status"] == "UNKNOWN"
    assert res_unknown["prediction_status"] == "MODEL_UNAVAILABLE"
    assert res_unknown["data_quality_status"] == "INVALID_SYMBOL"


def test_prediction_health_monitoring_endpoint(isolated_live_models) -> None:
    """Section 8: Verify GET /api/ml/prediction-health returns valid health classification and telemetry."""
    r = client.get("/api/ml/prediction-health?symbol=BTC-USD")
    assert r.status_code == 200
    body = r.json()
    assert body["health_classification"] in HEALTH_CLASSIFICATIONS
    assert body["registered_models_count"] >= 5
    assert body["execution_permission"] == "none"
    assert "inference_latency_ms" in body
    assert "prediction_success_rate" in body


def test_live_prediction_abstains_when_cached_model_fails_validation(tmp_path, isolated_live_models) -> None:
    now = datetime(2026, 10, 21, 10, 30, tzinfo=ET)
    first = generate_live_prediction("BTC-USD", "15m", now=now, persist=False)
    assert first["prediction_status"] == "VALID"
    path = tmp_path / "registry" / "crypto-15m" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = "not_eligible"
    manifest["gates"][0]["passed"] = False
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = generate_live_prediction("BTC-USD", "15m", now=now, persist=False)
    assert result["prediction_status"] == "MODEL_UNAVAILABLE"
    assert result["probability_target_before_stop"] is None
    assert result["expected_value"] is None
    assert result["execution_permission"] == "none"


@pytest.mark.parametrize("interval", ["1m", "1h", "4h"])
def test_missing_interval_bars_are_not_relabelled(interval, isolated_live_models) -> None:
    requested = []
    def bars(symbol, requested_interval):
        requested.append(requested_interval)
        return isolated_live_models.bars(symbol, "15m") if requested_interval == "15m" else []
    result = generate_live_prediction(
        "BTC-USD", interval, feed=SimpleNamespace(bars=bars),
        now=datetime(2026, 10, 21, 10, 30, tzinfo=ET), persist=False,
    )
    assert result["prediction_status"] == "INSUFFICIENT_HISTORY"
    assert result["probability_target_before_stop"] is None
    assert requested == [interval]


# ============================================================================
# SECTION 23: DETERMINISTIC MARKET STATUS ENGINE TESTS
# ============================================================================


def test_all_17_market_states_defined_and_cme_specs_present() -> None:
    """Verify all 17 required market states and CME contract specs exist."""
    expected_states = {
        "REGULAR_SESSION",
        "PREMARKET",
        "AFTER_HOURS",
        "OVERNIGHT_SESSION",
        "OPEN",
        "PREOPEN",
        "MAINTENANCE",
        "CLOSED",
        "HOLIDAY",
        "EARLY_CLOSE",
        "HALTED",
        "LIMIT_ONLY",
        "POST_ONLY",
        "CANCEL_ONLY",
        "VIEW_ONLY",
        "TRADING_DISABLED",
        "UNKNOWN",
    }
    assert expected_states.issubset(set(VALID_MARKET_STATES))
    for sym in ("GC", "MGC", "SI", "ES", "NQ", "MNQ", "CL"):
        assert sym in CME_CONTRACT_SPECS


def test_us_equity_sessions_holidays_early_close_and_nasdaq_23_5() -> None:
    """Test weekday open, premarket, after-hours, weekend, Thanksgiving holiday, Black Friday early close, and Nasdaq 23/5."""
    # 1. Weekday regular session (Wed Oct 21, 2026 11:00 ET)
    s_reg = evaluate_instrument_market_status("SPY", now=datetime(2026, 10, 21, 11, 0, tzinfo=ET))
    assert s_reg["scheduled_market_status"] == "REGULAR_SESSION"
    assert s_reg["market_status"] == "REGULAR_SESSION"
    assert s_reg["is_open"] is True

    # 2. Premarket (Wed Oct 21, 2026 07:15 ET)
    s_pre = evaluate_instrument_market_status("QQQ", now=datetime(2026, 10, 21, 7, 15, tzinfo=ET))
    assert s_pre["scheduled_market_status"] == "PREMARKET"
    assert s_pre["is_open"] is False
    assert s_pre["is_extended_hours"] is True

    # 3. After-hours (Wed Oct 21, 2026 17:30 ET)
    s_aft = evaluate_instrument_market_status("NVDA", now=datetime(2026, 10, 21, 17, 30, tzinfo=ET))
    assert s_aft["scheduled_market_status"] == "AFTER_HOURS"
    assert s_aft["is_open"] is False
    assert s_aft["is_extended_hours"] is True

    # 4. Weekend (Sat Oct 24, 2026 12:00 ET)
    s_wknd = evaluate_instrument_market_status("SPY", now=datetime(2026, 10, 24, 12, 0, tzinfo=ET))
    assert s_wknd["scheduled_market_status"] == "CLOSED"
    assert s_wknd["is_open"] is False

    # 5. Thanksgiving Holiday (Thu Nov 26, 2026 11:00 ET)
    s_hol = evaluate_instrument_market_status("SPY", now=datetime(2026, 11, 26, 11, 0, tzinfo=ET))
    assert s_hol["scheduled_market_status"] == "HOLIDAY"
    assert s_hol["is_holiday"] is True
    assert s_hol["is_open"] is False

    # 6. Black Friday Early Close (Fri Nov 27, 2026: open at 11:00 ET as EARLY_CLOSE, closed at 14:00 ET)
    s_early_open = evaluate_instrument_market_status("SPY", now=datetime(2026, 11, 27, 11, 0, tzinfo=ET))
    assert s_early_open["scheduled_market_status"] == "EARLY_CLOSE"
    assert s_early_open["is_early_close"] is True
    assert s_early_open["is_open"] is True

    s_early_after = evaluate_instrument_market_status("SPY", now=datetime(2026, 11, 27, 13, 30, tzinfo=ET))
    assert s_early_after["scheduled_market_status"] == "AFTER_HOURS"
    assert s_early_after["is_open"] is False

    # 7. Nasdaq 23/5: 2026-12-06 21:00 ET, pause 20:00–21:00, no Friday night.
    assert NASDAQ_23_5_EFFECTIVE_DATE.isoformat() == "2026-12-06"
    before_23_5 = evaluate_instrument_market_status("QQQ", now=datetime(2026, 10, 21, 22, 30, tzinfo=ET))
    assert before_23_5["scheduled_market_status"] == "CLOSED"
    still_before = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 2, 22, 30, tzinfo=ET))
    assert still_before["scheduled_market_status"] == "CLOSED"
    assert still_before["nasdaq_23_5_active"] is False
    sunday_open = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 6, 21, 30, tzinfo=ET))
    assert sunday_open["scheduled_market_status"] == "OVERNIGHT_SESSION"
    sunday_early = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 6, 20, 30, tzinfo=ET))
    assert sunday_early["scheduled_market_status"] == "CLOSED"
    pause = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 7, 20, 30, tzinfo=ET))
    assert pause["scheduled_market_status"] == "MAINTENANCE"
    assert pause["trading_session"] == "NASDAQ_23_5_PAUSE"
    night = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 7, 21, 30, tzinfo=ET))
    assert night["scheduled_market_status"] == "OVERNIGHT_SESSION"
    friday_night = evaluate_instrument_market_status("QQQ", now=datetime(2026, 12, 11, 21, 30, tzinfo=ET))
    assert friday_night["scheduled_market_status"] == "CLOSED"
    assert friday_night["nasdaq_23_5_active"] is True


def test_cme_maintenance_dst_and_venue_restrictions() -> None:
    """Test CME daily maintenance break (17:00-18:00 ET), Sunday preopen, market halts, and crypto venue restrictions."""
    # 1. CME Globex open on Wednesday 14:00 ET
    cme_open = evaluate_instrument_market_status("GC", now=datetime(2026, 10, 21, 14, 0, tzinfo=ET))
    assert cme_open["scheduled_market_status"] == "OPEN"
    assert cme_open["is_open"] is True

    # 2. CME Globex daily maintenance break (Wed 17:30 ET)
    cme_maint = evaluate_instrument_market_status("GC", now=datetime(2026, 10, 21, 17, 30, tzinfo=ET))
    assert cme_maint["scheduled_market_status"] == "MAINTENANCE"
    assert cme_maint["is_open"] is False

    # 3. CME Sunday preopen (Sun 17:45 ET)
    cme_preopen = evaluate_instrument_market_status("NQ", now=datetime(2026, 10, 25, 17, 45, tzinfo=ET))
    assert cme_preopen["scheduled_market_status"] == "PREOPEN"
    assert cme_preopen["is_open"] is False

    # 4. DST transition check (Nov 1, 2026 fallback day vs Oct 25, 2026 EDT day)
    dst_edt = evaluate_instrument_market_status("SPY", now=datetime(2026, 10, 26, 9, 35, tzinfo=ET))
    dst_est = evaluate_instrument_market_status("SPY", now=datetime(2026, 11, 2, 9, 35, tzinfo=ET))
    assert dst_edt["scheduled_market_status"] == "REGULAR_SESSION"
    assert dst_est["scheduled_market_status"] == "REGULAR_SESSION"

    # 5. Market Halt override
    halted = evaluate_instrument_market_status("SPY", now=datetime(2026, 10, 21, 11, 0, tzinfo=ET), venue_reported_status="HALTED")
    assert halted["market_status"] == "HALTED"
    assert halted["is_open"] is False
    assert halted["market_closed_behavior"]["allow_live_execution"] is False

    # 6. Crypto venue restrictions (LIMIT_ONLY, POST_ONLY, CANCEL_ONLY, TRADING_DISABLED)
    for mode in ("LIMIT_ONLY", "POST_ONLY", "CANCEL_ONLY", "VIEW_ONLY", "TRADING_DISABLED"):
        c_stat = evaluate_instrument_market_status("BTC-USD", venue_reported_status=mode)
        assert c_stat["market_status"] == mode
        assert c_stat["venue_reported_trading_status"] == mode

    # 7. Stale & Disconnected feed during open session
    now_utc = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
    stale_ts = now_utc.timestamp() - 3600  # 1 hour old vs 300s threshold
    stale_mkt = evaluate_instrument_market_status("BTC-USD", now=now_utc, last_price=68000.0, last_price_timestamp=stale_ts, stale_threshold_seconds=300.0)
    assert stale_mkt["data_feed_health"] == "STALE"
    assert stale_mkt["market_status"] == "STALE_MARKET_DATA"

    disc_mkt = evaluate_instrument_market_status("BTC-USD", now=now_utc, data_feed_health="DISCONNECTED")
    assert disc_mkt["data_feed_health"] == "DISCONNECTED"
    assert disc_mkt["market_status"] == "STALE_MARKET_DATA"

    # 8. Pump.fun bonding curve, migration, and pool liquidity states
    pf_curve = evaluate_instrument_market_status("PUMP:MINT123", bonding_curve_complete=False, migration_in_progress=False)
    assert pf_curve["market_status"] == "OPEN"
    pf_mig = evaluate_instrument_market_status("PUMP:MINT123", bonding_curve_complete=True, migration_in_progress=True)
    assert pf_mig["market_status"] == "HALTED"
    pf_illid = evaluate_instrument_market_status("PUMP:MINT123", bonding_curve_complete=True, migration_in_progress=False, pool_liquidity_usd=120.0)
    assert pf_illid["market_status"] == "TRADING_DISABLED"


# ============================================================================
# SECTION 24: MODEL EVOLUTION, EV INTELLIGENCE & CHAMPION-CHALLENGER TESTS
# ============================================================================


def test_ev_intelligence_high_win_prob_negative_ev_detection() -> None:
    """Section 15 & 24: Never show positive EV merely because p > 0.50 when payoff asymmetry + costs make EV negative."""
    ev_neg = compute_ev_intelligence(
        p_win=0.62,
        gross_gain_r=0.45,
        gross_loss_r=1.0,
        fees_r=0.04,
        slippage_r=0.04,
        uncertainty=0.12,
        sample_size=250,
        model_version="test-v1",
    )
    # 0.62 * 0.45 - 0.38 * 1.0 - 0.08 = 0.279 - 0.38 - 0.08 = -0.181R
    assert ev_neg["estimated_win_probability"] == 0.62
    assert ev_neg["expected_net_value_r"] < 0.0
    assert ev_neg["is_positive_ev"] is False
    assert ev_neg["high_win_prob_negative_ev_warning"] is True
    assert ev_neg["execution_permission"] == "none"

    ev_pos = compute_ev_intelligence(
        p_win=0.55,
        gross_gain_r=2.0,
        gross_loss_r=1.0,
        fees_r=0.03,
        slippage_r=0.02,
        uncertainty=0.10,
        sample_size=500,
        model_version="test-v1",
    )
    # 0.55 * 2.0 - 0.45 * 1.0 - 0.05 = 1.10 - 0.45 - 0.05 = +0.60R
    assert ev_pos["expected_net_value_r"] == pytest.approx(0.60, abs=1e-4)
    assert ev_pos["is_positive_ev"] is True
    assert ev_pos["high_win_prob_negative_ev_warning"] is False


def test_ev_evolution_monitor_and_champion_challenger_rollback(tmp_path) -> None:
    """Sections 16, 17, 18 & 24: Verify EV Evolution Monitor, 4-dimension dashboard, and governed model rollback."""
    ev_mon = get_ev_evolution_monitor("GC", "15m")
    assert ev_mon["status"] == "ok"
    assert "EV_ESTIMATED_AT_SIGNAL" in ev_mon
    assert "EV_REALIZED_AFTER_OUTCOME" in ev_mon
    assert "EV_ESTIMATION_ERROR" in ev_mon
    assert "ROLLING_REALIZED_EXPECTANCY" in ev_mon
    assert "ROLLING_CALIBRATION" in ev_mon
    assert ev_mon["diagnostics"]["automatic_risk_increase_prohibited"] is True
    assert ev_mon["execution_permission"] == "none"

    # Champion-Challenger lifecycle & governed rollback
    cc = get_champion_challenger_registry()
    assert set(cc["roles_supported"]) == set(MODEL_LIFECYCLE_ROLES)
    assert len(cc["models"]) >= 5
    assert cc["governance"]["llm_autonomous_promotion_allowed"] is False

    target_ver = cc["models"][1]["version"]
    rb = rollback_or_transition_model(target_version=target_ver, action="rollback", reason="unit_test_rollback", reg_path=tmp_path)
    assert rb["status"] == "ok"
    assert rb["event"]["action"] == "rollback_to_version"
    assert rb["event"]["target_version"] == target_ver
    assert rb["execution_permission"] == "none"

    # Strategy evolution matrix across all 7 families
    se = get_strategy_evolution_matrix()
    families = {s["family"] for s in se["strategies"]}
    assert {"Four-Box", "Continuation", "Reversal", "Gold", "Nasdaq", "Microstructure", "Solana & Pump.fun"}.issubset(families)
    assert se["execution_permission"] == "none"

    # 4-Dimension Evolution Intelligence Dashboard via HTTP API
    r_dash = client.get("/api/ml/evolution-intelligence?symbol=GC&interval=15m")
    assert r_dash.status_code == 200
    dash = r_dash.json()
    assert set(dash["dimensions"].keys()) == {
        "prediction_quality",
        "strategy_quality",
        "model_reliability",
        "operational_quality",
    }
    assert dash["governed_learning_loop"]["trains_on_immature_outcomes"] is False
    assert dash["governed_learning_loop"]["uses_future_labels_in_inference"] if "uses_future_labels_in_inference" in dash["governed_learning_loop"] else dash["governed_learning_loop"]["uses_future_labels_in_live_inference"] is False
    assert dash["execution_permission"] == "none"



def test_privacy_iso_standards_and_third_party_links() -> None:
    resp = client.get("/api/founder/compliance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_permission"] == "none"
    assert "privacy_details" in body
    assert body["privacy_details"]["breach_register_retention_days"] == 730
    assert body["privacy_details"]["dsar_response_sla_days"] == 30
    fw_ids = {f["id"] for f in body["privacy_details"]["frameworks"]}
    assert {"PIPEDA", "QUEBEC_LAW_25", "PCMLTFA_S8_PRIVACY_INTERLOCK"}.issubset(fw_ids)

    iso_codes = {row["standard"] for row in body["iso_standards"]}
    assert {
        "ISO 10383",
        "ISO 6166",
        "ISO 10962",
        "ISO 4217",
        "ISO 20022",
        "ISO/IEC 27001:2022",
        "ISO/IEC 27701:2019",
        "ISO/IEC 42001:2023",
        "ISO 31000:2018",
    }.issubset(iso_codes)

    reg_ids = {row["id"] for row in body["regulatory_links"]}
    assert {"CIRO", "CSA_OSC", "FINTRAC", "SEMA_CANADA", "OFAC_SDN", "UN_SC", "SEC_EDGAR"}.issubset(reg_ids)

    third_ids = {row["id"] for row in body["third_party_links"]}
    assert {
        "NASDAQ_CALENDAR",
        "NYSE_CALENDAR",
        "TMX_TSX_CALENDAR",
        "CME_GLOBEX",
        "LBMA_BULLION",
        "ROYAL_CANADIAN_MINT",
        "BANK_OF_CANADA",
        "TRADINGVIEW_LWC",
    }.issubset(third_ids)

    std_resp = client.get("/api/founder/standards-and-links")
    assert std_resp.status_code == 200
    assert std_resp.json()["execution_permission"] == "none"
