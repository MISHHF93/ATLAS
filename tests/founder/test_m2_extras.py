import base64
import subprocess
import sys
import time
from datetime import date

import pytest

from founder_conftest import FakeClock, intent, pos, state
from atlas.governance.audit import AuditLog
from atlas.control.policy import ConfigError, load_all
from atlas.risk import KillSwitch, Position
from atlas.risk.anomaly import AnomalyMonitor
from atlas.risk.fx import FxRateUnavailable, StaticFxProvider
from atlas.risk.reconcile import Ledger, reconcile
from atlas.risk.state_store import StateStore
from atlas.risk.watchdog_proc import check_once, watchdog_alive, write_core_heartbeat


def failed(d):
    return [k for k, v in d.checks.items() if not v]


# ---- persistence
def test_kill_switch_persists_across_restart(tmp_path):
    p = str(tmp_path / "s.sqlite")
    KillSwitch(AuditLog(), store=StateStore(p)).engage("x", "cli")
    ks2 = KillSwitch(AuditLog(), store=StateStore(p))
    assert ks2.engaged and ks2.reason == "x"
    ks2.reset("masharai", True, "masharai")
    assert not KillSwitch(AuditLog(), store=StateStore(p)).engaged


def test_kill_switch_unreadable_store_fails_closed():
    class Broken(StateStore):
        def get(self, *a, **k):
            raise OSError("disk")
    assert KillSwitch(AuditLog(), store=Broken()).engaged


# ---- daily session latch
def test_daily_halt_latched_until_session_roll(engine):
    engine.evaluate(intent(), state(cash=19_500, sod=20_000))
    assert engine.daily_halted
    d = engine.evaluate(intent(), state(cash=20_000, sod=20_000))  # recovered intraday
    assert "daily_loss" in failed(d)
    engine.roll_session("2099-01-02")
    assert engine.evaluate(intent(), state()).approved


# ---- FX / currency / sector / issuer
def test_fx_provider_missing_rate():
    with pytest.raises(FxRateUnavailable):
        StaticFxProvider().rate("XYZ", "CAD")


def test_unknown_currency_rejected(engine):
    assert "internal_error" in failed(engine.evaluate(intent(currency="XYZ"), state()))


def test_fx_rate_disagreement(engine):
    d = engine.evaluate(intent(currency="USD", fx_rate_to_base=1.0, asset_class="us_equity", sleeve="active"), state())
    assert "fx_rate" in failed(d)


def usd(sym, qty, px=100.0, sleeve="active", sector=None, issuer=None):
    return Position(symbol=sym, qty=qty, avg_price=px, last_price=px, sleeve=sleeve, currency="USD",
                    fx_rate_to_base=1.37, sector=sector, issuer=issuer)


def test_single_currency_cap(engine):
    ps = {f"U{i}": usd(f"U{i}", 14) for i in range(3)}  # 3*14*137 = 5754 (~29%)
    s = state(cash=20_000 - 5754, positions=ps)
    d = engine.evaluate(intent(symbol="U9", currency="USD", fx_rate_to_base=1.37, qty=10, sleeve="active", asset_class="us_equity"), s)
    assert "single_currency" in failed(d)  # +1370 => ~35.6% > 35%


def test_net_fx_cap(engine):
    eur = {f"E{i}": Position(symbol=f"E{i}", qty=13, avg_price=100, last_price=100, sleeve="active", currency="EUR", fx_rate_to_base=1.49) for i in range(3)}
    ps = {**eur, **{f"U{i}": usd(f"U{i}", 9) for i in range(2)}}  # EUR 5811 + USD 2466 = 8277
    s = state(cash=20_000 - 8277, positions=ps)
    d = engine.evaluate(intent(symbol="G1", currency="GBP", fx_rate_to_base=1.74, qty=11, sleeve="active", asset_class="us_equity"), s)
    assert "net_fx_exposure" in failed(d)  # +1914 => 10191 > 50%


def test_sector_cap(engine):
    ps = {f"T{i}": pos(f"T{i}", 19, sleeve="active") for i in range(3)}
    for p in ps.values():
        p.sector = "tech"
    d = engine.evaluate(intent(symbol="T9", qty=5, sleeve="active", asset_class="us_equity", sector="tech"), state(cash=14_300, positions=ps))
    assert "sector" in failed(d)  # 5700+500 > 6000


def test_issuer_netting_across_listings(engine):
    ps = {"SHOP.TO": Position(symbol="SHOP.TO", qty=15, avg_price=100, last_price=100, sleeve="active", issuer="CA82509L1076")}
    d = engine.evaluate(intent(symbol="SHOP", qty=6, sleeve="active", asset_class="us_equity", issuer="CA82509L1076"), state(cash=18_500, positions=ps))
    assert "max_position_pct" in failed(d)  # 1500 + 600 > 2000 across listings


def test_settled_cash(engine):
    s = state(cash=20_000)
    s = s.model_copy(update={"settled_cash_base": 50.0})
    assert "settled_cash" in failed(engine.evaluate(intent(qty=1), s))


# ---- anomalies
def test_stale_quote(engine):
    assert "stale_quote" in failed(engine.evaluate(intent(quote_age_s=11), state()))
    assert "stale_quote" in failed(engine.evaluate(intent(quote_age_s=None), state()))


def test_fill_deviation_halts():
    ks = KillSwitch(AuditLog()); m = AnomalyMonitor(ks)
    assert m.on_fill(100.4, 100) and not ks.engaged
    assert not m.on_fill(100.6, 100) and ks.engaged


def test_reject_spike_halts():
    ks = KillSwitch(AuditLog()); m = AnomalyMonitor(ks)
    m.on_broker_reject(0); m.on_broker_reject(400); m.on_broker_reject(500)
    assert not ks.engaged
    m.on_broker_reject(600)
    assert ks.engaged


def test_pnl_jump_halts():
    ks = KillSwitch(AuditLog()); m = AnomalyMonitor(ks)
    for i in range(30):
        m.on_pnl(10 if i % 2 else -10)
    assert not ks.engaged
    m.on_pnl(500)
    assert ks.engaged


# ---- reconciliation
def test_reconcile_ok_and_mismatch():
    a = AuditLog(); ks = KillSwitch(a)
    led = Ledger(cash=1000, positions={"SPY": 5})
    assert reconcile(led, {"SPY": 5}, 1000, ks, a) == [] and not ks.engaged
    assert reconcile(led, {"SPY": 4}, 1000, ks, a) and ks.engaged


def test_reconcile_cash_mismatch():
    a = AuditLog(); ks = KillSwitch(a)
    assert reconcile(Ledger(cash=1000), {}, 999, ks, a) and ks.engaged


def test_service_detects_broker_drift():
    from founder_conftest import CONFIG_DIR
    from atlas.mcp.trading import build_service
    svc = build_service(CONFIG_DIR)
    svc.broker.positions["GHOST"] = Position(symbol="GHOST", qty=1, avg_price=1, last_price=1, sleeve="core")
    assert svc.reconcile() and svc.ks.engaged


# ---- external watchdog
def test_external_watchdog_check_once():
    st = StateStore(); ks = KillSwitch(AuditLog(), store=st)
    write_core_heartbeat(st, now=100)
    assert check_once(st, ks, 15, now=110) and not ks.engaged
    assert watchdog_alive(st, 15, now=112)
    assert not check_once(st, ks, 15, now=200) and ks.engaged


def test_external_watchdog_missing_heartbeat():
    st = StateStore(); ks = KillSwitch(AuditLog(), store=st)
    assert not check_once(st, ks, 15) and ks.engaged


def test_engine_halts_if_external_watchdog_dead(cfg, audit, ks, clock):
    from atlas.risk import RiskEngine, Watchdog
    wd = Watchdog(5, 3, ks, clock=clock); wd.heartbeat()
    e = RiskEngine(cfg.risk, cfg.brokers, audit, ks, wd, clock=clock, external_watchdog=lambda: False)
    d = e.evaluate(intent(), state())
    assert "external_watchdog" in failed(d) and ks.engaged


def test_watchdog_subprocess_engages_shared_kill_switch(tmp_path):
    p = str(tmp_path / "state.sqlite")
    st = StateStore(p)
    write_core_heartbeat(st, now=time.time() - 100)  # stale
    subprocess.run([sys.executable, "-m", "atlas.risk.watchdog_proc", "--state", p, "--interval", "0.05",
                    "--missed", "2", "--iterations", "2"], check=True, timeout=30)
    assert KillSwitch(AuditLog(), store=StateStore(p)).engaged
    assert StateStore(p).get("watchdog_heartbeat") is not None


# ---- policy signature
def test_pin_mismatch(cfg_dir):
    p = cfg_dir / "risk_policy.yaml"
    p.write_text(p.read_text() + "\n# tamper\n")
    with pytest.raises(ConfigError, match="sha256 pin mismatch"):
        load_all(cfg_dir)


def test_unsigned_rejected(cfg_dir):
    (cfg_dir / "risk_policy.yaml.sha256").unlink()
    with pytest.raises(ConfigError, match="unsigned"):
        load_all(cfg_dir)


def test_ed25519_roundtrip_and_tamper(cfg_dir, tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from atlas.control.policy.signing import sign_policy_main
    keyfile = tmp_path / "owner_key.pem"  # throwaway test key, outside config dir
    keyfile.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    (cfg_dir / "risk_policy.yaml.sha256").unlink()
    sign_policy_main([str(cfg_dir), str(keyfile)])
    load_all(cfg_dir)
    sig = cfg_dir / "risk_policy.yaml.sig"
    raw = bytearray(base64.b64decode(sig.read_text())); raw[0] ^= 1
    sig.write_text(base64.b64encode(bytes(raw)).decode())
    with pytest.raises(ConfigError, match="INVALID"):
        load_all(cfg_dir)


def test_sig_without_pubkey(cfg_dir):
    (cfg_dir / "risk_policy.yaml.sig").write_text("AAAA")
    with pytest.raises(ConfigError, match="both"):
        load_all(cfg_dir)
