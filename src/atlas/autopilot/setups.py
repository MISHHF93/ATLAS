"""Paper autopilot for price-action setups: one on/off switch, paper orders only.

Each tick, for every configured stream, the newest *confirmed* bars go through the live path:

    PriceActionEngine.update -> predict() + EV gate (proposals.evaluate) -> StrategySignal (only if not abstained)
    -> ActionableControlPlaneEngine.ingest_whale_policy_signal (founder rulebook, paper connector)

Only orders the control plane returns as ``authorized_and_executed`` become paper positions. Positions are managed
with the replay fill model (``conservative_ohlc_v1``) and booked back through ``close_position``; nothing reaches a
venue and no money moves (``execution_permission: none`` everywhere).

Switching on needs an approval: ``request_on`` files a request; only the owner with step-up can grant it
(``atlas.control.setup_autopilot_approval``, used by the owner CLI). Switching off is instant and needs nothing. The founder Safe stop (2% daily loss / 10%
drawdown from the founder risk policy, never looser) is checked on every bar using realized plus
floating paper P&L; when it trips, the shared Safe stop is engaged, paper positions are flattened, and the switch
goes off. An engaged Safe stop also blocks switching on. Every decision is appended to a hash-chained audit log
and to the shadow collector. With an empty model registry every candidate abstains, and the reasons are recorded.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence

from atlas.features.price_action import PRESETS, EngineConfig, PriceActionEngine
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.detectors import Candidate
from atlas.features.price_action.proposals import candidate_to_signal, evaluate
from atlas.features.price_action.replay import ReplayConfig, ReplayTrade, _step_trade, trade_cost, try_fill
from atlas.governance.audit import AuditLog
from atlas.models.shadow import ShadowCollector
from atlas.risk.state_store import StateStore

SWITCH = "setup_autopilot.switch"
REQUESTS = "setup_autopilot.requests"
REQUEST_TTL_S = 900
Feed = Callable[[str, int], Sequence[Bar]]


@dataclass(frozen=True)
class Stream:
    symbol: str
    timeframe: int
    session: str | None = None


class PaperConnector:
    """Paper-only connector: acknowledges control-plane-approved orders; never contacts a venue."""

    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []

    def route_approved_order(self, decision: Any, *, tactic: str, reference_price: float, executed_at: datetime) -> dict:
        if decision.control_plane_decision != "authorized_and_executed":
            raise PermissionError("paper connector only accepts control-plane-authorized orders")
        rec = {"venue": "paper", "order_id": decision.order_id, "position_id": decision.position_id,
               "tactic": tactic, "limit_price": reference_price, "accepted_at": executed_at.isoformat(),
               "execution_mode": "paper", "execution_permission": "none"}
        self.receipts.append(rec)
        return rec


class SetupAutopilot:
    def __init__(self, feed: Feed, streams: Sequence[Stream], *, state_db: str = ":memory:",
                 audit_db: str = ":memory:", safe_stop: Any = None, shadow: ShadowCollector | None = None,
                 registry: Any = None, model_version: str | None = None, cost_bps: float = 10.0,
                 starting_equity_usd: Decimal = Decimal("100000"), founder_config_dir: str | None = None,
                 expected_owner: str = "owner", clock: Callable[[], float] = time.time):
        from atlas.control.engine import ActionableControlPlaneEngine
        from atlas.control.founder_track import build_founder_rulebook
        from atlas.risk.safe_stop import new_safe_stop

        self.feed, self.streams, self.clock = feed, list(streams), clock
        self.store, self.audit = StateStore(state_db), AuditLog(audit_db)
        self.safe_stop = safe_stop if safe_stop is not None else new_safe_stop()
        self.shadow = shadow
        self.registry, self.model_version, self.expected_owner = registry, model_version, expected_owner
        self.rcfg = ReplayConfig(cost_bps=cost_bps)
        self.rulebook = build_founder_rulebook(founder_config_dir)
        cp = ActionableControlPlaneEngine(safe_stop=self.safe_stop)
        # A clean paper account under the founder rulebook (the engine's demo book is not used here).
        eq = Decimal(starting_equity_usd)
        cp.open_rulebook, cp.active_track = self.rulebook, "open_market"
        cp.initial_equity_usd = cp.current_equity_usd = cp.high_water_mark_usd = cp.start_of_day_equity_usd = eq
        cp.gross_notional_usd = cp.correlated_exposure_usd = cp.sector_exposure_usd = Decimal("0")
        cp.best_day_profit_usd = cp.total_cumulative_profit_usd = Decimal("0")
        cp.completed_trading_days, cp.open_positions = 0, []
        self.cp, self.connector = cp, PaperConnector()
        self.engines = {s: PriceActionEngine(s.symbol, s.timeframe, EngineConfig(session=PRESETS.get(s.session) if s.session else None))
                        for s in self.streams}
        self.waiting: list[tuple[ReplayTrade, int, dict]] = []   # (trade, age, ctx)
        self.live: list[tuple[ReplayTrade, int, dict]] = []
        self.last_close: dict[str, float] = {}
        self.day: str | None = None
        self.decisions: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    # ---- switch ------------------------------------------------------------------------------------------
    def is_on(self) -> bool:
        return (self.store.get(SWITCH) or {}).get("on", False)

    def request_on(self, actor: str, note: str = "", channel: str = "api") -> dict[str, Any]:
        now = self.clock()
        req = {"id": "sap-" + secrets.token_hex(4), "actor": actor[:60], "note": note[:200], "channel": channel,
               "at": now, "expires": now + REQUEST_TTL_S}
        self.store.update(REQUESTS, lambda old: [r for r in (old or []) if r["expires"] > now][-9:] + [req], [])
        self.audit.append("setup_autopilot.on_requested", {"id": req["id"], "channel": channel}, actor=actor)
        return {**req, "status": "pending_owner_approval"}

    def pending(self) -> list[dict[str, Any]]:
        now = self.clock()
        return [r for r in (self.store.get(REQUESTS) or []) if r["expires"] > now]

    def switch_off(self, actor: str, reason: str = "switched_off") -> dict[str, Any]:
        self.store.set(SWITCH, {"on": False, "by": actor, "reason": reason[:200], "at": self.clock()})
        self.audit.append("setup_autopilot.switched_off", {"reason": reason[:200]}, actor=actor)
        return self.status()

    # ---- risk --------------------------------------------------------------------------------------------
    def _floating(self) -> Decimal:
        tot = Decimal("0")
        for t, _, ctx in self.live:
            px = self.last_close.get(ctx["symbol"])
            if px is None or not t.entry:
                continue
            sign = 1 if t.direction == "long" else -1
            tot += Decimal(str((px - t.entry) / t.entry * sign)) * ctx["notional"]
        return tot

    def risk_view(self) -> dict[str, Any]:
        cp = self.cp
        eq = cp.current_equity_usd + self._floating()
        daily = (cp.start_of_day_equity_usd - eq) / cp.start_of_day_equity_usd
        ref = cp.initial_equity_usd if self.rulebook.drawdown_mode == "static" else cp.high_water_mark_usd
        dd = (ref - eq) / ref
        return {"equity_usd": float(eq), "realized_equity_usd": float(cp.current_equity_usd),
                "start_of_day_equity_usd": float(cp.start_of_day_equity_usd),
                "daily_loss_fraction": float(daily), "drawdown_fraction": float(dd),
                "daily_limit": float(self.rulebook.max_daily_loss_fraction),
                "drawdown_limit": float(self.rulebook.max_drawdown_fraction),
                "safe_stop_engaged": self.safe_stop.engaged, "safe_stop_reason": self.safe_stop.reason}

    def _safety(self, ts: datetime) -> str | None:
        if self.safe_stop.engaged:
            return f"safe_stop_engaged:{self.safe_stop.reason}"
        rv = self.risk_view()
        why = None
        if rv["daily_loss_fraction"] >= rv["daily_limit"]:
            why = f"founder_daily_loss_{rv['daily_loss_fraction']:.4f}>={rv['daily_limit']}"
        elif rv["drawdown_fraction"] >= rv["drawdown_limit"]:
            why = f"founder_drawdown_{rv['drawdown_fraction']:.4f}>={rv['drawdown_limit']}"
        if why:
            self.safe_stop.engage(why, channel="setup_autopilot")
            self.audit.append("setup_autopilot.safe_stop_tripped", {"reason": why, **rv}, actor="setup_autopilot")
        return why

    def _halt(self, reason: str, ts: datetime) -> None:
        for t, _, ctx in list(self.live):
            px = self.last_close.get(ctx["symbol"], t.entry)
            self._book_exit(t, ctx, px, "safe_stop_flatten", ts)
        for t, _, ctx in self.waiting:
            if ctx.get("position_id"):
                self.cp.close_position(ctx["position_id"], exit_price=t.entry, reason="safe_stop_cancel", now=ts)
        self.live, self.waiting = [], [(t, a, c) for t, a, c in self.waiting if not c.get("position_id")]
        self.switch_off("setup_autopilot", reason)

    # ---- bookkeeping -------------------------------------------------------------------------------------
    def _book_exit(self, t: ReplayTrade, ctx: dict, price: float, reason: str, ts: datetime) -> None:
        if ctx.get("position_id"):
            fee = (ctx["notional"] * Decimal(str(self.rcfg.cost_bps)) * Decimal("0.0001")).quantize(Decimal("0.01"))
            res = self.cp.close_position(ctx["position_id"], exit_price=price, fee_usd=fee, reason=reason, now=ts)
            self.audit.append("setup_autopilot.paper_exit", {"candidate_id": t.candidate_id, "reason": reason,
                                                             "exit_price": price, "result": res.get("status")}, actor="setup_autopilot")

    def _resolve(self, t: ReplayTrade, ctx: dict, ts: datetime) -> None:
        if self.shadow is not None:
            self.shadow.resolve(t.candidate_id, outcome=t.outcome, r_multiple=t.r_multiple, exit_at=t.exit_at,
                                ambiguous=t.ambiguous)
        if t.outcome != "unfilled":
            self._book_exit(t, ctx, float(t.exit_price), f"paper_{t.outcome}", ts)
        elif ctx.get("position_id"):
            self.cp.close_position(ctx["position_id"], exit_price=t.entry, reason="entry_unfilled_cancelled", now=ts)

    def _force_close_if_held_too_long(self, t: ReplayTrade, b: Bar) -> None:
        """Founder rulebook max_holding_seconds (owner decision 2026-10-23: 86400 s): force-close at bar close."""
        limit = getattr(self.cp.open_rulebook, "max_holding_seconds", None)
        if limit is None or t.filled_at is None or b.end - t.filled_at < float(limit):
            return
        risk = abs(t.entry - t.stop)
        pnl = (b.close - t.entry) if t.direction == "long" else (t.entry - b.close)
        t.exit_at, t.exit_price, t.outcome = b.start, b.close, "max_holding"
        t.r_multiple = (pnl - trade_cost(t, self.rcfg)) / risk if risk > 0 else None

    def _manage(self, sym: str, b: Bar, ts: datetime) -> None:
        nxt = []
        for t, held, ctx in self.live:
            if ctx["symbol"] != sym:
                nxt.append((t, held, ctx)); continue
            _step_trade(t, b, self.rcfg, held + 1)
            if t.exit_at is None:
                self._force_close_if_held_too_long(t, b)
            if t.exit_at is None:
                nxt.append((t, held + 1, ctx))
            else:
                self._resolve(t, ctx, ts)
        self.live = nxt
        wait = []
        for t, age, ctx in self.waiting:
            if ctx["symbol"] != sym:
                wait.append((t, age, ctx)); continue
            if try_fill(t, b):
                _step_trade(t, b, self.rcfg, 0)
                if t.exit_at is None:
                    self.live.append((t, 0, ctx))
                else:
                    self._resolve(t, ctx, ts)
            elif t.outcome == "gap_skipped":
                t.outcome = "unfilled"                       # stop order cancelled: gapped beyond stop/target
                self._resolve(t, ctx, ts)
            elif age + 1 < self.rcfg.entry_window:
                wait.append((t, age + 1, ctx))
            else:
                self._resolve(t, ctx, ts)
        self.waiting = wait

    def _decide(self, c: Candidate, ts: datetime) -> dict[str, Any]:
        cost = trade_cost(ReplayTrade("", "", c.direction, 0, c.entry_reference, c.proposed_stop, c.proposed_target), self.rcfg)
        pred, ev = evaluate(c, model_version=self.model_version, registry=self.registry, cost_per_unit=cost)
        rec: dict[str, Any] = {"candidate_id": c.candidate_id, "instrument": c.instrument, "detector": c.detector,
                               "direction": c.direction, "detected_at": c.detected_at,
                               "probability": ev.probability, "expected_value_r": ev.expected_value_r,
                               "model_version": getattr(pred, "model_version", None)}
        ctx: dict[str, Any] = {"symbol": c.instrument, "position_id": None, "notional": Decimal("0")}
        if ev.abstained:
            rec.update(decision="abstain", reasons=list(ev.abstention_reason))
        else:
            sig = candidate_to_signal(c, ev)
            rep = self.cp.ingest_whale_policy_signal(sig, track="open_market", execution_connector=self.connector,
                                                     require_connector=True, now=ts, data_age_ms=0.0)
            d = rep.decision
            if d.control_plane_decision == "authorized_and_executed" and rep.connector_receipt:
                ctx.update(position_id=d.position_id, notional=Decimal(d.notional_usd))
                rec.update(decision="proposal_authorized", reasons=[], order_id=d.order_id,
                           notional_usd=float(d.notional_usd))
            else:
                rec.update(decision="proposal_rejected", reasons=list(d.violations) or ["rejected_by_control_plane"],
                           order_id=d.order_id)
        t = ReplayTrade(c.candidate_id, c.detector, c.direction, c.detected_at, c.entry_reference,
                        c.proposed_stop, c.proposed_target, entry_type=c.entry_type)
        self.waiting.append((t, 0, ctx))     # every candidate is tracked; only authorized ones carry a position
        if self.shadow is not None:
            self.shadow.observe(candidate=c, decision=rec["decision"], reasons=rec["reasons"],
                                probability=rec["probability"], expected_value_r=rec["expected_value_r"],
                                model_version=rec["model_version"], order_id=rec.get("order_id"))
        self.audit.append("setup_autopilot.decision", rec, actor="setup_autopilot")
        self.decisions = (self.decisions + [rec])[-200:]
        return rec

    # ---- loop --------------------------------------------------------------------------------------------
    def tick(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            now = self.clock() if now is None else now
            out: dict[str, Any] = {"bars": 0, "decisions": [], "halted": None}
            if not self.is_on():
                return {**out, "state": "off"}
            for s in self.streams:
                eng = self.engines[s]
                try:
                    bars = [b for b in self.feed(s.symbol, s.timeframe) if b.end <= now
                            and (eng.last_start is None or b.start > eng.last_start)]
                except Exception as exc:  # noqa: BLE001  a feed error skips the stream; never trades blind
                    self.audit.append("setup_autopilot.feed_error", {"symbol": s.symbol, "error": str(exc)[:200]}, actor="setup_autopilot")
                    continue
                for b in sorted(bars, key=lambda x: x.start):
                    if not self.is_on():
                        return {**out, "state": "off"}
                    ts = datetime.fromtimestamp(b.end, tz=timezone.utc)
                    day = ts.date().isoformat()
                    if day != self.day:
                        if self.day is not None:
                            self.cp.start_of_day_equity_usd = self.cp.current_equity_usd + self._floating()
                        self.day = day
                    self._manage(s.symbol, b, ts)
                    self.last_close[s.symbol] = b.close
                    out["bars"] += 1
                    why = self._safety(ts)
                    if why:
                        self._halt(why, ts)
                        out["halted"] = why
                        return {**out, "state": "halted"}
                    for ev in eng.update(b, now=int(now)):
                        if isinstance(ev, Candidate):
                            out["decisions"].append(self._decide(ev, ts))
            self.store.set("setup_autopilot.last_tick", {"at": now, "bars": out["bars"]})
            return {**out, "state": "on"}

    def start_background(self, interval_s: float = 60.0) -> None:
        if self._thread and self._thread.is_alive():
            return

        def run() -> None:
            while self.is_on():
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001  fail closed: switch off
                    self.switch_off("setup_autopilot", f"loop_error:{type(exc).__name__}")
                    break
                for _ in range(int(max(1, interval_s))):
                    if not self.is_on():
                        break
                    time.sleep(1)

        self._thread = threading.Thread(target=run, name="setup-autopilot", daemon=True)
        self._thread.start()

    def status(self) -> dict[str, Any]:
        sw = self.store.get(SWITCH) or {"on": False}
        return {"on": bool(sw.get("on")), "switch": {k: sw.get(k) for k in ("by", "reason", "request", "at")},
                "pending_requests": self.pending(), "streams": [s.__dict__ for s in self.streams],
                "risk": self.risk_view(), "open_paper_positions": sum(1 for _, _, c in self.live if c["position_id"]),
                "pending_entries": len(self.waiting), "recent_decisions": self.decisions[-20:],
                "registry_models": len(getattr(self.registry or __import__("atlas.models.predict", fromlist=["x"]).DEFAULT_REGISTRY, "_m", {})),
                "last_tick": self.store.get("setup_autopilot.last_tick"),
                "mode": "paper", "live_trading": "disabled", "execution_permission": "none"}
