"""Deterministic risk gate: the only path from an OrderIntent to execution.

The policy object is a frozen pydantic model held privately; there is no
method to modify it. Limits change only by restarting with a new, validated,
signature-verified config.
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Callable

from atlas.governance.audit import AuditLog
from atlas.control.policy.schemas import BrokersCfg, RiskPolicy
from atlas.risk.safety import assert_paper_only
from atlas.risk.anomaly import AnomalyMonitor
from atlas.risk.fx import FxRateProvider, StaticFxProvider
from atlas.risk.killswitch import KillSwitch
from atlas.risk.models import OrderIntent, PortfolioState, RiskDecision
from atlas.risk.ratelimit import SharedWindowLimiter
from atlas.risk.state_store import StateStore
from atlas.risk.watchdog import Watchdog

EPS = 1e-9
UNKNOWN_SECTOR = "unknown"
SECTORLESS = frozenset({"index_etf", "etf", "crypto_spot", "fx", "fx_spot", "cash_equivalent"})
from atlas.ops.timez import TORONTO as SESSION_TZ  # noqa: E402  sessions roll on the exchange-local (ET) date, not box/UTC date


def session_today() -> str:
    return datetime.now(SESSION_TZ).date().isoformat()


def _loss_pct(anchor: float, eq: float) -> float:
    """Loss vs an anchor. Non-finite input => 100% (fail closed: trips the limits). A non-positive
    anchor means there is nothing to lose (bot capital is 0, so sizing blocks every buy anyway)."""
    if not (math.isfinite(anchor) and math.isfinite(eq)):
        return 100.0
    if anchor <= 0:
        return 0.0
    return max(0.0, (anchor - eq) / anchor * 100)
DAILY_HALT_KEY = "daily_halt_session"
FX_TOLERANCE = 0.02  # intent fx rate may differ from provider by at most 2%


class RiskEngine:
    def __init__(self, policy: RiskPolicy, brokers: BrokersCfg, audit: AuditLog,
                 kill_switch: KillSwitch, watchdog: Watchdog,
                 clock: Callable[[], float] = time.monotonic,
                 fx: FxRateProvider | None = None, anomaly: AnomalyMonitor | None = None,
                 store: StateStore | None = None, external_watchdog: Callable[[], bool] | None = None,
                 hooks: list | None = None):
        assert_paper_only()
        self.__policy = policy
        self._brokers = brokers
        self._audit = audit
        self.ks = kill_switch
        self.watchdog = watchdog
        self._clock = clock
        self.fx = fx or StaticFxProvider(base=policy.base_currency)
        anomaly_cfg = getattr(policy, "anomaly_halts", None) or {}
        self.anomaly = anomaly or AnomalyMonitor.from_policy(kill_switch, anomaly_cfg)
        self.store = store or StateStore()
        self.external_watchdog = external_watchdog
        self.hooks = list(hooks or [])  # pre-trade hooks: (intent, state) -> (failures, warnings)
        self._rate = SharedWindowLimiter(self.store, policy.position_limits.max_orders_per_minute, 60.0,  # cross-process budget
                                         clock=time.time if clock is time.monotonic else clock)
        self.session: str = self.store.get("session_date", session_today())

    @property
    def policy(self) -> RiskPolicy:  # read-only view (frozen model)
        return self.__policy

    # ---------------------------------------------------------------- session
    @property
    def daily_halted(self) -> bool:
        return self.store.get(DAILY_HALT_KEY) == self.session

    def roll_session(self, session_date: str) -> None:
        """Start a new trading session: clears the daily-loss latch (not the kill switch)."""
        self.session = session_date
        self.store.set("session_date", session_date)
        self._audit.append("risk.session_roll", {"session": session_date})

    # ---------------------------------------------------------------- helpers
    def bot_capital(self, s: PortfolioState) -> float:
        cap = self.policy.capital.allocation_cap_pct / 100 * s.total_account_equity_base
        return max(0.0, min(s.bot_equity, cap))

    def loss_metrics(self, s: PortfolioState) -> dict[str, float]:
        eq = s.bot_equity
        return {
            "daily_loss_pct": _loss_pct(s.start_of_day_equity, eq),
            "weekly_loss_pct": _loss_pct(s.start_of_week_equity, eq),
            "drawdown_pct": _loss_pct(s.peak_equity, eq),
        }

    # ---------------------------------------------------------------- gate
    def evaluate(self, intent: OrderIntent, state: PortfolioState, record_rate: bool = True) -> RiskDecision:
        p = self.policy
        pl, ll = p.position_limits, p.loss_limits
        base = p.base_currency
        checks: dict[str, bool] = {}
        reasons: list[str] = []
        warnings: list[str] = []

        def chk(name: str, ok: bool, why: str) -> None:
            checks[name] = bool(ok)
            if not ok:
                reasons.append(f"{name}: {why}")

        try:
            # 1. halts (fail closed)
            wd_ok = self.watchdog.check()
            if self.external_watchdog is not None:
                ext = bool(self.external_watchdog())
                chk("external_watchdog", ext, "external watchdog process not alive")
                if not ext and not self.ks.engaged:
                    self.ks.engage("external watchdog not alive", "watchdog")
            chk("kill_switch", not self.ks.engaged, f"engaged ({self.ks.reason})")
            chk("watchdog", wd_ok, "heartbeat stale or missing")

            # 2. venue / mode
            plat = self._brokers.platforms.get(intent.broker)
            chk("broker", plat is not None and plat.enabled and plat.mode == "paper",
                f"broker {intent.broker!r} unknown, disabled or not paper")

            # 3. sleeve
            sl = p.sleeves.get(intent.sleeve)
            chk("sleeve_defined", sl is not None, f"undefined sleeve {intent.sleeve!r}")
            if sl is not None:
                chk("sleeve_unlocked", not sl.locked and sl.max_pct > 0, f"sleeve {intent.sleeve!r} locked")
                if sl.instruments:
                    chk("sleeve_instrument", intent.asset_class in sl.instruments,
                        f"{intent.asset_class!r} not allowed in sleeve {intent.sleeve!r}")

            pos = state.positions.get(intent.symbol)
            held = pos.qty if pos else 0.0
            increasing = intent.side == "buy"

            # 4. no shorting
            if intent.side == "sell":
                pend = state.pending_sell_qty.get(intent.symbol, 0.0)  # resting sells already commit part of the holding
                chk("no_short", intent.qty + pend <= held + EPS,
                    f"sell {intent.qty} + open sells {pend} > held {held} (shorting disabled)")

            # 5. quote freshness, price collar
            ref = intent.reference_price
            chk("reference_price", ref is not None, "no reference price")
            chk("stale_quote", self.anomaly.quote_fresh(intent.quote_age_s),
                f"quote age {intent.quote_age_s} > {self.anomaly.stale_quote_seconds}s or unknown")
            if ref is not None and intent.order_type == "limit":
                dev = abs(intent.limit_price - ref) / ref * 100  # type: ignore[operator]
                chk("price_collar", dev <= pl.price_collar_pct + EPS,
                    f"limit {intent.limit_price} deviates {dev:.2f}% > {pl.price_collar_pct}% from ref {ref}")

            # 6. FX rate (provider is the source of truth; fail closed)
            fx_rate = self.fx.rate(intent.currency, base)
            fx_ok = math.isfinite(fx_rate) and fx_rate > 0 and math.isfinite(intent.fx_rate_to_base)
            chk("fx_rate", fx_ok and abs(intent.fx_rate_to_base - fx_rate) / fx_rate <= FX_TOLERANCE,
                f"intent fx {intent.fx_rate_to_base} vs provider {fx_rate} for {intent.currency}/{base}")

            # 7. loss limits (block risk-increasing orders; reducing allowed)
            lm = self.loss_metrics(state)
            if lm["daily_loss_pct"] >= ll.daily_pct and not self.daily_halted:
                self.store.set(DAILY_HALT_KEY, self.session)
                self._audit.append("risk.daily_halt", {"session": self.session, **lm})
            if increasing:
                chk("daily_loss", not self.daily_halted,
                    f"daily loss limit hit this session ({lm['daily_loss_pct']:.2f}% now, limit {ll.daily_pct}%)")
                chk("weekly_loss", lm["weekly_loss_pct"] < ll.weekly_pct, f"weekly loss {lm['weekly_loss_pct']:.2f}% >= {ll.weekly_pct}%")
                chk("max_drawdown", lm["drawdown_pct"] < ll.max_drawdown_pct, f"drawdown {lm['drawdown_pct']:.2f}% >= {ll.max_drawdown_pct}%")

            # 8. order rate / open orders
            now = self._clock()
            chk("order_rate", self._rate.would_allow(now), f"> {pl.max_orders_per_minute} orders/min")
            chk("open_orders", state.open_orders < pl.max_open_orders, f"open orders {state.open_orders} >= {pl.max_open_orders}")

            # 9. sizing / concentration on risk-increasing orders
            if increasing and ref is not None:
                px = intent.limit_price if intent.order_type == "limit" else ref
                notional = intent.qty * px * fx_rate  # type: ignore[operator]
                bot_cap = self.bot_capital(state)
                issuer_key = intent.issuer or intent.symbol
                new_issuer = state.issuer_exposure(issuer_key) + notional
                if pos is not None and pos.issuer_key != issuer_key:
                    new_issuer += pos.market_value_base
                chk("no_leverage_cash", notional <= state.bot_cash_base + EPS, f"cost {notional:.2f} > cash {state.bot_cash_base:.2f}")
                chk("settled_cash", notional <= state.settled_cash + EPS,
                    f"cost {notional:.2f} > settled cash {state.settled_cash:.2f} (cash account, avoid GFV)")
                chk("max_position_pct", new_issuer <= pl.max_position_pct_bot_capital / 100 * bot_cap + EPS,
                    f"issuer {issuer_key} {new_issuer:.2f} > {pl.max_position_pct_bot_capital}% of bot capital {bot_cap:.2f}")
                chk("max_position_notional", new_issuer <= pl.max_position_notional_base + EPS,
                    f"issuer {issuer_key} {new_issuer:.2f} > {pl.max_position_notional_base}")
                new_gross = state.gross_exposure_base + notional
                chk("max_gross_exposure", new_gross <= pl.max_gross_exposure_pct / 100 * bot_cap + EPS,
                    f"gross {new_gross:.2f} > {pl.max_gross_exposure_pct}% of bot capital")
                cap_abs = p.capital.allocation_cap_pct / 100 * state.total_account_equity_base
                chk("bot_capital_cap", new_gross <= cap_abs + EPS,
                    f"bot exposure {new_gross:.2f} > {p.capital.allocation_cap_pct}% of account equity ({cap_abs:.2f})")
                if sl is not None:
                    new_sleeve = state.sleeve_exposure(intent.sleeve) + notional
                    chk("sleeve_allocation", new_sleeve <= sl.max_pct / 100 * bot_cap + EPS,
                        f"sleeve {intent.sleeve} {new_sleeve:.2f} > {sl.max_pct}% of bot capital")
                if intent.currency != base:
                    new_ccy = state.currency_exposure(intent.currency) + notional
                    non_base = sum(q.market_value_base for q in state.positions.values() if q.currency != base) + notional
                    chk("single_currency", new_ccy <= pl.max_single_currency_pct / 100 * bot_cap + EPS,
                        f"{intent.currency} exposure {new_ccy:.2f} > {pl.max_single_currency_pct}% of bot capital")
                    chk("net_fx_exposure", non_base <= pl.max_net_fx_exposure_pct / 100 * bot_cap + EPS,
                        f"non-{base} exposure {non_base:.2f} > {pl.max_net_fx_exposure_pct}% of bot capital")
                # Single names with an unknown sector share one "unknown" bucket under the sector cap
                # (was: check skipped). Diversified wrappers (index ETFs, crypto spot, FX) have no single
                # sector and stay exempt; their concentration is bounded by position/sleeve caps.
                sec = intent.sector or (None if intent.asset_class in SECTORLESS else UNKNOWN_SECTOR)
                if sec:
                    new_sec = state.sector_exposure(sec, SECTORLESS) + notional
                    chk("sector", new_sec <= pl.max_sector_pct / 100 * bot_cap + EPS,
                        f"sector {sec} {new_sec:.2f} > {pl.max_sector_pct}% of bot capital")
            # 10. pre-trade hooks (venue eligibility, tax guard, ...)
            for h in self.hooks:
                fails, warns = h(intent, state)
                warnings.extend(warns)
                chk(getattr(h, "name", "hook"), not fails, "; ".join(fails))
        except Exception as e:  # any error in the gate => reject
            chk("internal_error", False, repr(e))

        approved = all(checks.values()) and bool(checks)
        if approved and record_rate:
            self._rate.record(self._clock())
        decision = RiskDecision(intent_id=intent.intent_id, approved=approved, reasons=reasons, checks=checks,
                                halted=self.ks.engaged, policy_version=p.version, warnings=warnings)
        self._audit.append("risk.decision", {"intent": intent.model_dump(), "decision": decision.model_dump()},
                           actor=intent.source)
        self._post_breach_actions(state)
        return decision

    def check_breaches(self, state: PortfolioState) -> None:
        """Call on every mark-to-market (heartbeat / backtest bar), not only on new intents."""
        lm = self.loss_metrics(state)
        if lm["daily_loss_pct"] >= self.policy.loss_limits.daily_pct and not self.daily_halted:
            self.store.set(DAILY_HALT_KEY, self.session)
            self._audit.append("risk.daily_halt", {"session": self.session, **lm})
        self._post_breach_actions(state)

    def _post_breach_actions(self, state: PortfolioState) -> None:
        """Weekly loss / max drawdown => halt until owner review (kill switch)."""
        lm = self.loss_metrics(state)
        ll = self.policy.loss_limits
        if not self.ks.engaged:
            if lm["weekly_loss_pct"] >= ll.weekly_pct:
                self.ks.engage(f"weekly loss limit breached ({lm['weekly_loss_pct']:.2f}%)", channel="risk_engine")
            elif lm["drawdown_pct"] >= ll.max_drawdown_pct:
                self.ks.engage(f"max drawdown breached ({lm['drawdown_pct']:.2f}%)", channel="risk_engine")
