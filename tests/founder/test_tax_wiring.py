"""Milestone: tax ledger wired to paper fills, superficial-loss guard (warn default),
Kraken synced blocklist file, BoC fetcher (disabled by default; fake HTTP only)."""
import json
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from founder_conftest import CONFIG_DIR, intent
from atlas.control.policy import ConfigError, load_all
from atlas.control.policy.venues import EligibilityHook
from atlas.mcp.trading import build_service
from atlas.tax.boc_fetch import BocFetcher, FetchDisabled
from atlas.tax.config import TaxCfg
from atlas.tax.ledger import TaxLedger

TOR = ZoneInfo("America/Toronto")
FIX = Path(__file__).parent / "fixtures" / "boc_valet_fx.json"
ORDER = dict(symbol="SPY", side="buy", qty=10, order_type="limit", limit_price=100, reference_price=100,
             sleeve="core", asset_class="index_etf", broker="alpaca", quote_age_s=1.0)


@pytest.fixture
def svc():
    s = build_service(CONFIG_DIR)
    s.broker.clock = lambda: datetime(2026, 10, 16, 10, 0, tzinfo=TOR)
    s.heartbeat()
    return s


def run(svc, **kw):
    r = svc.propose_order(**(ORDER | kw))
    assert r["approved"], r
    out = svc.owner_approve(r["approval_id"], "masharai", True)
    assert out["executes"]
    return r


def test_default_tax_cfg_is_warn():
    cfg = load_all(CONFIG_DIR)
    assert cfg.tax.superficial_loss_guard == "warn" and cfg.tax.boc_fetch.enabled is False


def test_fills_flow_into_tax_ledger_and_audit(svc):
    run(svc)
    assert len(svc.tax.events) == 1
    t = svc.tax.events[0]
    assert t.property == "SPY" and t.side == "buy" and t.qty == D(10) and t.fx.source == "identity (CAD)"
    rep = svc.tax.report()
    q, cost = rep.acb("masharai", "SPY")
    assert q == D(10) and cost > D(1000)  # price + slippage + commission
    assert len(svc.audit.entries("tax.event")) == 1 and svc.audit.verify() > 0


def test_superficial_loss_warns_but_does_not_block_by_default(svc):
    run(svc)
    sell = svc.propose_order(**(ORDER | dict(side="sell", limit_price=90, reference_price=90)))
    assert sell["approved"] and any("superficial" in w for w in sell["warnings"])
    svc.owner_approve(sell["approval_id"], "masharai", True)
    assert svc.tax.report().dispositions[0].gain < 0
    rebuy = svc.propose_order(**(ORDER | dict(limit_price=91, reference_price=91)))
    assert rebuy["approved"] and any("within 30 days of a loss sale" in w for w in rebuy["warnings"])


def test_block_mode(cfg_dir):
    p = cfg_dir / "tax.yaml"
    d = yaml.safe_load(p.read_text()); d["superficial_loss_guard"] = "block"; p.write_text(yaml.safe_dump(d))
    s = build_service(cfg_dir)
    s.broker.clock = lambda: datetime(2026, 10, 16, 10, 0, tzinfo=TOR)
    s.heartbeat()
    run(s)
    r = s.propose_order(**(ORDER | dict(side="sell", limit_price=90, reference_price=90)))
    assert not r["approved"] and any("superficial" in x for x in r["reasons"])


def test_off_mode_no_hook(cfg_dir):
    p = cfg_dir / "tax.yaml"
    d = yaml.safe_load(p.read_text()); d["superficial_loss_guard"] = "off"; p.write_text(yaml.safe_dump(d))
    s = build_service(cfg_dir)
    assert not any(getattr(h, "name", "") == "superficial_loss_guard" for h in s.engine.hooks)


def test_invalid_tax_yaml_fails_closed(cfg_dir):
    (cfg_dir / "tax.yaml").write_text("superficial_loss_guard: maybe\n")
    with pytest.raises(ConfigError, match="tax.yaml"):
        load_all(cfg_dir)


def test_usd_fill_uses_labelled_fill_rate_without_boc():
    led = TaxLedger(TaxCfg(), clock=lambda: datetime(2026, 2, 2, 12, tzinfo=TOR))
    from atlas.execution.paper.broker import Fill
    t = led.on_fill(Fill("o1", "i1", "AAPL", "buy", 2, 200.0, 200.0, 1.4, -561.4, currency="USD", fx_rate=1.4))
    assert t.fx.rate == D("1.4") and "NOT Bank of Canada" in t.fx.source and t.foreign
    assert t.fee == D("1.000000")  # CAD 1.40 commission expressed in USD


def test_usd_fill_uses_boc_file_when_configured(tmp_path):
    import shutil
    shutil.copy(FIX, tmp_path / "boc.json")
    cfg = TaxCfg(fx={"source": "boc_file", "boc_file": "boc.json"})
    led = TaxLedger.from_config(cfg, tmp_path, clock=lambda: datetime(2026, 2, 2, 12, tzinfo=TOR))
    from atlas.execution.paper.broker import Fill
    t = led.on_fill(Fill("o1", "i1", "AAPL", "buy", 2, 200.0, 200.0, 0, -560, currency="USD", fx_rate=1.3))
    assert t.fx.rate == D("1.4000") and t.fx.source.startswith("Bank of Canada")


def test_ledger_persists_and_reloads(tmp_path):
    db = str(tmp_path / "tax.db")
    from atlas.execution.paper.broker import Fill
    led = TaxLedger(TaxCfg(), db_path=db, clock=lambda: datetime(2026, 3, 1, 12, tzinfo=TOR))
    led.on_fill(Fill("o1", "i1", "XIC", "buy", 5, 30.0, 30.0, 1.0, -151))
    again = TaxLedger(TaxCfg(), db_path=db)
    assert again.events == led.events and again.report().acb("masharai", "XIC") == (D(5), D("151.00"))


def test_crypto_fill_is_crypto_not_foreign():
    from atlas.execution.paper.broker import Fill
    led = TaxLedger(TaxCfg(), clock=lambda: datetime(2026, 3, 1, 12, tzinfo=TOR))
    t = led.on_fill(Fill("o1", "i1", "BTC/CAD", "buy", 0.1, 90000.0, 90000.0, 1, -9001, asset_class="crypto_spot",
                         issuer="BTC", broker="kraken"))
    assert t.asset_type == "crypto" and not t.foreign and t.property == "BTC" and t.venue == "kraken"


# ---------------------------------------------------------------- Kraken blocklist file
def _kraken_bl(cfg_dir, fn):
    p = cfg_dir / "blocklists" / "kraken_ca.yaml"
    d = yaml.safe_load(p.read_text()); fn(d); p.write_text(yaml.safe_dump(d))


def test_kraken_blocklist_loaded_from_synced_file(cfg):
    assert {"USDT", "USDG", "DAI", "WBTC", "XMR"} <= set(cfg.venues.venues["kraken"].asset_blocklist)
    assert any("incomplete" in w for w in cfg.warnings)


def test_blocklist_file_additions_enforced(cfg_dir):
    _kraken_bl(cfg_dir, lambda d: d["assets"].append({"symbol": "PEPE", "reason": "test"}))
    cfg = load_all(cfg_dir)
    i = intent(symbol="PEPE/CAD", broker="kraken", asset_class="crypto_spot", sleeve="high_risk", qty=1)
    fails, _ = EligibilityHook(cfg.venues)(i, None)
    assert any("restricted" in f for f in fails)


@pytest.mark.parametrize("mut,msg", [
    (lambda d: d.__setitem__("retrieved", date(2026, 6, 1)), "stale"),
    (lambda d: d.__setitem__("venue", "coinbase"), "not 'kraken'"),
    (lambda d: d.pop("assets"), "invalid"),
])
def test_blocklist_file_problems_fail_closed(cfg_dir, mut, msg):
    _kraken_bl(cfg_dir, mut)
    with pytest.raises(ConfigError, match=msg):
        load_all(cfg_dir)


def test_missing_blocklist_file_fails_closed(cfg_dir):
    (cfg_dir / "blocklists" / "kraken_ca.yaml").unlink()
    with pytest.raises(ConfigError, match="missing"):
        load_all(cfg_dir)


# ---------------------------------------------------------------- BoC fetcher
def test_fetcher_disabled_by_default():
    calls = []
    f = BocFetcher(http_get=lambda u: calls.append(u) or "{}")
    with pytest.raises(FetchDisabled):
        f.fetch(date(2026, 1, 1), date(2026, 3, 1))
    assert calls == []


def test_fetcher_with_fake_http_writes_cache(tmp_path):
    seen = []
    f = BocFetcher(enabled=True, series=["FXUSDCAD"], http_get=lambda u: seen.append(u) or FIX.read_text())
    prov = f.fetch(date(2026, 1, 1), date(2026, 3, 31), cache_file=tmp_path / "c.json")
    assert seen[0].startswith("https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?start_date=2026-01-01")
    assert prov.quote("USD", date(2026, 2, 2)).rate == D("1.4000")
    assert json.loads((tmp_path / "c.json").read_text())["observations"]


def test_fetcher_rejects_bad_series_and_payload():
    with pytest.raises(ValueError):
        BocFetcher(enabled=True, series=["FXUSD;rm"], http_get=lambda u: "{}").fetch(date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(ValueError, match="observations"):
        BocFetcher(enabled=True, http_get=lambda u: '{"x":1}').fetch(date(2026, 1, 1), date(2026, 1, 2))
