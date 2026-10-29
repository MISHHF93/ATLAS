from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from atlas.multi_agent.config import MultiAgentConfig
from atlas.multi_agent.contracts import (
    AnalystReport,
    EvidenceReference,
    EvidenceSnapshot,
    MacroEvent,
    NewsItem,
    PortfolioReview,
    ResearchDecision,
    RunRequest,
    TradeProposal,
)
from atlas.multi_agent.debate import run_debate
from atlas.multi_agent.deterministic import gate
from atlas.multi_agent.evidence import EvidenceDependencies
from atlas.multi_agent.reconciliation import reconcile
from atlas.multi_agent.service import MultiAgentService

AS_OF = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)


@dataclass
class RawBar:
    event_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class FakeFeed:
    def __init__(self) -> None:
        self.instruments: dict = {}
        tf = 900
        daily = 86400
        self._bars: dict[tuple[str, str], list[RawBar]] = {}
        self._bars[("BTCUSDT", "15m")] = self._series(AS_OF - timedelta(minutes=15 * 220), tf, 220, 50000.0, 20.0)
        self._bars[("BTCUSDT", "1d")] = self._series(AS_OF - timedelta(days=260), daily, 260, 42000.0, 45.0)
        self._bars[("SPY", "15m")] = self._series(AS_OF - timedelta(minutes=15 * 220), tf, 220, 550.0, 0.15)
        self._bars[("SPY", "1d")] = self._series(AS_OF - timedelta(days=260), daily, 260, 480.0, 0.4)

    @staticmethod
    def _series(start: datetime, duration: int, count: int, base: float, step: float) -> list[RawBar]:
        out: list[RawBar] = []
        prev = base
        for i in range(count):
            ts = int(start.timestamp()) + i * duration
            close = base + i * step
            high = max(prev, close) + step * 0.6
            low = min(prev, close) - step * 0.6
            out.append(RawBar(ts, prev, high, low, close, 1000.0 + i * 3.0))
            prev = close
        return out

    def bars(self, inst: str, iv: str):
        return list(self._bars.get((inst.upper(), iv), []))


def _news() -> list[NewsItem]:
    return [
        NewsItem(source="fixture-news", published_at=AS_OF - timedelta(hours=1),
                 text="Record profit growth and strong demand support the outlook.", category="news"),
        NewsItem(source="fixture-news", published_at=AS_OF + timedelta(hours=1),
                 text="FUTURE ITEM MUST NOT BE USED", category="news"),
    ]


def _macro() -> list[MacroEvent]:
    return [
        MacroEvent(name="US CPI", scheduled_at=AS_OF - timedelta(hours=2), actual=3.4, consensus=3.0),
        MacroEvent(name="US FOMC", scheduled_at=AS_OF + timedelta(hours=2), actual=5.5, consensus=5.25),
    ]


def _deps() -> EvidenceDependencies:
    def strategy(_inst, _bars, _duration, _as_of):
        return [{
            "candidate_id": "cand-1", "detector": "fixture_breakout", "direction": "long",
            "entry_reference": 54000.0, "proposed_stop": 53500.0, "proposed_target": 55200.0,
        }]

    def ml(_inst, _tf, _feed, _as_of):
        return [{"model_version": "fixture-v1", "probability_up": 0.62,
                 "expected_value_r": 0.3, "calibration_status": "calibrated"}]

    return EvidenceDependencies(feed=FakeFeed(), strategy_candidates=strategy, ml_predictions=ml,
                                fundamentals=lambda _ticker, _as_of: {"status": "unavailable", "periods": []})


def _service(tmp_path, **overrides) -> MultiAgentService:
    cfg = MultiAgentConfig(
        root_dir=tmp_path / "multi_agent",
        debate_rounds=2,
        allow_network_fundamentals=False,
        **overrides,
    )
    return MultiAgentService(cfg, dependencies=_deps())


def _request(**overrides) -> RunRequest:
    base = dict(
        instrument_id="BTCUSDT",
        timeframe="15m",
        as_of=AS_OF,
        debate_rounds=2,
        notional_usd=1000.0,
        news=_news(),
        macro_events=_macro(),
    )
    base.update(overrides)
    return RunRequest(**base)


def test_run_completes_with_audit_and_advisory_permission(tmp_path):
    svc = _service(tmp_path)
    state = svc.start(_request())

    assert state.status == "completed"
    assert state.snapshot is not None and state.snapshot.point_in_time is True
    assert len(state.analyst_reports) >= 4
    assert state.reconciliation is not None
    assert state.debate is not None and state.debate.rounds_completed <= 2
    assert state.research_decision is not None
    assert state.trade_proposal is not None
    assert len(state.risk_reviews) == 3
    assert state.portfolio_review is not None
    assert state.deterministic_decision is not None
    assert state.deterministic_decision.submitted is False
    assert state.original_decision_hash

    assert all(r.execution_permission == "none" for r in state.analyst_reports)
    assert all(r.execution_permission == "none" for r in state.risk_reviews)
    assert "execution_permission\": \"none" in state.model_dump_json() or state.execution_permission == "none"

    verification = svc.audit_verify(state.run_id)
    assert verification["valid"] is True
    assert verification["records"] >= 8
    assert [r.run_id for r in svc.list_runs()] == [state.run_id]


def test_point_in_time_news_and_macro_exclude_future_items(tmp_path):
    svc = _service(tmp_path)
    state = svc.start(_request())

    assert state.snapshot is not None
    assert [n.text for n in state.snapshot.news_items] == ["Record profit growth and strong demand support the outlook."]
    assert [m.name for m in state.snapshot.macro_events] == ["US CPI"]
    for report in state.analyst_reports:
        for ref in report.supporting_evidence + report.contradicting_evidence:
            assert ref.available_at <= state.snapshot.as_of


def test_debate_is_bounded_and_keeps_disagreement(tmp_path):
    svc = _service(tmp_path)
    state = svc.start(_request())
    assert state.snapshot is not None
    assert state.research_decision is not None

    reports = [
        AnalystReport(run_id="r", analyst_type="technical", instrument_id="BTCUSDT", as_of=AS_OF,
                      stance="bullish", confidence_label="high", thesis="Uptrend and positive momentum.",
                      metrics={"score": 20.0}),
        AnalystReport(run_id="r", analyst_type="fundamentals", instrument_id="BTCUSDT", as_of=AS_OF,
                      stance="bearish", confidence_label="medium", thesis="Cash flow and margins deteriorated.",
                      metrics={"score": -12.0}),
    ]
    rec = reconcile(reports, state.snapshot)
    debate = run_debate(reports, rec, state.snapshot, rounds_max=3)
    assert debate.rounds_max == 3
    assert debate.rounds_completed <= 3
    assert debate.net_score != 0
    assert rec.insufficient_evidence is False
    assert debate.bull_evidence_ids == [] or isinstance(debate.bull_evidence_ids, list)


class _Preview:
    compliance_passed = True
    violations: tuple[str, ...] = ()


class _FakeControl:
    def __init__(self) -> None:
        self.requests = []
        self.submit_called = False

    def preview_order(self, request, *, now=None, intake_violations=()):
        self.requests.append((request, now))
        return _Preview()

    def submit_order(self, *_a, **_k):
        self.submit_called = True
        raise AssertionError("multi-agent research must never submit orders")


def test_deterministic_gate_previews_but_never_submits():
    engine = _FakeControl()
    proposal = TradeProposal(
        run_id="r", instrument_id="BTCUSDT", action="BUY_CANDIDATE", side="buy",
        notional_usd=1000.0, stop_distance_bps=120.0, entry_price=50000.0,
        reward_risk=2.0, max_holding_horizon="intraday",
    )
    decision = ResearchDecision(outcome="BULLISH_CASE_STRONGER", thesis="bull", confidence_label="medium")
    portfolio = PortfolioReview(outcome="RECOMMEND_FOR_RISK_REVIEW")
    result = gate(proposal, decision, portfolio, track="competition",
                  evaluation_time=AS_OF, control_engine=engine)
    assert result.outcome == "PAPER_REVIEW_AUTHORIZED"
    assert result.authorized is True
    assert result.submitted is False
    assert len(engine.requests) == 1
    assert engine.submit_called is False
    assert engine.requests[0][0].instrument_id == "BTCUSDT"

    missing_stop = proposal.model_copy(update={"stop_distance_bps": None})
    result2 = gate(missing_stop, decision, portfolio, track="competition",
                   evaluation_time=AS_OF, control_engine=engine)
    assert result2.outcome == "REJECTED"
    assert result2.authorized is False
    assert len(engine.requests) == 1


def test_cancel_then_resume_reaches_completion(tmp_path):
    svc = _service(tmp_path)
    request = _request(run_id="cancel-resume")
    svc.store.request_cancel("cancel-resume")
    state = svc.start(request)
    assert state.status == "cancelled"

    resumed = svc.resume("cancel-resume")
    assert resumed is not None
    assert resumed.status == "completed"
    assert resumed.deterministic_decision is not None
    assert any(e.node == "complete" for e in resumed.node_history)


def test_reflection_does_not_mutate_decision_hash(tmp_path):
    svc = _service(tmp_path)
    state = svc.start(_request())
    original_hash = state.original_decision_hash
    assert state.snapshot is not None and state.snapshot.last_close

    record = svc.reflect(state.run_id, outcome_price=state.snapshot.last_close * 1.04,
                         benchmark_return=0.01)
    assert record.original_decision_hash == original_hash
    assert record.realized_return is not None
    assert record.predicted_direction in ("up", "down", "none")
    assert svc.get(state.run_id).original_decision_hash == original_hash
    assert svc.evolution().reflected_runs == 1


def test_contracts_strip_any_execution_permission():
    report = AnalystReport(
        run_id="r", analyst_type="technical", instrument_id="X", as_of=AS_OF,
        thesis="Thesis.", execution_permission="authorized",
    )
    assert report.execution_permission == "none"
    proposal = TradeProposal(run_id="r", instrument_id="X", action="HOLD",
                             execution_permission="execute")
    assert proposal.execution_permission == "none"


def test_missing_evidence_abstains_without_fabrication(tmp_path):
    cfg = MultiAgentConfig(root_dir=tmp_path / "no_data", allow_network_fundamentals=False)
    empty_feed = FakeFeed()
    empty_feed._bars = {}
    svc = MultiAgentService(cfg, dependencies=EvidenceDependencies(feed=empty_feed))
    state = svc.start(RunRequest(instrument_id="NOPE", timeframe="15m", as_of=AS_OF))
    assert state.status == "completed"
    assert state.research_decision is not None
    assert state.research_decision.outcome == "INSUFFICIENT_EVIDENCE"
    assert state.deterministic_decision is not None
    assert state.deterministic_decision.outcome == "NOT_APPLICABLE"
    assert "no_confirmed_intraday_bars_at_as_of" in state.snapshot.missing_data


def test_http_surface_is_advisory_and_has_no_submit_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import atlas.api.multi_agent_api as api_module
    from atlas.api.app import app

    svc = _service(tmp_path)
    monkeypatch.setattr(api_module, "get_service", lambda: svc)
    client = TestClient(app)

    direct = client.get("/api/multi-agent/status")
    assert direct.status_code == 200
    assert direct.json()["execution_permission"] == "none"

    aliased = client.get("/api/ai/multi-agent/status")
    assert aliased.status_code == 200
    assert aliased.json()["execution_permission"] == "none"

    paths = [getattr(route, "path", "") for route in api_module.router.routes]
    assert not any(token in p for p in paths for token in ("submit", "execute", "/orders"))

def test_llm_factory_stays_off_without_opt_in_or_key(monkeypatch):
    from atlas.multi_agent.llm import build_llm

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert build_llm(MultiAgentConfig(enable_llm=True)) is None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert build_llm(MultiAgentConfig(enable_llm=False)) is None

def test_audit_chain_detects_tampering(tmp_path):
    import json

    svc = _service(tmp_path)
    state = svc.start(_request())
    path = svc.audit.path_for(state.run_id)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    rows[0]["payload"]["instrument_id"] = "TAMPERED"
    path.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    verification = svc.audit_verify(state.run_id)
    assert verification["valid"] is False
    assert verification["reason"] in {"hash_mismatch", "prev_hash_mismatch"}

def test_portfolio_review_preserves_dissent_and_rejects_multiple_objectors():
    from atlas.multi_agent.contracts import RiskReview
    from atlas.multi_agent.portfolio import review

    proposal = TradeProposal(
        run_id="r", instrument_id="BTCUSDT", action="BUY_CANDIDATE", side="buy",
        notional_usd=1000.0, stop_distance_bps=120.0, reward_risk=2.0,
    )
    conservative = RiskReview(perspective="conservative", verdict="objects", concerns=["missing evidence"], severity="high")
    aggressive = RiskReview(perspective="aggressive", verdict="supports_candidate", severity="low")
    neutral = RiskReview(perspective="neutral", verdict="concerns_raised", concerns=["mixed"], severity="medium")
    one_dissent = review(proposal, None, [conservative, aggressive, neutral])
    assert one_dissent.outcome == "RECOMMEND_FOR_RISK_REVIEW"
    assert "deterministic control plane enforces account limits at preview time" in one_dissent.constraints

    second = RiskReview(perspective="aggressive", verdict="objects", concerns=["unbounded risk"], severity="high")
    rejected = review(proposal, None, [conservative, second, neutral])
    assert rejected.outcome == "REJECT_RESEARCH_PROPOSAL"
    assert "multiple independent risk perspectives objected" in rejected.constraints