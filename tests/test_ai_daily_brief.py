"""Tests for the ATLAS AI Daily Investment & ML Research Brief (``atlas.ai.daily_brief``)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.ai.daily_brief import build_ai_daily_investment_brief
from atlas.ai.node import component, component_status
from atlas.api.app import app


def test_daily_investment_brief_component_registered() -> None:
    comp = component("daily_investment_brief")
    status = component_status(comp)
    assert status["status"] == "ok"
    assert status["execution_permission"] == "none"
    assert "/api/ai/daily-brief" in status["api"]


def test_build_ai_daily_investment_brief_core_sections() -> None:
    brief = build_ai_daily_investment_brief(symbols=["GC", "GLD", "SPY", "BIL", "AAPL", "MSFT", "BTCUSDT"])
    assert brief["paper_only"] is True
    assert brief["execution_permission"] == "none"
    assert brief["usd_cad_rate"] > 1.0

    exec_brief = brief["executive_brief"]
    assert "Yesterday Paper Session" in exec_brief["headline"]
    assert len(exec_brief["what_we_invested_yesterday"]) > 40
    assert len(exec_brief["what_to_invest_today_and_why"]) > 40
    assert len(exec_brief["ml_and_ratings_loop_synthesis"]) > 40
    assert "NI 31-103" in exec_brief["risk_and_governance_notice"]

    yest = brief["yesterday_investments"]
    assert "total_paper_notional_usd" in yest
    assert "total_paper_pnl_usd" in yest
    assert "total_paper_pnl_cad" in yest
    assert len(yest["allocations"]) >= 3
    for alloc in yest["allocations"]:
        assert alloc["symbol"]
        assert isinstance(alloc["based_on_factors"], list)
        assert len(alloc["based_on_factors"]) >= 1

    today = brief["today_investments"]
    candidates = today["today_paper_candidates"]
    assert len(candidates) >= 3
    for cand in candidates:
        assert 1 <= cand["conviction_score"] <= 100
        assert cand["conviction_label"] in ("BUY", "WATCH", "SELL")
        assert 0.0 < cand["ml_p_up"] < 1.0
        assert isinstance(cand["ml_expected_value_r"], float)
        assert cand["execution_permission"] == "none"

    ml_loop = brief["ml_and_loop_status"]
    assert ml_loop["unified_14_stage_loop"]["stage_count"] == 14
    assert ml_loop["unified_14_stage_loop"]["all_stages_completed"] is True


def test_daily_brief_http_endpoints() -> None:
    client = TestClient(app)

    r_get = client.get("/api/ai/daily-brief?symbols=GC,SPY,AAPL,BIL")
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["execution_permission"] == "none"
    assert body["paper_only"] is True
    assert len(body["ranked_opportunities"]) == 4

    r_post = client.post(
        "/api/ai/daily-brief",
        json={"symbols": ["GC", "MSFT", "TLT"], "include_llm_narrative": False, "execute_top_paper": False},
    )
    assert r_post.status_code == 200
    post_body = r_post.json()
    assert post_body["execution_permission"] == "none"
    assert len(post_body["ranked_opportunities"]) == 3

    r_assets = client.get("/api/assets/daily-brief?symbols=GC,GLD,BIL")
    assert r_assets.status_code == 200
    assert r_assets.json()["execution_permission"] == "none"

