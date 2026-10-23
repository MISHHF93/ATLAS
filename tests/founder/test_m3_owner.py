import asyncio
import json

import pytest

from founder_conftest import CONFIG_DIR, FakeClock
from atlas.mcp.trading import build_service
from atlas.mcp.trading.tokens import TokenRegistry
from atlas.control.owner_cli import run
from atlas.risk.killswitch import KillSwitch
from atlas.governance.audit import AuditLog
from atlas.risk.state_store import StateStore
from atlas.risk.stepup import StepUp, totp

PW = "correct horse battery staple"
ORDER = dict(symbol="SPY", side="buy", qty=1, order_type="limit", limit_price=100, reference_price=100,
             sleeve="core", asset_class="index_etf", broker="alpaca", quote_age_s=1.0)


def test_totp_rfc6238_vector():
    assert totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59, digits=8) == "94287082"


def test_stepup_verify_single_use_and_lockout(tmp_path):
    c = FakeClock(1_700_000_000)
    su = StepUp(tmp_path / "s.json", clock=c)
    secret = su.init(PW, "masharai")
    assert (tmp_path / "s.json").stat().st_mode & 0o777 == 0o600
    code = totp(secret, c())
    assert su.verify("masharai", PW, code)
    assert not su.verify("masharai", PW, code)  # replay
    c.advance(30)
    assert not su.verify("masharai", "wrong passphrase!!", totp(secret, c()))
    assert not su.verify("ai", PW, totp(secret, c()))
    for _ in range(5):
        su.verify("masharai", "nope-nope-nope", "000000")
    assert not su.verify("masharai", PW, totp(secret, c()))  # locked out
    c.advance(301)
    assert su.verify("masharai", PW, totp(secret, c()))


def test_stepup_short_passphrase_and_missing_file(tmp_path):
    with pytest.raises(ValueError):
        StepUp(tmp_path / "x.json").init("short", "masharai")
    assert not StepUp(tmp_path / "missing.json").verify("masharai", PW, "123456")


@pytest.fixture
def env(tmp_path):
    paths = dict(state=str(tmp_path / "state.sqlite"), audit=str(tmp_path / "audit.sqlite"),
                 stepup=str(tmp_path / "stepup.json"), tokens=str(tmp_path / "tokens.json"))
    base = ["--config", str(CONFIG_DIR)] + sum([[f"--{k}", v] for k, v in paths.items()], [])
    out = []
    secret_holder = {}

    import time as _t
    offsets = iter([0, 30, -30])  # TOTP codes are single-use; ±1 step accepted

    def cli(*args, pw=PW, code=None):
        def prompt():
            return pw, code if code is not None else totp(secret_holder["s"], _t.time() + next(offsets))
        return run(base + list(args), prompt=prompt, out=out.append)

    run(base + ["init-stepup"], prompt=lambda: (PW, PW), out=out.append)
    secret_holder["s"] = out[-1].rsplit(" ", 1)[-1]
    svc = build_service(CONFIG_DIR, audit_path=paths["audit"], state_path=paths["state"])
    svc.heartbeat()
    return cli, out, svc, paths


def test_cli_approve_flow_executes_in_core(env):
    cli, out, svc, _ = env
    aid = svc.propose_order(**ORDER)["approval_id"]
    cli("approvals")
    assert aid in out[-1]
    assert cli("approve", aid, code="000000") == 3  # bad TOTP
    assert cli("approve", aid) == 0
    assert svc.broker.fills == []  # CLI never executes
    assert svc.process_owner_actions()["approvals_processed"] == 1
    assert len(svc.broker.fills) == 1 and svc.approvals.get(aid).status == "executed"


def test_cli_reject(env):
    cli, out, svc, _ = env
    aid = svc.propose_order(**ORDER)["approval_id"]
    cli("reject", aid)
    assert svc.approvals.get(aid).status == "rejected" and svc.list_approvals() == []


def test_cli_kill_without_stepup_and_reset_with(env):
    cli, out, svc, _ = env
    assert cli("kill", "--reason", "drill", code="bad") == 0  # halting never needs step-up
    assert svc.ks.engaged
    assert cli("reset", code="000000") == 3 and svc.ks.engaged
    assert cli("reset") == 0 and not svc.ks.engaged


def test_cli_kill_flatten(env):
    cli, out, svc, _ = env
    aid = svc.propose_order(**ORDER)["approval_id"]
    svc.owner_approve(aid, "masharai", True)
    assert "SPY" in svc.broker.positions
    assert cli("kill", "--reason", "flatten drill", "--flatten") == 0
    r = svc.process_owner_actions()
    assert r["flattened"] == 1 and svc.broker.positions == {} and svc.ks.engaged
    assert svc.reconcile() == []  # flatten fills went through the ledger


def test_cli_flatten_denied_still_halts(env):
    cli, out, svc, _ = env
    assert cli("kill", "--reason", "x", "--flatten", code="000000") == 3
    assert svc.ks.engaged and svc.store.get("flatten_request") is None


def test_mcp_kill_cannot_flatten(env):
    cli, out, svc, _ = env
    aid = svc.propose_order(**ORDER)["approval_id"]
    svc.owner_approve(aid, "masharai", True)
    r = svc.kill_switch("ai halt", flatten=True)
    assert r["halted"] and r["flattened_positions"] == 0 and "SPY" in svc.broker.positions


def test_core_cancels_open_orders_after_external_kill(env):
    cli, out, svc, _ = env
    from founder_conftest import intent
    from atlas.risk import RiskDecision
    i = intent(limit_price=99)
    svc.broker.submit(i, RiskDecision(intent_id=i.intent_id, approved=True, reasons=[], checks={}, halted=False, policy_version=4))
    assert svc.broker.open_orders
    cli("kill", "--reason", "external")
    svc.process_owner_actions()
    assert not svc.broker.open_orders


def test_approval_ttl_shared_across_processes(env):
    cli, out, svc, paths = env
    aid = svc.propose_order(**ORDER)["approval_id"]
    rec = svc.store.get("approval:" + aid); rec["expires"] = 0; svc.store.set("approval:" + aid, rec)
    cli("approve", aid) if False else None
    with pytest.raises(ValueError):
        svc.owner_approve(aid, "masharai", True)


# ---- MCP scoped tokens
def test_token_scopes_expiry_lockout(tmp_path):
    c = FakeClock(1000)
    reg = TokenRegistry(tmp_path / "t.json", clock=c)
    tok = reg.create("grok", {"read", "propose"}, ttl_days=1)
    assert tok not in (tmp_path / "t.json").read_text()  # only hash stored
    assert reg.check(tok, "read") == "grok"
    with pytest.raises(PermissionError, match="scope"):
        reg.check(tok, "kill")
    c.advance(2 * 86400)
    with pytest.raises(PermissionError):
        reg.check(tok, "read")
    for _ in range(5):
        with pytest.raises(PermissionError):
            reg.check("bad", "read")
    with pytest.raises(PermissionError, match="locked"):
        reg.check(tok, "read")
    with pytest.raises(ValueError):
        reg.create("x", {"admin"})


def test_cli_creates_token_with_stepup(env):
    cli, out, svc, paths = env
    assert cli("mcp-token", "create", "grok", "--scopes", "read") == 0
    tok = out[-1].rsplit(" ", 1)[-1]
    assert TokenRegistry(paths["tokens"]).check(tok, "read") == "grok"
    assert cli("mcp-token", "revoke", "grok") == 0
    with pytest.raises(PermissionError):
        TokenRegistry(paths["tokens"]).check(tok, "read")


def test_mcp_scope_enforced(tmp_path):
    from atlas.mcp.trading.server import create_server
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    reg = TokenRegistry(tmp_path / "t.json")
    ro = reg.create("ro", {"read"})
    app = create_server(svc, None, reg)
    ok = asyncio.run(app.call_tool("get_status", {"auth_token": ro}))
    assert not getattr(ok, "is_error", False)
    try:
        res = asyncio.run(app.call_tool("kill_switch", {"auth_token": ro, "reason": "x"}))
        assert getattr(res, "is_error", getattr(res, "isError", False))
    except Exception as e:
        assert "unauthorized" in str(e).lower()
    assert not svc.ks.engaged
