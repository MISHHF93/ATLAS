from datetime import date

import pytest
import yaml

from founder_conftest import CONFIG_DIR, intent, state
from atlas.control.policy import ConfigError, load_all
from atlas.control.policy.venues import EligibilityHook, symbol_assets, validate_venues
from atlas.mcp.trading import build_service


def edit(d, fn):
    p = d / "venues.yaml"
    data = yaml.safe_load(p.read_text()); fn(data); p.write_text(yaml.safe_dump(data))


def errs(d):
    with pytest.raises(ConfigError) as e:
        load_all(d)
    return "\n".join(e.value.errors)


def test_venues_loaded(cfg):
    assert cfg.venues.venues["kraken"].flags.spot_only and "USDT" in cfg.venues.venues["kraken"].asset_blocklist
    assert cfg.brokers.platforms["kraken"].enabled and cfg.brokers.platforms["kraken"].mode == "paper"


def test_missing_venues_fails(cfg_dir):
    (cfg_dir / "venues.yaml").unlink()
    assert "venues.yaml: missing" in errs(cfg_dir)


def test_stale_registration_fails_closed(cfg_dir):
    edit(cfg_dir, lambda d: d["venues"]["kraken"]["registration"].__setitem__("last_verified", date(2026, 6, 1)))
    assert "kraken" in errs(cfg_dir) and "re-verify" in errs(cfg_dir)


def test_90_day_boundary(cfg):
    vc = cfg.venues
    enabled = ["kraken"]
    assert validate_venues(vc, enabled, date(2027, 1, 14)) == []      # 90 days
    assert validate_venues(vc, enabled, date(2027, 1, 15))            # 91 days


def test_unregistered_status_fails(cfg_dir):
    edit(cfg_dir, lambda d: d["venues"]["coinbase"]["registration"].__setitem__("status", "pending"))
    assert "coinbase" in errs(cfg_dir)


def test_margin_flag_rejected(cfg_dir):
    edit(cfg_dir, lambda d: d["venues"]["kraken"]["flags"].__setitem__("margin", True))
    assert "margin/derivatives" in errs(cfg_dir)


def test_excluded_venue_enabled(cfg):
    assert any("excluded" in e for e in validate_venues(cfg.venues, ["questrade"]) + validate_venues(cfg.venues, ["binance"])) or \
        any("no eligibility entry" in e for e in validate_venues(cfg.venues, ["binance"]))


def test_alpaca_cannot_be_live_capable(cfg_dir):
    edit(cfg_dir, lambda d: d["venues"]["alpaca"].__setitem__("paper_only", False))
    assert "alpaca" in errs(cfg_dir)


def test_corporation_needs_pro_data_and_eligible_venues(cfg_dir):
    edit(cfg_dir, lambda d: d["operating_entity"].__setitem__("type", "corporation"))
    e = errs(cfg_dir)
    assert "'alpaca' not available to entity type 'corporation'" in e
    assert "non_pro licence cannot be used by a corporation" in e


def test_fund_cannot_use_kraken_or_coinbase(cfg_dir):
    edit(cfg_dir, lambda d: d["operating_entity"].__setitem__("type", "fund"))
    e = errs(cfg_dir)
    assert "'kraken' not available to entity type 'fund'" in e and "'coinbase' not available" in e


def test_tsx_data_not_from_massive(cfg_dir):
    edit(cfg_dir, lambda d: d["data_routes"].__setitem__("ca_equity", ["massive", "ibkr_data"]))
    assert "no TSX coverage" in errs(cfg_dir)


@pytest.mark.parametrize("sym,expected", [("USDT/CAD", {"USDT", "CAD"}), ("XBT-USDT", {"XBT", "USDT"}),
                                          ("WBTCCAD", {"WBTCCAD", "WBTC", "CAD"}), ("BTC-CAD", {"BTC", "CAD"})])
def test_symbol_assets(sym, expected):
    assert expected <= symbol_assets(sym)


def kr(symbol, **kw):
    return intent(symbol=symbol, broker="kraken", asset_class="crypto_spot", sleeve="high_risk", qty=0.01, **kw)


@pytest.fixture
def svc():
    s = build_service(CONFIG_DIR); s.heartbeat(); return s


def failed(d):
    return [k for k, v in d.checks.items() if not v]


@pytest.mark.parametrize("sym", ["USDT/CAD", "DAI-CAD", "WBTC/CAD", "XMR/CAD", "USDG/CAD", "BTC/USDT"])
def test_kraken_blocklist_enforced(svc, sym):
    d = svc.engine.evaluate(kr(sym), svc.broker.snapshot())
    assert "venue_eligibility" in failed(d) and "restricted list" in " ".join(d.reasons)


def test_kraken_allowed_asset(svc):
    d = svc.engine.evaluate(kr("XBT/CAD"), svc.broker.snapshot())
    assert d.approved, d.reasons


def test_kraken_no_derivatives(svc):
    d = svc.engine.evaluate(kr("XBT/CAD").model_copy(update={"asset_class": "future", "sleeve": "high_risk"}), svc.broker.snapshot())
    assert "venue_eligibility" in failed(d)


def test_ibkr_crypto_not_eligible(svc):
    d = svc.engine.evaluate(intent(symbol="BTC-CAD", broker="ibkr", asset_class="crypto_spot", sleeve="high_risk", qty=0.01), svc.broker.snapshot())
    assert "venue_eligibility" in failed(d)


def test_coinbase_interim_relief_warning(svc):
    d = svc.engine.evaluate(intent(symbol="BTC-CAD", broker="coinbase", asset_class="crypto_spot", sleeve="high_risk", qty=0.01), svc.broker.snapshot())
    assert d.approved and any("interim" in w for w in d.warnings)


def test_runtime_staleness_fails_closed(cfg):
    hook = EligibilityHook(cfg.venues, today=lambda: date(2027, 3, 1))
    fails, _ = hook(kr("XBT/CAD"), state())
    assert any("re-verify" in f for f in fails)


def test_alpaca_paper_still_ok(svc):
    assert svc.engine.evaluate(intent(), svc.broker.snapshot()).approved
