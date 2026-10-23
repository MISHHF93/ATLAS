"""Worked examples (CRA-style). Figures verified by hand; NOT tax advice."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from atlas.tax import Affiliations, BocFxProvider, Dividend, Entity, Income, Swap, TaxEngine, Trade, Transfer
from atlas.tax.events import CryptoFee
from atlas.tax.fx import FxUnavailable
from atlas.tax.guard import SuperficialLossGuard

TOR = ZoneInfo("America/Toronto")
FX = BocFxProvider.from_valet_json(Path(__file__).parent / "fixtures" / "boc_valet_fx.json")
ME = Entity("me-cash", "individual", "masharai")
ME2 = Entity("me-margin-ibkr", "individual", "masharai")
SPOUSE = Entity("spouse", "individual", "spouse")
TFSA = Entity("me-tfsa", "tfsa", "masharai-tfsa")
CORP = Entity("holdco", "corporation", "holdco")
ALL = [ME, ME2, SPOUSE, TFSA, CORP]
AFF = Affiliations([{"me-cash", "me-margin-ibkr", "spouse", "me-tfsa", "holdco"}])


def ts(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=TOR)


_n = [0]


def tr(day, side, qty, price, prop="XYZ", entity="me-cash", fee="0", venue="ibkr", **kw):
    _n[0] += 1
    return Trade(f"t{_n[0]}", entity, venue, day, prop, side, D(str(qty)), D(str(price)), fee=D(fee), **kw)


def eng(**kw):
    return TaxEngine(ALL, AFF, FX, **kw)


# ---------------------------------------------------------------- ACB
def test_cra_style_average_cost():
    ev = [tr(ts(2026, 1, 5), "buy", 200, 15, fee="20"), tr(ts(2026, 2, 5), "buy", 300, 16, fee="25"),
          tr(ts(2026, 3, 5), "sell", 100, 18, fee="20")]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert (d.proceeds, d.outlays, round(d.acb, 2), round(d.gain, 2)) == (D(1800), D(20), D("1569.00"), D("211.00"))
    assert r.acb("masharai", "XYZ") == (D(400), D("6276.00"))


def test_pooled_across_accounts_and_venues():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 50000, prop="BTC", venue="coinbase", asset_type="crypto"),
          tr(ts(2026, 1, 6), "buy", 1, 60000, prop="BTC", entity="me-margin-ibkr", venue="kraken", asset_type="crypto"),
          tr(ts(2026, 3, 1), "sell", 1, 58000, prop="BTC", venue="kraken", asset_type="crypto")]
    r = eng().run(ev)
    assert r.dispositions[0].gain == D(3000) and r.acb("masharai", "BTC") == (D(1), D("55000.00"))


def test_entities_are_separate_taxpayers():
    ev = [tr(ts(2026, 1, 5), "buy", 10, 100), tr(ts(2026, 1, 6), "buy", 10, 200, entity="holdco")]
    r = eng().run(ev)
    assert r.acb("masharai", "XYZ") == (D(10), D("1000.00")) and r.acb("holdco", "XYZ") == (D(10), D("2000.00"))


def test_usd_fill_uses_boc_rate_with_source_and_weekend_fallback():
    ev = [tr(ts(2026, 1, 10), "buy", 10, 500, prop="SPY", currency="USD", fee="1", foreign=True),   # Saturday -> Fri Jan 9
          tr(ts(2026, 3, 2), "sell", 10, 520, prop="SPY", currency="USD", fee="1", foreign=True)]
    r = eng().run(ev)
    assert r.fills_fx[0]["source"] == "Bank of Canada Valet FXUSDCAD 2026-01-09" and r.fills_fx[0]["rate"] == D("1.3800")
    d = r.dispositions[0]
    assert d.acb == D("6901.3800") and d.proceeds == D("7020.0000") and d.outlays == D("1.3500")
    assert round(d.gain, 2) == D("117.27")
    assert "FXUSDCAD 2026-03-02" in d.fx_source


def test_missing_fx_fails_closed():
    with pytest.raises(FxUnavailable):
        eng().run([tr(ts(2026, 1, 5), "buy", 1, 1, currency="JPY")])
    with pytest.raises(ValueError):
        TaxEngine(ALL, AFF, None).run([tr(ts(2026, 1, 5), "buy", 1, 1, currency="USD")])


# ---------------------------------------------------------------- superficial loss
def test_superficial_full_denial_added_to_acb():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 3, 16), "buy", 100, 7)]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert d.gain == D(-400) and d.denied_loss == D(400) and d.allowable == 0 and d.treatment == "added_to_acb:me-cash"
    assert r.acb("masharai", "XYZ") == (D(100), D("1100.00"))


def test_superficial_partial_denial():
    ev = [tr(ts(2026, 1, 2), "buy", 1000, 10), tr(ts(2026, 3, 2), "sell", 1000, 8), tr(ts(2026, 3, 11), "buy", 500, "8.5")]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert d.gain == D(-2000) and d.denied_loss == D(1000) and d.allowable == D(-1000)
    assert r.acb("masharai", "XYZ") == (D(500), D("5250.00"))


def test_purchase_before_sale_counts():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 2, 13), "buy", 100, 8), tr(ts(2026, 3, 2), "sell", 100, 7)]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert d.gain == D(-200) and d.denied_loss == D(200)
    assert r.acb("masharai", "XYZ") == (D(100), D("1100.00"))


def test_rebuy_on_day_31_not_superficial():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 4, 2), "buy", 100, 7)]
    r = eng().run(ev)
    assert r.dispositions[0].denied_loss == 0 and r.acb("masharai", "XYZ") == (D(100), D("700.00"))


def test_rebought_but_not_held_at_window_end():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6),
          tr(ts(2026, 3, 10), "buy", 100, 7), tr(ts(2026, 3, 20), "sell", 100, 7)]
    r = eng().run(ev)
    assert r.dispositions[0].denied_loss == 0


def test_spouse_repurchase_denied_and_added_to_spouse_acb():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 3, 5), "buy", 100, 6, entity="spouse")]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert d.denied_loss == D(400) and d.treatment == "added_to_acb:spouse"
    assert r.acb("spouse", "XYZ") == (D(100), D("1000.00"))


def test_tfsa_repurchase_permanently_denied():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 3, 5), "buy", 100, 6, entity="me-tfsa")]
    r = eng().run(ev)
    d = r.dispositions[0]
    assert d.denied_loss == D(400) and d.treatment.startswith("permanently_denied")
    assert ("masharai-tfsa", "XYZ") not in r.pools


def test_corporation_loss_suspended():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10, entity="holdco"), tr(ts(2026, 3, 2), "sell", 100, 6, entity="holdco"),
          tr(ts(2026, 3, 5), "buy", 100, 6, entity="holdco")]
    d = eng().run(ev).dispositions[0]
    assert d.denied_loss == D(400) and d.treatment.startswith("suspended_40(3.4)")


def test_unaffiliated_entity_purchase_does_not_deny():
    e = TaxEngine(ALL, Affiliations([]), FX)
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 3, 5), "buy", 100, 6, entity="spouse")]
    assert e.run(ev).dispositions[0].denied_loss == 0


def test_crypto_superficial_loss_applies():
    ev = [tr(ts(2026, 1, 2), "buy", 1, 60000, prop="BTC", asset_type="crypto", venue="coinbase"),
          tr(ts(2026, 3, 2), "sell", 1, 50000, prop="BTC", asset_type="crypto", venue="coinbase"),
          tr(ts(2026, 3, 3), "buy", 1, 50500, prop="BTC", asset_type="crypto", venue="kraken")]
    r = eng().run(ev)
    assert r.dispositions[0].denied_loss == D(10000) and r.acb("masharai", "BTC") == (D(1), D("60500.00"))


# ---------------------------------------------------------------- crypto events
def test_crypto_to_crypto_swap_is_disposition():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 4000, prop="ETH", asset_type="crypto", venue="kraken"),
          Swap("s1", "me-cash", "kraken", ts(2026, 2, 5), "ETH", D(1), "XBT", D("0.05"), D(5000))]
    r = eng().run(ev)
    assert r.dispositions[0].gain == D(1000) and r.acb("masharai", "XBT") == (D("0.05"), D("5000.00"))


def test_fee_paid_in_crypto_is_disposition_and_cost():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 50000, prop="BTC", asset_type="crypto", venue="kraken"),
          tr(ts(2026, 2, 5), "buy", 10, 300, prop="SOL", asset_type="crypto", venue="kraken",
             crypto_fee=CryptoFee("BTC", D("0.001"), D(60)))]
    r = eng().run(ev)
    fee = r.dispositions[0]
    assert fee.property == "BTC" and fee.qty == D("0.001") and fee.gain == D(10)   # 60 - 50
    assert r.acb("masharai", "SOL") == (D(10), D("3060.00"))


def test_transfer_linked_not_a_disposition_network_fee_is():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 50000, prop="BTC", asset_type="crypto", venue="coinbase"),
          Transfer("x1", "T1", "me-cash", "coinbase", ts(2026, 1, 6), "BTC", D(1), "out", D("0.0001"), D(6)),
          Transfer("x2", "T1", "me-cash", "kraken", ts(2026, 1, 6, 13), "BTC", D("0.9999"), "in")]
    r = eng().run(ev)
    assert [d.id for d in r.dispositions] == ["x1:netfee"] and r.dispositions[0].gain == D(1)
    assert r.warnings == [] and r.acb("masharai", "BTC")[0] == D("0.9999")


def test_unlinked_or_cross_taxpayer_transfer_flagged():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 50000, prop="BTC", asset_type="crypto"),
          Transfer("x1", "T9", "me-cash", "coinbase", ts(2026, 1, 6), "BTC", D(1), "out"),
          Transfer("y1", "T2", "me-cash", "coinbase", ts(2026, 1, 7), "BTC", D(0), "out"),
          Transfer("y2", "T2", "spouse", "kraken", ts(2026, 1, 7), "BTC", D(0), "in")]
    w = " ".join(eng().run(ev).warnings)
    assert "T9: unlinked" in w and "T2: between different taxpayers" in w


def test_staking_income_and_acb():
    ev = [Income("i1", "me-cash", "kraken", ts(2026, 2, 1), "ETH", D("0.1"), D(400))]
    r = eng().run(ev)
    assert r.income[0]["fmv_cad"] == D("400.00") and r.acb("masharai", "ETH") == (D("0.1"), D("400.00"))


# ---------------------------------------------------------------- dividends / T1135 / evidence
def test_us_withholding_checks():
    ev = [Dividend("d1", "me-cash", ts(2026, 2, 2), "SPY", D(100), "USD", D(15)),
          Dividend("d2", "me-margin-ibkr", ts(2026, 2, 2), "SPY", D(100), "USD", D(30)),
          Dividend("d3", "me-tfsa", ts(2026, 2, 2), "SPY", D(100), "USD", D(15))]
    r = eng().run(ev)
    d1, d2, d3 = r.dividends
    assert d1["gross_cad"] == D("140.00") and d1["withheld_cad"] == D("21.00") and not d1["warning"]
    assert "30%" in d2["warning"] and "TFSA" in d3["warning"]


def test_t1135_peak_cost_threshold():
    ev = [tr(ts(2026, 1, 9), "buy", 100, 500, prop="SPY", currency="USD", foreign=True),       # 69,000 CAD
          tr(ts(2026, 2, 2), "buy", 50, 500, prop="QQQ", currency="USD", foreign=True),        # +35,000 -> 104,000
          tr(ts(2026, 3, 2), "sell", 100, 500, prop="SPY", currency="USD", foreign=True),
          tr(ts(2026, 2, 2), "buy", 500, 500, prop="VOO", currency="USD", foreign=True, entity="me-tfsa")]  # registered: excluded
    r = eng().run(ev)
    t = r.t1135[("masharai", 2026)]
    assert t["peak_cost_cad"] == D("104000.00") and t["t1135_required"] and str(t["peak_date"]) == "2026-02-02"


def test_t1135_below_threshold():
    r = eng().run([tr(ts(2026, 1, 9), "buy", 10, 500, prop="SPY", currency="USD", foreign=True)])
    assert not r.t1135[("masharai", 2026)]["t1135_required"]


def test_business_vs_capital_evidence():
    base = ts(2026, 1, 5)
    ev = []
    for i in range(10):
        ev += [tr(base + timedelta(days=3 * i), "buy", 10, 100), tr(base + timedelta(days=3 * i + 1), "sell", 10, 101)]
    ev += [tr(ts(2026, 2, 5), "buy", 1, 10, entity="me-tfsa"), tr(ts(2026, 2, 6), "sell", 1, 11, entity="me-tfsa")]
    r = eng().run(ev)
    e = r.evidence[("me-cash", 2026)]
    assert e["trades"] == 20 and e["automated_trades"] == 20 and e["median_holding_days"] == 1 and e["pct_held_under_30d"] == 100.0
    assert any("automated" in f for f in e["flags"]) and any("turnover" in f for f in e["flags"])
    assert any("registered" in f for f in r.evidence[("me-tfsa", 2026)]["flags"])
    assert "me-tfsa" in r.evidence_csv()


def test_registered_plan_has_no_reportable_dispositions():
    ev = [tr(ts(2026, 1, 5), "buy", 10, 100, entity="me-tfsa"), tr(ts(2026, 2, 5), "sell", 10, 50, entity="me-tfsa")]
    assert eng().run(ev).dispositions == []


# ---------------------------------------------------------------- exports
def test_csv_exports_and_schedule3():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6), tr(ts(2026, 3, 16), "buy", 100, 7),
          tr(ts(2026, 4, 20), "sell", 100, 13),
          tr(ts(2026, 1, 5), "buy", 1, 4000, prop="ETH", asset_type="crypto"),
          Swap("s1", "me-cash", "kraken", ts(2026, 2, 5), "ETH", D(1), "XBT", D("0.05"), D(5000))]
    r = eng().run(ev)
    s3 = r.schedule3("masharai", 2026)
    sh = s3["shares_and_units"]
    assert sh["denied_superficial"] == D("400.00") and sh["losses"] == D("0.00")
    assert sh["gains"] == D("200.00")       # 1300 - 1100 adjusted ACB
    assert s3["crypto"]["net"] == D("1000.00") and s3["crypto"]["taxable_if_capital"] == D("500.00")
    csv_t = r.t5008_csv("masharai", 2026)
    assert csv_t.startswith("# NOT TAX ADVICE") and "superficial_denied_cad" in csv_t and r.input_hash in csv_t
    assert len(csv_t.strip().splitlines()) == 2 + 3
    assert "shares_and_units" in r.schedule3_csv("masharai", 2026)


def test_input_hash_deterministic():
    ev = [tr(ts(2026, 1, 5), "buy", 1, 1)]
    assert eng().run(ev).input_hash == eng().run(list(ev)).input_hash


# ---------------------------------------------------------------- pre-trade guard
def loss_history():
    return [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 3, 2), "sell", 100, 6)]


def test_guard_warns_on_rebuy_after_loss():
    g = SuperficialLossGuard(eng(), loss_history(), "me-cash", today=lambda: ts(2026, 3, 10).date())
    assert g.check("XYZ", "buy", None)
    g2 = SuperficialLossGuard(eng(), loss_history(), "spouse", today=lambda: ts(2026, 3, 10).date())
    assert g2.check("XYZ", "buy", None)  # affiliated
    g3 = SuperficialLossGuard(eng(), loss_history(), "me-cash", today=lambda: ts(2026, 4, 5).date())
    assert g3.check("XYZ", "buy", None) == []


def test_guard_sell_at_loss_after_recent_buy():
    ev = [tr(ts(2026, 1, 2), "buy", 100, 10), tr(ts(2026, 2, 20), "buy", 100, 9)]
    g = SuperficialLossGuard(eng(), ev, "me-cash", today=lambda: ts(2026, 3, 2).date())
    m = g.check("XYZ", "sell", D(8))
    assert m and "superficial" in m[0]
    assert g.check("XYZ", "sell", D(12)) == []


def test_guard_as_risk_hook_block_and_warn():
    from founder_conftest import CONFIG_DIR, intent
    from atlas.mcp.trading import build_service
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    g = SuperficialLossGuard(eng(), loss_history(), "me-cash", mode="block", today=lambda: ts(2026, 3, 10).date())
    svc.engine.hooks.append(g)
    d = svc.engine.evaluate(intent(symbol="XYZ"), svc.broker.snapshot())
    assert not d.approved and not d.checks["superficial_loss_guard"]
    g.mode = "warn"
    d = svc.engine.evaluate(intent(symbol="XYZ"), svc.broker.snapshot())
    assert d.approved and any("superficial" in w for w in d.warnings)
