"""Comprehensive verification suite for the ATLAS Internet Research & Full Implementation Directive:
- Version-pinned Protocol & Adapter Manifest + Drift Detection (src/atlas/integrations/protocol_manifest.py)
- Massive.com (formerly Polygon.io) dual-env adapter & Solana JSON-RPC / WebSocket subscriptions
- Extended Institutional Strategy Detectors (Failed Breakout Reversal, Nasdaq IB-30 Opening Drive,
  Fair-Price Session VWAP Anchor, Scheduled News Post-Release Causal Box, Whale Order-Flow, Prop-Firm Risk Pacing)
- Enhanced Four-Box Event Box activation with causal EconomicEvent items
- Complete 14-Stage ATLAS Unified Intelligence Loop & /api/ai/protocol-manifest + /api/ai/intelligence-loop
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.ai.intel.fourbox import scan as scan_fourbox
from atlas.ai.intel.unified_loop import STAGE_NAMES, _default_bars_for_instrument, _default_events_for_instrument, run_unified_intelligence_loop
from atlas.api.app import app
from atlas.feeds.providers.polygon import PolygonAdapter
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.events import EconomicEvent
from atlas.features.price_action.extended_strategies import (
    ExtendedStrategyEngine,
    FailedBreakoutReversalDetector,
    FairPriceSessionAnchorDetector,
    NasdaqOpeningSessionDetector,
    PropFirmCompetitionAdvisor,
    PropFirmCompetitionState,
    ScheduledNewsPostReleaseDetector,
    WhaleOrderFlowDetector,
)
from atlas.features.price_action.features import batch_features
from atlas.features.price_action.strategies import StrategyRegistry
from atlas.integrations.protocol_manifest import PROTOCOL_SPECS, detect_protocol_drift, installed_ml_analytics_stack, verify_protocol_compatibility
from atlas.integrations.registry import status as integrations_status
from atlas.pump.engine import MINT_ALPHA_CURVE
from atlas.pump.indexing import SolanaRPCIndexer


def test_protocol_manifest_compatibility_and_drift():
    compat = verify_protocol_compatibility()
    assert compat["all_compatible"] is True
    assert compat["adapter_count"] == len(PROTOCOL_SPECS) >= 10
    assert compat["execution_permission"] == "none"

    stack = installed_ml_analytics_stack()
    assert stack["scikit_learn"] is not None
    assert stack["xgboost"] is not None
    assert stack["lightgbm"] is not None
    assert stack["duckdb"] is not None

    drift = detect_protocol_drift()
    assert drift["drift_detected"] is False
    assert drift["issues"] == []
    assert drift["execution_permission"] == "none"


def test_massive_polygon_dual_key_and_solana_rpc_registry():
    # Verify PolygonAdapter accepts MASSIVE_API_KEY when POLYGON_API_KEY is absent
    calls = []

    def fake_transport(url, headers):
        calls.append((url, dict(headers)))
        return 200, {}, b'{"results":[{"t":1761696000000,"o":100.0,"h":102.0,"l":99.0,"c":101.0,"v":5000}]}'

    import datetime as _dt
    from zoneinfo import ZoneInfo
    from atlas.feeds.core import RateLimiter
    now = int(_dt.datetime(2026, 10, 29, 17, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
    adapter = PolygonAdapter(
        transport=fake_transport,
        env={"MASSIVE_API_KEY": "massive_test_key_123", "MASSIVE_BASE_URL": "https://api.massive.com"},
        clock=lambda: now, sleep=lambda s: None, limiter=RateLimiter(1000, sleep=lambda s: None),
    )
    assert adapter.health().enabled is True
    bars = adapter.history("SPY", "1d", now - 5 * 86400, now)
    assert len(bars) == 1
    url, headers = calls[0]
    assert "https://api.massive.com/v2/aggs/ticker/SPY" in url
    # The key travels as a Bearer header, never in the URL (so it cannot leak into logs).
    assert headers["Authorization"] == "Bearer massive_test_key_123"
    assert "massive_test_key_123" not in url and "apiKey" not in url

    # Verify integrations.registry.status recognizes MASSIVE_API_KEY for polygon and includes solana_rpc
    rep = integrations_status(env={"MASSIVE_API_KEY": "massive_test_key_123"}, probe=False)
    by_id = {s["id"]: s for s in rep["services"]}
    assert by_id["polygon"]["configured"] is True
    assert "solana_rpc" in by_id
    assert by_id["solana_rpc"]["configured"] is True


def test_solana_rpc_indexer_priority_fees_simulation_and_ws_payloads():
    indexer = SolanaRPCIndexer()
    fees = indexer.fetch_recent_prioritization_fees([MINT_ALPHA_CURVE])
    assert fees["ok"] is True
    assert fees["median_micro_lamports"] > 0
    assert fees["p75_micro_lamports"] >= fees["median_micro_lamports"]
    assert fees["execution_permission"] == "none"

    sim = indexer.simulate_transaction_rpc("AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAED")
    assert sim["ok"] is True
    assert sim["err"] is None
    assert sim["units_consumed"] > 0

    acct = indexer.fetch_account_info(MINT_ALPHA_CURVE)
    assert acct["ok"] is True

    ws = indexer.build_ws_subscription_payloads([MINT_ALPHA_CURVE])
    assert ws["logs_subscribe"]["method"] == "logsSubscribe"
    assert len(ws["account_subscribes"]) == 1
    assert ws["account_subscribes"][0]["method"] == "accountSubscribe"
    assert ws["execution_permission"] == "none"


def test_extended_strategy_detectors_and_scoping(tmp_path):
    # StrategyRegistry includes new detectors, all disabled by default with execution_permission == "none"
    reg = StrategyRegistry(tmp_path / "strat.json")
    for sid in (
        "failed_breakout_reversal",
        "nasdaq_opening_drive",
        "fair_price_session_anchor",
        "scheduled_news_post_release",
        "whale_orderflow_research",
    ):
        assert reg.enabled(sid) is False
        reg.set(sid, True)
        assert reg.enabled(sid) is True

    # NasdaqOpeningSessionDetector is strictly scoped to Nasdaq instruments (NQ, QQQ, etc.)
    nq_bars = _default_bars_for_instrument("NQ")
    gc_bars = _default_bars_for_instrument("GC")
    nq_det = NasdaqOpeningSessionDetector("NQ", 300)
    gc_nq_det = NasdaqOpeningSessionDetector("GC", 300)
    for b, c in zip(nq_bars, batch_features(nq_bars, 14)):
        nq_det.step(b, c)
    for b, c in zip(gc_bars, batch_features(gc_bars, 14)):
        gc_nq_det.step(b, c)
    assert len(nq_det.zones) >= 1
    assert len(nq_det.candidates) >= 1
    assert gc_nq_det.zones == [] and gc_nq_det.candidates == []

    # ExtendedStrategyEngine runs all causal extended detectors over NQ
    events = _default_events_for_instrument("NQ", nq_bars)
    ext = ExtendedStrategyEngine("NQ", 300, events=events)
    res = ext.run_batch(nq_bars)
    assert res["execution_permission"] == "none"
    det_names = {c["detector"] for c in res["candidates"]}
    assert "nasdaq_opening_drive" in det_names
    assert "scheduled_news_post_release" in det_names
    assert "whale_orderflow_research" in det_names
    assert all(c["execution_permission"] == "none" for c in res["candidates"])


def test_scheduled_news_detector_is_strictly_causal_and_fourbox_event_activates():
    bars = _default_bars_for_instrument("GC")
    events = _default_events_for_instrument("GC", bars)
    det = ScheduledNewsPostReleaseDetector("GC", 300, events=events)
    ctxs = batch_features(bars, 14)

    # Before release bar (bars[0..4]), no event zone or candidate may exist
    for b, c in zip(bars[:5], ctxs[:5]):
        det.step(b, c)
    assert det.zones == [] and det.candidates == []

    # Step through remaining bars -> release box locks on bar[5] and breakout emits on bar[6]
    for b, c in zip(bars[5:], ctxs[5:]):
        det.step(b, c)
    assert len(det.zones) == 1
    assert len(det.candidates) == 1
    assert det.candidates[0].features["raw_surprise"] is not None

    # Four-Box without events keeps Event box disabled; with events activates Event box causally
    fb_default = scan_fourbox("GC", bars)
    assert fb_default["boxes"][3]["status"] == "disabled"
    fb_with_events = scan_fourbox("GC", bars, events=events)
    assert fb_with_events["boxes"][3]["status"] == "enabled"
    assert fb_with_events["boxes"][3]["n_zones"] >= 1
    assert fb_with_events["boxes"][3]["n_candidates"] >= 1


def test_prop_firm_competition_advisor_never_loosens_risk():
    advisor = PropFirmCompetitionAdvisor()
    normal = advisor.evaluate(PropFirmCompetitionState())
    assert 0.0 < normal["size_scalar"] <= 1.0
    assert normal["loosens_risk_limits"] is False
    assert normal["execution_permission"] == "none"

    # Critical trailing drawdown halts new entries (size_scalar == 0.0)
    critical = advisor.evaluate(
        PropFirmCompetitionState(
            account_equity_usd=97_200.0,
            high_water_mark_usd=100_000.0,
            max_trailing_drawdown_usd=3_000.0,
        )
    )
    assert critical["size_scalar"] == 0.0
    assert critical["halt_new_entries"] is True


def test_14_stage_unified_intelligence_loop_and_http_endpoints():
    loop_res = run_unified_intelligence_loop(instruments=("GC", "NQ", "BTCUSDT"), execute_top_paper=True)
    assert loop_res["status"] == "ok"
    assert loop_res["paper_only"] is True
    assert loop_res["execution_permission"] == "none"
    assert loop_res["stage_count"] == 14
    assert tuple(loop_res["stage_names"]) == STAGE_NAMES
    for stage_name in STAGE_NAMES:
        st = loop_res["stages"][stage_name]
        assert st["status"] == "ok"
        assert st["execution_permission"] == "none"

    assert loop_res["summary"]["multi_asset_candidates"] > 0
    assert loop_res["summary"]["solana_signals"] > 0
    assert loop_res["summary"]["ranked_opportunities"] > 0
    assert loop_res["summary"]["approved_opportunities"] > 0

    # Test HTTP endpoints via FastAPI TestClient
    client = TestClient(app)
    r_manifest = client.get("/api/ai/protocol-manifest")
    assert r_manifest.status_code == 200
    j_manifest = r_manifest.json()
    assert j_manifest["compatibility"]["all_compatible"] is True
    assert j_manifest["drift"]["drift_detected"] is False
    assert j_manifest["execution_permission"] == "none"

    r_loop = client.post("/api/ai/intelligence-loop", json={"instruments": ["GC", "NQ"], "execute_top_paper": True})
    assert r_loop.status_code == 200
    j_loop = r_loop.json()
    assert j_loop["stage_count"] == 14
    assert j_loop["execution_permission"] == "none"
