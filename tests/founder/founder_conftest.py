from __future__ import annotations
import os
os.environ.setdefault("ATLAS_AS_OF", "2026-10-16")  # pin venue-verification date for reproducible tests

import shutil
from pathlib import Path

import pytest

from atlas.governance.audit import AuditLog
from atlas.control.policy import load_all
from atlas.risk import KillSwitch, OrderIntent, PortfolioState, Position, RiskEngine, Watchdog

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "founder"


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture
def cfg():
    return load_all(CONFIG_DIR)


@pytest.fixture
def cfg_dir(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, d)
    return d


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def audit():
    return AuditLog()


@pytest.fixture
def ks(audit):
    return KillSwitch(audit)


@pytest.fixture
def engine(cfg, audit, ks, clock):
    wd = Watchdog(5, 3, ks, clock=clock)
    wd.heartbeat()
    return RiskEngine(cfg.risk, cfg.brokers, audit, ks, wd, clock=clock)


def state(total=100_000.0, cash=20_000.0, positions=None, sod=None, sow=None, peak=None, open_orders=0) -> PortfolioState:
    positions = positions or {}
    eq = cash + sum(p.market_value_base for p in positions.values())
    return PortfolioState(total_account_equity_base=total, bot_cash_base=cash, positions=positions,
                          start_of_day_equity=sod or eq, start_of_week_equity=sow or eq, peak_equity=peak or eq,
                          open_orders=open_orders)


def pos(symbol="SPY", qty=1.0, price=100.0, sleeve="core") -> Position:
    return Position(symbol=symbol, qty=qty, avg_price=price, last_price=price, sleeve=sleeve)


def intent(**kw) -> OrderIntent:
    base = dict(symbol="SPY", side="buy", qty=1, order_type="limit", limit_price=100.0, reference_price=100.0,
                sleeve="core", asset_class="index_etf", broker="alpaca", source="strategy", quote_age_s=0.5)
    base.update(kw)
    return OrderIntent(**base)
