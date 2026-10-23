"""Round-2 strategy items: each module on fixtures + harness (trial log, DSR, challenger-only)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from founder_conftest import pos, state

FX = Path(__file__).parent / "fixtures" / "strategies2"


# ---------------- harness
def test_harness_logs_trial_deflates_and_registers_challenger_only(tmp_path):
    from atlas.models.quant.stack2 import all_trial_srs
    from atlas.strategies.sleeve_strategies.harness import evaluate_challenger, strat_registry
    rng = np.random.default_rng(0)
    r1 = evaluate_challenger(tmp_path, "pairs", rng.normal(0, 0.01, 500), {"a": 1})
    r2 = evaluate_challenger(tmp_path, "pairs", rng.normal(0, 0.01, 500), {"a": 2})
    assert r2["n_trials"] == 2 and len(all_trial_srs(tmp_path)) == 2
    assert not r1["gate_dsr"] and not r2["gate_dsr"]          # noise must not pass DSR
    reg = strat_registry(tmp_path, "pairs")
    assert reg.challenger == r2["model_id"] and reg.champion is None
    assert reg.stage(r1["model_id"]) == "archived"
    assert reg.load(r2["model_id"]).params == {"a": 2}       # digest-checked load


def test_nonalpha_pool_does_not_deflate_alpha(tmp_path):
    from atlas.models.quant.stack2 import all_trial_srs
    from atlas.strategies.sleeve_strategies.harness import evaluate_challenger
    evaluate_challenger(tmp_path, "fx_cost", np.full(100, 1e-4) + np.random.default_rng(1).normal(0, 1e-7, 100), {}, register=False)
    assert all_trial_srs(tmp_path) == []                     # separate pool
    assert len(all_trial_srs(tmp_path / "_nonalpha")) == 1


# ---------------- 1 cash yield
def test_cash_yield_plan_policy_and_buffer(cfg):
    from atlas.strategies.sleeve_strategies.cash_yield import CashYieldPlanner, backtest
    p = CashYieldPlanner(buffer_pct=5)
    st = state(cash=20_000)
    out = p.plan(st, 20_000, cfg.risk, {"CASH.TO": 50.0, "ZMMK.TO": 50.0}, sleeve_headroom_base=12_000)
    (i,) = out["intents"]
    assert i.symbol == "CASH.TO" and i.side == "buy" and i.qty * 50 <= 12_000 and i.sleeve == "core"
    assert "cash-equivalent" in out["notes"][0]
    blocked = CashYieldPlanner(sleeve="high_risk").plan(st, 20_000, cfg.risk, {"CASH.TO": 50.0})
    assert not blocked["intents"] and "blocked by policy" in blocked["notes"][0]
    assert not p.plan(state(cash=1_100), 20_000, cfg.risk, {"CASH.TO": 50.0})["intents"]   # within buffer
    held = state(cash=100, positions={"CASH.TO": pos("CASH.TO", qty=100, price=50)})
    assert p.needs_cash(held, 2_000) == [("CASH.TO", 38)]
    assert backtest(np.array([0.5]), np.array([0.0252]))[0] == pytest.approx(0.5 * 0.0252 / 252 - 0.02 * 0.5 * 1e-4)


# ---------------- 2 fx cost
def test_fx_planner_routes():
    from atlas.strategies.sleeve_strategies.fx_cost import plan
    small = plan(1_000)
    costs = {r["route"]: r["cost_cad"] for r in small["routes"]}
    assert costs["ibkr_spot"] == pytest.approx(2.74 + 0.05, abs=0.01)   # USD 2 minimum dominates
    assert small["best"]["cost_cad"] == min(costs.values()) and costs["retail_conversion"] == 20.0
    big = plan(200_000)
    assert big["best"]["route"] in ("ibkr_spot", "norberts_gambit") and big["saving_vs_retail_cad"] > 3_000
    reg = plan(50_000, account="rrsp")
    assert reg["best"]["route"] in ("norberts_gambit", "ibkr_spot") and len(reg["best"]["steps"]) >= 1
    assert plan(50_000, account="rrsp")["routes"][-1]["route"] == "retail_conversion"


# ---------------- 3 overlays
def test_overlays_down_only_and_no_lookahead():
    from atlas.strategies.sleeve_strategies.overlays import TrendSwitch, VolManaged
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2023-01-02", periods=400)
    calm = np.cumsum(rng.normal(0, 0.003, 200)); wild = np.cumsum(rng.normal(-0.002, 0.04, 200))
    close = pd.Series(100 * np.exp(np.r_[calm, calm[-1] + wild]), index=idx)
    m = VolManaged(target_vol=0.12).multipliers(close)
    assert m.max() <= 1.0 and m.min() >= 0.0 and m.iloc[:200].min() == 1.0 and m.iloc[-1] < 0.5
    t = TrendSwitch(sma=50, mom_days=60).multipliers(close)
    assert set(t.unique()) <= {0.0, 1.0} and t.iloc[:50].min() == 1.0     # warm-up never de-risks
    down = pd.Series(np.linspace(100, 60, 120), index=pd.bdate_range("2024-01-01", periods=120))
    assert TrendSwitch(sma=50, mom_days=60).multipliers(down).iloc[-1] == 0.0
    # no look-ahead: changing the last price doesn't change today's multiplier
    c2 = close.copy(); c2.iloc[-1] *= 3
    assert VolManaged().multipliers(c2).iloc[-1] == VolManaged().multipliers(close).iloc[-1]


def test_pipeline_overlay_champion_only_shrinks_and_challenger_is_shadow():
    from atlas.ops.pipeline_models import ModelSet
    from atlas.strategies.sleeve_strategies.harness import StratModel
    ms = ModelSet(preloaded={"strat_trend_switch": StratModel("trend_switch", {"sma": 5, "mom_days": 5, "off_mult": 0.0})})
    assert "strat_trend_switch" in ms.OVERLAY_KINDS
    from atlas.strategies.sleeve_strategies.overlays import OverlayModel
    falling = pd.Series(np.linspace(100, 50, 60), index=pd.bdate_range("2024-01-01", periods=60))
    assert OverlayModel.build(ms.acting["strat_trend_switch"]).multiplier(falling) == 0.0


# ---------------- 4 timing
def test_turn_of_month_window_and_auction_policy():
    from atlas.strategies.sleeve_strategies.timing import DeploymentTimer, auction_policy, tom_days
    idx = pd.bdate_range("2026-09-21", "2026-10-16")
    w = tom_days(idx)
    assert list(w[w].index.strftime("%m-%d")) == ["09-30", "10-01", "10-02", "10-05"]
    t = DeploymentTimer()
    assert t.deploy_now(idx, date(2026, 10, 1))[0]
    ok, why = t.deploy_now(idx, date(2026, 10, 14), cash_waiting_since=date(2026, 10, 7))
    assert not ok and "outside" in why
    assert t.deploy_now(idx, date(2026, 10, 14), cash_waiting_since=date(2026, 9, 25))[0]
    assert auction_policy("buy", urgent=False)["style"] == "closing_auction"
    assert auction_policy("sell", urgent=True)["style"] == "opening_auction"
    assert auction_policy("buy", False, venue_has_auctions=False)["style"] == "limit_twap"


# ---------------- 5 screens
def test_sedi_cluster_point_in_time():
    from atlas.strategies.sleeve_strategies.screens import InsiderClusterScreen, read_sedi_csv
    f = read_sedi_csv(FX / "sedi.csv")
    s = InsiderClusterScreen(min_insiders=3, min_value=20_000).score(f, date(2026, 10, 1))
    assert s["ACM"]["cluster"] and s["ACM"]["insiders"] == 3      # Dave's later filing not yet public
    assert not s["BET"]["cluster"]                                 # code 11 (not open-market buy) ignored
    assert not s["GAM"]["cluster"]                                 # value 15k < min
    assert InsiderClusterScreen().score(f, date(2026, 10, 25))["ACM"]["insiders"] == 1   # 30-day window moved: only Dave


def test_ciro_short_interest_screen():
    from atlas.strategies.sleeve_strategies.screens import ShortInterestScreen, read_ciro_csv
    rows = read_ciro_csv(FX / "ciro.csv")
    out = ShortInterestScreen(exclude_top_pct=34).evaluate(rows, date(2026, 10, 10))
    assert out["exclude"] == ["AAA"] and out["tilt"] == ["BBB"]   # 10-12 report not public yet
    assert out["dtc"]["AAA"] == 11.0


# ---------------- 6 PEAD
def test_pead_fixture_provider_and_signal():
    from atlas.strategies.sleeve_strategies.pead import FixtureEarningsProvider, PaidProviderPlaceholder, PeadSignal, event_backtest, sue
    p = FixtureEarningsProvider(FX / "earnings.csv")
    ev = p.events(date(2024, 1, 1), date(2024, 12, 31))
    assert [round(sue(e), 1) for e in ev] == [3.0, -1.0, 2.0]
    idx = pd.bdate_range("2024-01-02", periods=120)
    sig = PeadSignal(hold_days=60)
    assert sig.longs(ev, date(2024, 2, 5), idx) == []                  # not on announce day
    assert sig.longs(ev, date(2024, 2, 7), idx) == ["AAA"]
    assert "CCC" in sig.longs(ev, date(2024, 3, 6), idx)
    close = pd.DataFrame({s: np.linspace(100, 110, 120) for s in ("AAA", "BBB", "CCC")}, index=idx)
    assert event_backtest(close, ev, sig).sum() > 0
    with pytest.raises(RuntimeError):
        PaidProviderPlaceholder().events(date(2024, 1, 1), date(2024, 2, 1))


# ---------------- 7 index addition
def test_index_addition_predictor():
    from atlas.strategies.sleeve_strategies.index_add import IndexAdditionPredictor
    u = [{"symbol": "BIG", "price": 20, "listing_months": 40, "float_turnover": 1.2, "float_cap": 2e9},
         {"symbol": "NEW", "price": 20, "listing_months": 6, "float_turnover": 2.0, "float_cap": 5e9},
         {"symbol": "SML", "price": 5, "listing_months": 40, "float_turnover": 0.6, "float_cap": 3e8},
         {"symbol": "PNY", "price": 0.5, "listing_months": 40, "float_turnover": 1.0, "float_cap": 3e9}]
    r = IndexAdditionPredictor().rank(u, smallest_constituent_cap=8e8)
    assert r[0]["symbol"] == "BIG" and r[0]["p_add"] > 0.9
    assert {x["symbol"]: x["p_add"] for x in r}["NEW"] == 0.0 and {x["symbol"]: x["p_add"] for x in r}["SML"] < 0.1


# ---------------- 8 crypto
def test_crypto_factors_vol_target_and_maker_only():
    from atlas.strategies.sleeve_strategies.crypto_factors import CryptoFactorModel, is_maker, maker_only_limit
    from atlas.strategies.sleeve_strategies.research import synthetic_panel
    px = synthetic_panel(200, ("BTC", "ETH", "SOL"), seed=2, sigma=0.8)
    w = CryptoFactorModel(target_vol=0.40).weights(px)
    assert (w >= 0).all() and w.sum() <= 1.0 + 1e-9
    for side in ("buy", "sell"):
        lp = maker_only_limit(side, 100.00, 100.10)
        assert is_maker(side, lp, 100.00, 100.10)
    assert maker_only_limit("buy", 100.00, 100.01) == 100.00
    with pytest.raises(ValueError):
        maker_only_limit("buy", 100, 99)


# ---------------- 9 pairs
def test_pairs_switch_holds_cheaper_leg():
    from atlas.strategies.sleeve_strategies.pairs import PairSwitcher
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(5)
    b = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=idx)
    a = b * np.exp(np.r_[np.zeros(250), np.linspace(0, 0.15, 50)])     # A gets rich at the end
    pos_ = PairSwitcher(lookback=120, entry_z=1.5).positions(a, b)
    assert pos_.iloc[-1] == "B" and set(pos_.unique()) <= {"A", "B"}


# ---------------- 10 interlisted
def test_interlisted_venue_selection_counts_fx():
    from atlas.strategies.sleeve_strategies.interlisted import Line, choose_venue
    ca, us = Line("RY.TO", "CAD", 140.00, 140.06), Line("RY", "USD", 102.18, 102.20)
    no_usd = choose_venue(ca, us, 10_000, usd_on_hand=0)
    assert no_usd["choose"] == "RY.TO"                                  # FX cost dominates
    have_usd = choose_venue(ca, us, 10_000, usd_on_hand=10_000)
    assert have_usd["choose"] == "RY" and have_usd["options"][1]["fx_cost_cad"] == 0


# ---------------- 11 TLH
def test_tlh_taxable_only_superficial_loss_and_warning():
    from atlas.strategies.sleeve_strategies.tlh import BUSINESS_INCOME_WARNING, Holding, TlhPlanner
    from atlas.tax.entities import Affiliations, Entity
    from atlas.tax.events import Trade
    ents = {"me": Entity("me", "individual", "me"), "tfsa": Entity("tfsa", "tfsa", "me"), "spouse": Entity("spouse", "individual", "sp")}
    aff = Affiliations([{"me", "tfsa", "spouse"}])
    today = date(2026, 10, 16)
    hs = [Holding("me", "XIC", Decimal(100), Decimal(40), Decimal(34)),       # 600 loss
          Holding("me", "VFV", Decimal(100), Decimal(120), Decimal(100)),     # loss but spouse bought identical XUS
          Holding("tfsa", "XEF", Decimal(100), Decimal(40), Decimal(30)),     # registered
          Holding("me", "XUU", Decimal(10), Decimal(40), Decimal(39))]        # too small
    tr = [Trade("t1", "spouse", "ibkr", datetime(2026, 10, 1, tzinfo=timezone.utc), "XUS", "buy", Decimal(1), Decimal(100))]
    p = TlhPlanner().plan(hs, ents, aff, tr, today)
    (c,) = p["candidates"]
    assert c["symbol"] == "XIC" and c["replacement"] == "VCN" and c["no_repurchase_until"] == "2026-11-16"
    assert set(c["no_repurchase_accounts"]) == {"me", "tfsa", "spouse"} and c["taxable_capital_loss_cad"] == "300.00"
    why = {s["symbol"]: s["why"] for s in p["skipped"]}
    assert "superficial" in why["VFV"] and "registered" in why["XEF"]
    assert p["warning"] == BUSINESS_INCOME_WARNING and "business income" in p["warning"]


# ---------------- 12 tax location
def test_tax_location_report_only():
    from atlas.strategies.sleeve_strategies.tax_location import report
    r = report([{"symbol": "VTI", "income_type": "us_dividend_us_listed", "current_account": "tfsa", "annual_income_cad": 1000},
                {"symbol": "RY", "income_type": "ca_eligible_dividend", "current_account": "non_registered"}],
               {"non_registered", "rrsp", "tfsa"})
    assert r["report_only"] and r["rows"][0]["mismatch"] and r["rows"][0]["recommended"] == ["rrsp"]
    assert r["rows"][0]["est_annual_leak_cad"] == 150.0 and not r["rows"][1]["mismatch"]


# ---------------- research runner
def test_research_runner_registers_all_as_challengers(tmp_path):
    from atlas.strategies.sleeve_strategies.research import run_all
    res = run_all(tmp_path, seed=7)
    kinds = {r["kind"] for r in res}
    assert {"strat_cash_yield", "strat_fx_cost", "strat_vol_managed", "strat_trend_switch", "strat_timing_tom",
            "strat_crypto_factors", "strat_pairs"} <= kinds
    assert all(r["model_id"] for r in res)
    from atlas.ops.pipeline_models import ModelSet
    ms = ModelSet(tmp_path)                     # challengers load as SHADOW, never acting
    assert "strat_vol_managed" in ms.shadow and "strat_vol_managed" not in ms.acting
