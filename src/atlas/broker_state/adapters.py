"""Read-only broker state adapters. One interface, one adapter per broker.

``BrokerStateAdapter.fetch(env) -> AccountSnapshot``. Rules shared by every adapter:
* paper / practice / simulated endpoints only (live hosts are refused, never contacted);
* a network adapter does nothing (no request at all) until Settings -> Verify has marked that broker's key ``verified``;
* only GET requests; no order, cancel or transfer call exists in this module;
* errors become a snapshot with ``status="error"`` and a short reason, never an exception to the caller and never a secret."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Protocol

from atlas.broker_state.snapshot import (AccountSnapshot, Balances, FeeSchedule, MarketState, OrderView, PositionView, TradingRules,
                                         mask, now_iso, num, unavailable)

OANDA_PRACTICE_HOST = "api-fxpractice.oanda.com"
OANDA_LIVE_HOSTS = {"api-fxtrade.oanda.com", "stream-fxtrade.oanda.com"}
GetJson = Callable[[str, dict[str, str]], Any]     # (url, headers) -> parsed JSON; GET only


class BrokerStateAdapter(Protocol):
    broker: str
    environment: str

    def fetch(self, env: Mapping[str, str]) -> AccountSnapshot: ...


def verification_state(service_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Secret-free state from the same store the Settings Verify button writes (needs_verification | verified | failed | ...)."""
    from atlas.integrations import verify as v
    from atlas.integrations.registry import SERVICES
    svc = next((s for s in SERVICES if s.id == service_id), None)
    return v.state_for(svc, dict(env)) if svc else {"state": "needs_verification", "detail": f"unknown service {service_id}"}


def _gate(broker: str, environment: str, service_id: str, env: Mapping[str, str]) -> AccountSnapshot | None:
    st = verification_state(service_id, env)
    if st.get("state") == "verified":
        return None
    if st.get("state") == "failed":
        return unavailable(broker, environment, "verification_failed", st.get("detail") or "The last Verify failed; fix the key and press Verify.")
    return unavailable(broker, environment, "needs_verification", st.get("detail") or "Enter the key in Settings and press Verify.")


def _urlopen_get(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, method="GET", headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:  # noqa: S310 - host is guarded to the practice endpoint by the caller
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None


# --------------------------------------------------------------------------------------------------------- paper sim
class PaperSimAdapter:
    """ATLAS's own in-memory paper book (``execution.paper.broker.PaperBroker``): no network, always available."""
    broker, environment = "paper_sim", "simulated"

    def __init__(self, book: Any | None = None, start_equity: float | None = None, currency: str = "CAD"):
        from atlas.execution.paper.broker import PaperBroker
        if book is None:
            eq = float(start_equity if start_equity is not None else os.environ.get("ATLAS_PAPER_START_EQUITY", "100"))
            book = PaperBroker(total_account_equity_base=eq, bot_cash_base=eq)
        self.book, self.currency = book, currency

    def fetch(self, env: Mapping[str, str] | None = None) -> AccountSnapshot:
        b = self.book
        eq, cash = b.bot_equity(), b.bot_cash_base
        pos = [PositionView(symbol=k, qty=p.qty, avg_price=p.avg_price, market_value=p.market_value_base,
                            unrealized_pl=(p.last_price - p.avg_price) * p.qty * p.fx_rate_to_base, asset_class=p.asset_class)
               for k, p in b.positions.items()]
        orders = [OrderView(order_id=o.order_id, symbol=o.intent.symbol, side=o.intent.side, qty=o.intent.qty,
                            order_type=o.intent.order_type, status="open") for o in b.open_orders.values()]
        c = b.costs
        snap = AccountSnapshot(
            broker=self.broker, environment=self.environment, currency=self.currency, account_ref="sim",
            balances=Balances(cash=cash, equity=eq, buying_power=b.settled_cash, settled_cash=b.settled_cash, leverage_max=1.0),
            positions=pos, open_orders=orders,
            rules=TradingRules(min_order_notional=1.0, fractional=True, shorting_allowed=False, margin_enabled=False, pdt_applies=False,
                               settlement_days=1, notes=["Simulated cash account: long-only, no margin; equities settle T+1, crypto/FX T+0.",
                                                          "Minimum order of 1.00 is an ASSUMPTION that mirrors Alpaca's $1 notional minimum; real brokers differ."]),
            fees=FeeSchedule(commission_per_order=c.commission_per_order, spread_bps_assumed=c.slippage_bps,
                             notes=["Paper cost model: flat commission per order plus adverse slippage; mirror the real broker's schedule before trusting results."]),
            market=MarketState(source="not_modelled"))
        if cash < 0:
            snap.warnings.append("negative cash in the paper book")
        return snap


# --------------------------------------------------------------------------------------------------------- Alpaca paper
class AlpacaPaperStateAdapter:
    """Alpaca PAPER account, positions, open orders and market clock. Idle until Alpaca keys are verified. Alpaca is optional
    (not offered to Canadian residents); this adapter exists for users whose own account allows it."""
    broker, environment = "alpaca", "paper"

    def __init__(self, transport: Any | None = None):
        self.transport = transport

    def fetch(self, env: Mapping[str, str]) -> AccountSnapshot:
        gated = _gate(self.broker, self.environment, "alpaca", env)
        if gated:
            return gated
        from atlas.execution.adapters.alpaca import AlpacaPaperBroker
        b = AlpacaPaperBroker(env=dict(env), transport=self.transport)
        if b.adapter is None:
            return unavailable(self.broker, self.environment, "refused_live" if b.status == "refused_live_endpoint" else "not_configured", b.reason)
        acct = b._read("/v2/account")
        if acct["status"] != "ok":
            st = "refused_live" if acct["status"] in ("refused_live_account", "refused_live_endpoint") else "error"
            return unavailable(self.broker, self.environment, st, str(acct.get("reason") or acct["status"]))
        a = acct["data"] or {}
        pos, orders, clock = b._read("/v2/positions"), b._read("/v2/orders?status=open&limit=100"), b._read("/v2/clock")
        snap = AccountSnapshot(
            broker=self.broker, environment=self.environment, currency=a.get("currency"), account_ref=mask(a.get("account_number")),
            balances=Balances(cash=num(a.get("cash")), equity=num(a.get("equity")), buying_power=num(a.get("buying_power")),
                              margin_used=num(a.get("initial_margin")), leverage_max=num(a.get("multiplier"))),
            rules=TradingRules(min_order_notional=1.0, fractional=True, shorting_allowed=a.get("shorting_enabled"),
                               margin_enabled=(num(a.get("multiplier")) or 1) > 1, pdt_applies=bool(a.get("pattern_day_trader")) or None,
                               pdt_note="Alpaca flag pattern_day_trader; the FINRA $25k PDT rule was retired 2026-06-04 (Reg Notice 26-10), broker policy may differ.",
                               trading_blocked=bool(a.get("trading_blocked") or a.get("account_blocked")),
                               notes=["Fractional and notional orders need a market/day order; $1 minimum notional (Alpaca docs)."]),
            fees=FeeSchedule(commission_per_order=0.0, notes=["Commission-free US equities; SEC/FINRA/CAT pass-through fees apply (Alpaca fee schedule)."]),
            market=MarketState(source="alpaca /v2/clock"))
        for p in (pos["data"] or []) if pos["status"] == "ok" else []:
            q = num(p.get("qty")) or 0.0
            snap.positions.append(PositionView(symbol=p.get("symbol", "?"), qty=abs(q), side=p.get("side") or ("long" if q >= 0 else "short"),
                                               avg_price=num(p.get("avg_entry_price")), market_value=num(p.get("market_value")),
                                               unrealized_pl=num(p.get("unrealized_pl")), asset_class=p.get("asset_class")))
        for o in (orders["data"] or []) if orders["status"] == "ok" else []:
            snap.open_orders.append(OrderView(order_id=str(o.get("id", "")), symbol=o.get("symbol", "?"), side=o.get("side", "?"), qty=num(o.get("qty")),
                                              notional=num(o.get("notional")), order_type=o.get("type"), status=o.get("status"), submitted_at=o.get("submitted_at")))
        if clock["status"] == "ok" and clock["data"]:
            c = clock["data"]
            snap.market = MarketState(is_open=c.get("is_open"), next_open=c.get("next_open"), next_close=c.get("next_close"), source="alpaca /v2/clock")
        for name, r in (("positions", pos), ("orders", orders), ("clock", clock)):
            if r["status"] != "ok":
                snap.warnings.append(f"{name} unavailable: {r.get('reason') or r['status']}")
        return snap


# --------------------------------------------------------------------------------------------------------- OANDA practice
class OandaPracticeStateAdapter:
    """OANDA v20 PRACTICE account summary, open positions and pending orders. Idle until the OANDA token is verified.
    The live host (api-fxtrade.oanda.com) is refused."""
    broker, environment = "oanda", "practice"

    def __init__(self, get_json: GetJson | None = None, instrument: str = "EUR_USD"):
        self.get_json, self.instrument = get_json or _urlopen_get, instrument

    def fetch(self, env: Mapping[str, str]) -> AccountSnapshot:
        if (env.get("OANDA_ENV") or "practice").lower() == "live":
            return unavailable(self.broker, self.environment, "refused_live", "OANDA_ENV=live is refused; ATLAS only reads the practice account.")
        gated = _gate(self.broker, self.environment, "oanda", env)
        if gated:
            return gated
        from atlas.integrations import oanda_v20 as O
        token, acct_id = env.get("OANDA_API_TOKEN", ""), (env.get("OANDA_ACCOUNT_ID") or "").strip()
        if not token:
            return unavailable(self.broker, self.environment, "not_configured", "OANDA_API_TOKEN is needed for the account snapshot (OANDA_ACCOUNT_ID is optional: it is discovered from the token).")
        h = {"Authorization": f"Bearer {token}"}
        note = ""
        try:
            O.refuse_live(env)
            if not acct_id or not O.PRACTICE_ID.fullmatch(acct_id):
                acct_id, note = O.pick_account("", O.discover_account_ids(self.get_json, token))
            if not acct_id:
                return unavailable(self.broker, self.environment, "not_configured", "OANDA: " + (note or "no practice account found for this token"))
            base = f"https://{OANDA_PRACTICE_HOST}/v3/accounts/{acct_id}"
            a = (self.get_json(base + "/summary", h) or {}).get("account") or {}
        except O.OandaLiveRefused as ex:
            return unavailable(self.broker, self.environment, "refused_live", str(ex)[:200])
        except Exception as ex:  # noqa: BLE001
            return unavailable(self.broker, self.environment, "error", f"{type(ex).__name__}: {ex}"[:200])
        warnings: list[str] = [note] if note else []

        def opt(path: str, key: str) -> list[dict]:
            try:
                return list((self.get_json(base + path, h) or {}).get(key) or [])
            except Exception as ex:  # noqa: BLE001
                warnings.append(f"{key} unavailable: {type(ex).__name__}: {ex}"[:120])
                return []
        positions, orders = opt("/openPositions", "positions"), opt("/pendingOrders", "orders")
        inst = next(iter(opt(f"/instruments?instruments={self.instrument}", "instruments")), {})
        mr = num(a.get("marginRate"))
        snap = AccountSnapshot(
            broker=self.broker, environment=self.environment, currency=a.get("currency"), account_ref=mask(acct_id), warnings=warnings,
            balances=Balances(cash=num(a.get("balance")), equity=num(a.get("NAV")), margin_used=num(a.get("marginUsed")),
                              margin_available=num(a.get("marginAvailable")), buying_power=num(a.get("marginAvailable")),
                              leverage_max=(1.0 / mr) if mr else None),
            rules=TradingRules(min_order_qty=num(inst.get("minimumTradeSize")), fractional=None, shorting_allowed=True, margin_enabled=True,
                               pdt_applies=False, settlement_days=0,
                               notes=[f"Units, not dollars: minimum trade size and precision come from /instruments (shown for {self.instrument}); margin rate is per instrument.",
                                      "Account marginRate is the account default; each instrument can differ."]),
            fees=FeeSchedule(notes=["No separate commission modelled: cost is the spread (read /pricing); financing accrues on overnight positions."]),
            market=MarketState(source="not_modelled (per-instrument 'tradeable' flag in /pricing)"))
        for p in positions:
            lq, sq = num((p.get("long") or {}).get("units")) or 0.0, num((p.get("short") or {}).get("units")) or 0.0
            snap.positions.append(PositionView(symbol=p.get("instrument", "?"), qty=abs(lq if lq else sq), side="long" if lq else "short",
                                               unrealized_pl=num(p.get("unrealizedPL")), asset_class="fx"))
        for o in orders:
            snap.open_orders.append(OrderView(order_id=str(o.get("id", "")), symbol=o.get("instrument", "?"), side="buy" if (num(o.get("units")) or 0) >= 0 else "sell",
                                              qty=abs(num(o.get("units")) or 0.0), order_type=str(o.get("type", "")).lower() or None, status=o.get("state"),
                                              submitted_at=o.get("createTime")))
        return snap


REGISTRY: dict[str, Callable[..., BrokerStateAdapter]] = {"paper_sim": PaperSimAdapter, "alpaca": AlpacaPaperStateAdapter, "oanda": OandaPracticeStateAdapter}
