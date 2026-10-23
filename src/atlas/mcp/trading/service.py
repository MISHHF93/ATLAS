"""Transport-agnostic tool implementations used by the MCP server.

Exposed over MCP: get_status, get_positions, get_risk_limits, list_approvals,
get_bars / get_quote / compute_indicators (read-only research over the local bar store),
propose_order (decision + optional owner-approval ticket; never executes),
kill_switch (engage only). NOT exposed: policy changes, kill-switch reset,
approvals, execution, mode changes. Owner-only methods live here for the CLI.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from atlas.governance.audit import AuditLog
from atlas.control.policy import LoadedConfig, load_all
from atlas.execution.paper import PaperBroker
from atlas.execution.paper.broker import Fill
from atlas.risk import KillSwitch, OrderIntent, RiskEngine, Watchdog
from atlas.risk.anomaly import AnomalyMonitor
from atlas.risk.approvals import ApprovalQueue
from atlas.risk.reconcile import Ledger, reconcile
from atlas.risk.state_store import StateStore
from atlas.risk.safety import assert_paper_only


PAPER_STATE_KEY = "paper_state"

class TradingService:
    def __init__(self, cfg: LoadedConfig, broker: PaperBroker, audit: AuditLog,
                 clock: Callable[[], float] = time.monotonic, store: StateStore | None = None,
                 external_watchdog: Callable[[], bool] | None = None, adapters: dict[str, Any] | None = None,
                 hooks: list | None = None, tax_db_path: str = ":memory:", config_dir: str | Path | None = None):
        assert_paper_only()
        self.cfg = cfg
        self.broker = broker
        self.audit = audit
        self.store = store or StateStore()
        self.ks = KillSwitch(audit, on_engage=[broker.cancel_all], store=self.store)
        wd = cfg.risk.watchdog
        self.watchdog = Watchdog(wd.heartbeat_interval_s, wd.missed_beats_to_halt, self.ks, clock=clock)
        self.anomaly = AnomalyMonitor.from_policy(self.ks, getattr(cfg.risk, "anomaly_halts", {}) or {}, clock)
        self.engine = RiskEngine(cfg.risk, cfg.brokers, audit, self.ks, self.watchdog, clock=clock,
                                 anomaly=self.anomaly, store=self.store, external_watchdog=external_watchdog,
                                 hooks=list(hooks or []))
        if cfg.venues is not None:
            from atlas.control.policy.venues import EligibilityHook
            self.engine.hooks.insert(0, EligibilityHook(cfg.venues))
        # tax ledger wired to fills + superficial-loss pre-trade check (warn by default)
        from atlas.tax.config import TaxCfg
        from atlas.tax.ledger import TaxLedger
        from atlas.tax.guard import SuperficialLossGuard
        tcfg = cfg.tax or TaxCfg()
        self.tax = TaxLedger.from_config(tcfg, config_dir or ".", db_path=tax_db_path)
        if tcfg.superficial_loss_guard != "off":
            self.engine.hooks.append(SuperficialLossGuard(self.tax.engine, self.tax.events, self.tax.entity,
                                                          mode=tcfg.superficial_loss_guard))
        approval_clock = time.time if clock is time.monotonic else clock  # wall clock: shared across processes
        self.approvals = ApprovalQueue(cfg.risk.autonomy.approval_ttl_seconds, cfg.risk.owner, audit, approval_clock, self.store)
        self.ks.add_on_flatten(broker.flatten_all)
        from atlas.execution.adapters.router import ExecutionRouter
        self.router = ExecutionRouter(self.engine, adapters or {}, audit, fallback=broker)
        import os as _os
        self.models_root = _os.environ.get("ATLAS_MODELS_DIR", "var/models")
        saved = self.store.get(PAPER_STATE_KEY)
        if saved:  # restart: restore broker (positions, open orders, anchors, settlements) and recon ledger
            broker.load_state(saved["broker"])
            self.ledger = Ledger(cash=saved["ledger"]["cash"], positions=dict(saved["ledger"]["positions"]))
            audit.append("paper.state_restored", {"positions": len(broker.positions), "open_orders": len(broker.open_orders)})
        else:
            self.ledger = Ledger(cash=broker.bot_cash_base, positions=broker.positions_qty())
        broker.fill_listeners.append(self._on_fill)
        audit.append("service.start", {"mode": "paper", "config_digests": cfg.digests})

    @property
    def approval_required(self) -> bool:
        a = self.cfg.risk.autonomy
        return a.level < a.approval_required_below_level

    def persist(self) -> None:
        """Save paper broker + reconciliation ledger to the shared StateStore (called on every fill,
        session roll and loop tick) so a restart resumes with true start-of-day anchors."""
        self.store.set(PAPER_STATE_KEY, {"broker": self.broker.to_state(),
                                         "ledger": {"cash": self.ledger.cash, "positions": self.ledger.positions}})

    def _on_fill(self, f: Fill) -> None:
        self.ledger.apply_fill(f.symbol, f.side, f.qty, f.cash_delta)
        try:
            self.persist()
        except Exception as e:  # noqa: BLE001
            self.audit.append("paper.persist_error", {"error": repr(e)[:200]})
        self.anomaly.on_fill(f.price, f.reference_price)
        self.audit.append("paper.fill", f.__dict__)
        try:
            t = self.tax.on_fill(f)
            self.audit.append("tax.event", {"id": t.id, "property": t.property, "side": t.side, "fx_source": t.fx.source})
        except Exception as e:  # noqa: BLE001  never break trading bookkeeping; flag loudly
            self.audit.append("tax.event_error", {"order_id": f.order_id, "error": str(e)})

    def heartbeat(self) -> None:
        self.watchdog.heartbeat()

    def reconcile(self) -> list[str]:
        return reconcile(self.ledger, self.broker.positions_qty(), self.broker.bot_cash_base, self.ks, self.audit)

    def roll_session(self, d: date) -> None:
        self.broker.roll_day(d)
        self.engine.roll_session(d.isoformat())
        self.persist()

    def ensure_session(self, now) -> bool:
        """Roll broker anchors + the daily-loss latch when the America/Toronto date changes.
        The long-running loop must call this; without it the daily latch and start-of-day equity
        would never reset in the live paper service. Returns True if a roll happened."""
        from atlas.risk.engine import SESSION_TZ
        d = now.astimezone(SESSION_TZ).date()
        if self.engine.session == d.isoformat() and self.broker.today == d:
            return False
        self.roll_session(d)
        return True

    # ---------------------------------------------------------------- MCP tools
    def get_status(self) -> dict[str, Any]:
        s = self.broker.snapshot()
        lm = self.engine.loss_metrics(s)
        bot_cap = self.engine.bot_capital(s)
        ll = self.cfg.risk.loss_limits
        return {
            "mode": "paper", "live_available": False,
            "halted": self.ks.engaged, "kill_switch": self.ks.engaged, "kill_reason": self.ks.reason,
            "daily_halted": self.engine.daily_halted, "session": self.engine.session,
            "watchdog_healthy": self.watchdog.healthy(),
            "bot_equity": s.bot_equity, "bot_capital": bot_cap, "cash": s.bot_cash_base, "settled_cash": s.settled_cash,
            **lm, "daily_loss_limit_pct": ll.daily_pct,
            "loss_limit_used_pct": lm["daily_loss_pct"] / ll.daily_pct * 100,
            "gross_exposure_pct": (s.gross_exposure_base / bot_cap * 100) if bot_cap else 0.0,
            "open_orders": s.open_orders, "pending_approvals": len(self.approvals.pending()),
        }

    def get_positions(self) -> list[dict[str, Any]]:
        return [p.model_dump() | {"market_value_base": p.market_value_base} for p in self.broker.positions.values()]

    def get_risk_limits(self) -> dict[str, Any]:
        r = self.cfg.risk
        return {"read_only": True, "policy_version": r.version, "capital": r.capital.model_dump(),
                "sleeves": {k: v.model_dump() for k, v in r.sleeves.items()},
                "loss_limits": r.loss_limits.model_dump(), "position_limits": r.position_limits.model_dump(),
                "watchdog": r.watchdog.model_dump(), "approval_required": self.approval_required}

    def list_approvals(self) -> list[dict[str, Any]]:
        return [{"approval_id": p.approval_id, "intent": p.intent.model_dump(), "expires_in_s": p.expires - self.approvals.clock()}
                for p in self.approvals.pending()]

    # read-only research (offline: local point-in-time bar store, paper book)
    @property
    def bar_store(self):
        if not hasattr(self, "_bar_store"):
            import os as _os
            root = _os.environ.get("ATLAS_DATA_DIR")
            if root and Path(root).is_dir():
                from atlas.marketdata.pit.store import ParquetBarStore
                self._bar_store = ParquetBarStore(root)
            else:
                self._bar_store = None
        return self._bar_store

    @bar_store.setter
    def bar_store(self, store) -> None:
        self._bar_store = store

    def get_bars(self, symbol: str, limit: int = 200) -> dict[str, Any]:
        from atlas.mcp.trading.research import get_bars
        return get_bars(self.bar_store, symbol, limit)

    def get_quote(self, symbol: str) -> dict[str, Any]:
        from atlas.mcp.trading.research import get_quote
        return get_quote(self.broker, self.bar_store, symbol)

    def compute_indicators(self, symbol: str, indicators: list[dict], lookback: int = 200) -> dict[str, Any]:
        from atlas.mcp.trading.research import compute_indicators
        return compute_indicators(self.bar_store, symbol, indicators, lookback)

    def propose_order(self, **fields: Any) -> dict[str, Any]:
        fields = {k: v for k, v in fields.items() if v is not None} | {"source": "ai"}  # AI cannot impersonate owner
        try:
            intent = OrderIntent(**fields)
        except Exception as e:
            self.audit.append("risk.intent_invalid", {"fields": fields, "error": str(e)}, actor="ai")
            return {"approved": False, "executes": False, "reasons": [f"invalid intent: {e}"]}
        d = self.engine.evaluate(intent, self.broker.snapshot(), record_rate=False)
        out = d.model_dump() | {"executes": False}
        if d.approved and self.approval_required:
            p = self.approvals.enqueue(intent)
            out |= {"status": "pending_owner_approval", "approval_id": p.approval_id, "ttl_s": self.approvals.ttl_s}
        out["note"] = "Decision only. AI cannot approve or execute orders."
        return out

    def kill_switch(self, reason: str, flatten: bool = False) -> dict[str, Any]:
        # Flatten is an OWNER choice (policy: flatten_positions_default false); the AI can only halt.
        res = self.ks.engage(reason or "unspecified", channel="mcp", flatten=False)
        return res | {"flatten_requested": flatten,
                      "note": "flatten ignored over MCP; owner can flatten via CLI/dashboard" if flatten else ""}

    # ---------------------------------------------------------------- owner-only (CLI/dashboard; not MCP)
    def _execute(self, intent: OrderIntent) -> dict:
        return self.router.execute(intent, self.broker.snapshot())  # risk re-checked inside the router

    def owner_approve(self, approval_id: str, owner: str, step_up_verified: bool) -> dict[str, Any]:
        return self.approvals.approve(approval_id, owner, step_up_verified, self._execute)

    def process_owner_actions(self) -> dict[str, Any]:
        """Core loop: execute owner-approved items and owner flatten requests written by the CLI/dashboard."""
        self.engine.check_breaches(self.broker.snapshot())
        if self.ks.engaged and self.broker.open_orders:  # halted from another process (CLI/watchdog)
            self.broker.cancel_all("kill switch engaged externally")
        done = self.approvals.process_owner_approved(self._execute)
        flat = self.store.pop("flatten_request")
        flattened = 0
        if flat:
            flattened = self.ks.engage(flat.get("reason", "owner flatten"), channel=flat.get("channel", "cli"), flatten=True)["flattened_positions"]
        return {"approvals_processed": len(done), "flattened": flattened}


def build_service(config_dir: str | Path = "config/founder", audit_path: str = ":memory:", state_path: str = ":memory:",
                  total_equity: float = 100_000.0, verify_signature: bool = True, tax_db_path: str = ":memory:") -> TradingService:
    cfg = load_all(config_dir, verify_signature=verify_signature)
    cap = cfg.risk.capital.allocation_cap_pct / 100 * total_equity
    return TradingService(cfg, PaperBroker(total_account_equity_base=total_equity, bot_cash_base=cap),
                          AuditLog(audit_path), store=StateStore(state_path), config_dir=config_dir,
                          tax_db_path=tax_db_path)
