"""Founder workbench API (Lola port): paper only, execution_permission none, Safe stop halts only."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas.api import founder
from atlas.api.app import app
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.control.founder_track import build_founder_rulebook
from atlas.governance import EIGHT_NON_CUSTODIAL_LEDGERS, LEDGER_IMPLEMENTATIONS


@pytest.fixture()
def client():
    from atlas.risk.safe_stop import operator_reset, shared_safe_stop

    founder.service.cache_clear()
    yield TestClient(app)
    operator_reset(shared_safe_stop(), "test_teardown")
    founder.service.cache_clear()


ROUTES = ["pnl", "remaining-room", "state", "safe-stop", "approvals", "inbox", "venues", "tax", "ledgers", "compliance"]


@pytest.mark.parametrize("route", ROUTES)
def test_every_route_is_paper_only_with_no_execution_permission(client, route):
    body = client.get(f"/api/founder/{route}").json()
    assert body["execution_permission"] == "none"
    assert body["trading"] == "paper_only"


def test_founder_track_defaults_to_two_percent_daily_loss_and_prop_stays_four():
    assert build_founder_rulebook().max_daily_loss_fraction == Decimal("0.02")
    eng = ActionableControlPlaneEngine()
    assert eng.founder_rulebook.max_daily_loss_fraction == Decimal("0.02")
    assert eng.comp_rulebook.max_daily_loss_fraction == Decimal("0.04")


def test_founder_track_fails_closed_to_two_percent_without_policy(tmp_path):
    assert build_founder_rulebook(tmp_path).max_daily_loss_fraction == Decimal("0.02")


def test_rulebooks_endpoint_lists_founder_capital(client):
    body = client.get("/api/control/rulebooks").json()
    assert body["founder_capital"]["max_daily_loss_fraction"] == "0.02"
    assert body["competition"]["max_daily_loss_fraction"] == "0.04"


def test_safe_stop_engages_but_cannot_be_reset_over_http(client):
    assert client.get("/api/founder/safe-stop").json()["engaged"] is False
    r = client.post("/api/founder/safe-stop", json={"reason": "test"}).json()
    assert r["engaged"] is True and r["execution_permission"] == "none"
    assert client.post("/api/founder/safe-stop/reset").status_code == 403
    inbox = client.get("/api/founder/inbox").json()
    assert any(i["kind"] == "safe_stop" for i in inbox["items"])


def test_ledgers_cover_all_eight(client):
    body = client.get("/api/founder/ledgers").json()
    assert [r["ledger"] for r in body["ledgers"]] == list(EIGHT_NON_CUSTODIAL_LEDGERS)
    assert set(LEDGER_IMPLEMENTATIONS) == set(EIGHT_NON_CUSTODIAL_LEDGERS)
    assert body["custody"] == "non_custodial"


def test_canadian_venues_loaded(client):
    body = client.get("/api/founder/venues").json()
    assert body["available"] is True
    names = {v["venue"] for v in body["venues"]}
    assert {"ibkr", "alpaca"} <= names
    assert next(v for v in body["venues"] if v["venue"] == "alpaca")["paper_only"] is True


def test_one_safe_stop_shared_by_control_plane_and_founder(client):
    from atlas.api.app import control_engine

    client.post("/api/founder/safe-stop", json={"reason": "unify"})
    assert control_engine.get_state().kill_switch_engaged is True
    from atlas.risk.safe_stop import operator_reset, shared_safe_stop

    operator_reset(shared_safe_stop(), "t")
    eng = ActionableControlPlaneEngine(safe_stop=shared_safe_stop())  # isolated positions, shared switch
    eng.kill_switch_engaged = True
    assert client.get("/api/founder/safe-stop").json()["engaged"] is True


def test_founder_remaining_room_uses_two_percent(client):
    body = client.get("/api/founder/remaining-room").json()
    assert body["daily_loss_limit_pct"] == 2.0 and body["rulebook_id"].startswith("founder-capital")
    pnl = client.get("/api/founder/pnl").json()
    assert pnl["remaining_room"]["daily_loss_limit_pct"] == 2.0 and "day_pnl_usd" in pnl
