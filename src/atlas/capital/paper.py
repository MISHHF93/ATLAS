"""Operator paper capital: deposit, trade, and withdraw on one append-only ledger.

The ledger account ``default_workspace_paper_capital`` is the book of record.
Control-plane equity is a derived snapshot (``is_book_of_record`` is false).
There is no deposit address, no custodian, and no live withdrawal.
The research hand stays unable to buy or sell. Automated strategies do not
spend this cash. An operator order goes through the control plane and cannot
exceed free cash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import uuid
from typing import Any

from atlas.control.engine import ActionableControlPlaneEngine, ActionablePositionRecord
from atlas.investment_intelligence.ledger import InvestmentPortfolioLedger

PAPER_TENANT = "default_workspace"
PAPER_ACCOUNT_ID = "default_workspace_paper_capital"
PAPER_MAX_USD = Decimal("1000000000")
NOTICE = (
    "Append-only paper ledger. Control-plane equity is a snapshot of that ledger. "
    "Orders, closes, and withdrawals stay inside this paper book. "
    "The research hand cannot buy or sell."
)


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _labels() -> dict[str, Any]:
    return {
        "book": "paper_ledger",
        "account_id": PAPER_ACCOUNT_ID,
        "tenant_id": PAPER_TENANT,
        "customer_custody": False,
        "live_withdrawal": False,
        "deposit_address": None,
        "execution_permission": "none",
        "may_propose_order": False,
        "research_hand_can_buy": False,
        "research_hand_can_sell": False,
        "snapshot_is_book_of_record": False,
        "notice": NOTICE,
    }


def ensure_paper_account(ledger: InvestmentPortfolioLedger) -> None:
    ledger.create_account(
        tenant_id=PAPER_TENANT,
        account_id=PAPER_ACCOUNT_ID,
        account_name="Paper capital",
        account_type="paper_ledger",
        base_currency="USD",
        custodian_source="atlas_paper_ledger",
        verification_status="USER_ENTERED",
    )


def _paper_txs(ledger: InvestmentPortfolioLedger) -> list[Any]:
    return ledger.list_transactions(tenant_id=PAPER_TENANT, account_id=PAPER_ACCOUNT_ID)


def capital_status(engine: ActionableControlPlaneEngine, ledger: InvestmentPortfolioLedger) -> dict[str, Any]:
    txs = _paper_txs(ledger)
    cash = Decimal("0")
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    for tx in txs:
        if str(tx.currency).upper() != "USD":
            continue
        cash += Decimal(str(tx.net_cash_impact))
        if tx.tx_type == "DEPOSIT":
            deposits += Decimal(str(tx.gross_amount))
        elif tx.tx_type == "WITHDRAWAL":
            withdrawals += Decimal(str(tx.gross_amount))
    hand = engine.research_hand or {}
    tracked = bool(engine.cash_tracked)
    open_count = sum(1 for pos in engine.open_positions if pos.status == "open")
    return {
        **_labels(),
        "status": "ok",
        "ledger_cash_usd": f"{_money(cash):.2f}",
        "deposits_usd": f"{_money(deposits):.2f}",
        "withdrawals_usd": f"{_money(withdrawals):.2f}",
        "free_cash_usd": f"{_money(engine.cash_usd):.2f}" if tracked else "0.00",
        "equity_usd": f"{_money(engine.current_equity_usd):.2f}" if tracked else "0.00",
        "deposits_loaded": bool(engine.deposits_loaded and tracked),
        "cash_tracked": tracked,
        "open_positions": open_count,
        "transactions": len(txs),
        "research_hand_genome": hand.get("genome_id"),
        "snapshot_source": f"control_plane:{engine.active_track}",
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _refuse(reason: str, engine: ActionableControlPlaneEngine, ledger: InvestmentPortfolioLedger) -> dict[str, Any]:
    return {**capital_status(engine, ledger), "status": "refused", "reason": reason}


def _check_amount(amount: Decimal) -> str | None:
    if not amount.is_finite() or amount <= 0:
        return "amount_must_be_positive"
    if amount > PAPER_MAX_USD:
        return "amount_above_paper_cap"
    return None


def deposit_paper(
    engine: ActionableControlPlaneEngine,
    ledger: InvestmentPortfolioLedger,
    amount: Decimal,
) -> dict[str, Any]:
    amount = _money(amount)
    reason = _check_amount(amount)
    if reason:
        return _refuse(reason, engine, ledger)
    if engine.deposits_loaded and not engine.cash_tracked:
        return _refuse("paper_capital_requires_unfunded_or_tracked_book", engine, ledger)
    ensure_paper_account(ledger)
    salt = uuid.uuid4().hex
    recorded = ledger.record_transaction(
        tenant_id=PAPER_TENANT,
        account_id=PAPER_ACCOUNT_ID,
        tx_type="DEPOSIT",
        trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        gross_amount=float(amount),
        quantity=0.0,
        price=0.0,
        currency="USD",
        verification_status="USER_ENTERED",
        source_provenance="atlas_paper_ledger",
        notes="paper deposit",
        dedup_salt=salt,
    )
    if recorded.get("deduplicated"):
        return _refuse("deposit_not_recorded", engine, ledger)
    engine.apply_external_cash(amount)
    engine.audit_log.append(
        f"{datetime.now(timezone.utc).isoformat()} | paper_deposit | usd={amount} | book=paper_ledger"
    )
    view = capital_status(engine, ledger)
    view["status"] = "deposited"
    view["transaction"] = recorded["transaction"]
    return view


def withdraw_paper(
    engine: ActionableControlPlaneEngine,
    ledger: InvestmentPortfolioLedger,
    amount: Decimal,
) -> dict[str, Any]:
    amount = _money(amount)
    reason = _check_amount(amount)
    if reason:
        return _refuse(reason, engine, ledger)
    if not engine.cash_tracked or not engine.deposits_loaded:
        return _refuse("no_deposited_capital", engine, ledger)
    if amount > engine.cash_usd:
        return _refuse("insufficient_paper_cash", engine, ledger)
    ensure_paper_account(ledger)
    recorded = ledger.record_transaction(
        tenant_id=PAPER_TENANT,
        account_id=PAPER_ACCOUNT_ID,
        tx_type="WITHDRAWAL",
        trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        gross_amount=float(amount),
        quantity=0.0,
        price=0.0,
        currency="USD",
        verification_status="USER_ENTERED",
        source_provenance="atlas_paper_ledger",
        notes="paper withdrawal",
        dedup_salt=uuid.uuid4().hex,
    )
    if recorded.get("deduplicated"):
        return _refuse("withdrawal_not_recorded", engine, ledger)
    engine.apply_external_cash(-amount)
    engine.audit_log.append(
        f"{datetime.now(timezone.utc).isoformat()} | paper_withdrawal | usd={amount} | book=paper_ledger"
    )
    view = capital_status(engine, ledger)
    view["status"] = "withdrawn"
    view["transaction"] = recorded["transaction"]
    return view


def bind_paper_journal(engine: ActionableControlPlaneEngine, ledger: InvestmentPortfolioLedger) -> None:
    """Book each operator fill, close, and flatten onto the paper ledger."""

    def journal(event: dict[str, Any]) -> dict[str, Any]:
        return _journal(ledger, event)

    engine.paper_journal = journal


def _price(value: Any) -> float:
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return float(value)
    return 1.0


def _journal(ledger: InvestmentPortfolioLedger, event: dict[str, Any]) -> dict[str, Any]:
    ensure_paper_account(ledger)
    kind = str(event.get("event") or "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if kind == "fill":
        notional = _money(event["notional_usd"])
        price = _price(event.get("entry_price"))
        qty = round(float(notional) / price, 8)
        notes = json.dumps(
            {
                "atlas_paper": "fill",
                "position_id": event["position_id"],
                "instrument_id": event["instrument_id"],
                "side": event["side"],
                "track": event["track"],
                "stop_kind": event["stop_kind"],
                "stop_bps": str(event["stop_distance_bps"]),
                "entry_price": price,
            },
            sort_keys=True,
        )
        recorded = ledger.record_transaction(
            tenant_id=PAPER_TENANT,
            account_id=PAPER_ACCOUNT_ID,
            tx_type="BUY",
            trade_date=today,
            symbol=str(event["instrument_id"]),
            quantity=qty,
            price=price,
            currency="USD",
            verification_status="USER_ENTERED",
            source_provenance="atlas_paper_ledger",
            notes=notes,
            dedup_salt=f"fill:{event['position_id']}",
        )
        tx = recorded["transaction"]
        return {
            "deduplicated": bool(recorded["deduplicated"]),
            "gross_usd": f"{float(tx['gross_amount']):.2f}",
            "net_cash_usd": f"{float(tx['net_cash_impact']):.2f}",
        }
    if kind in ("close", "flatten"):
        if kind == "flatten":
            notional = _money(event["notional_usd"])
            price = _price(event.get("entry_price"))
            cash_target = notional
            closed = notional
            fraction = 1.0
        else:
            closed = _money(event["closed_notional_usd"])
            pnl = _money(event.get("pnl_usd") or "0")
            fee = _money(event.get("fee_usd") or "0")
            cash_target = _money(closed + pnl)
            price = _price(event.get("exit_price"))
            fraction = float(event.get("fraction") or 1.0)
            fee_float = float(fee)
        qty = round(float(cash_target) / price, 8) if kind == "close" else round(float(notional) / price, 8)
        fee_float = float(_money(event.get("fee_usd") or "0")) if kind == "close" else 0.0
        notes = json.dumps(
            {
                "atlas_paper": kind,
                "position_id": event["position_id"],
                "closed_notional_usd": f"{closed:.2f}",
                "exit_price": price,
                "fraction": fraction,
            },
            sort_keys=True,
        )
        recorded = ledger.record_transaction(
            tenant_id=PAPER_TENANT,
            account_id=PAPER_ACCOUNT_ID,
            tx_type="SELL",
            trade_date=today,
            symbol=str(event["instrument_id"]),
            quantity=qty,
            price=price,
            fee=fee_float,
            currency="USD",
            verification_status="USER_ENTERED",
            source_provenance="atlas_paper_ledger",
            notes=notes,
            dedup_salt=f"{kind}:{event['position_id']}:{closed:.2f}:{price:.8f}:{fraction}",
        )
        tx = recorded["transaction"]
        return {
            "deduplicated": bool(recorded["deduplicated"]),
            "cash_in": f"{float(tx['net_cash_impact']):.2f}",
        }
    raise ValueError(f"unknown paper journal event: {kind}")


def _meta(notes: str) -> dict[str, Any]:
    if not notes or not notes.startswith("{"):
        return {}
    try:
        data = json.loads(notes)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _opened_at(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _bump_seq(engine: ActionableControlPlaneEngine, position_id: str) -> None:
    try:
        number = int(str(position_id).rsplit("-", 1)[-1])
    except ValueError:
        return
    if number > engine._pos_seq:
        engine._pos_seq = number


def _replay_fill(engine: ActionableControlPlaneEngine, tx: Any, meta: dict[str, Any]) -> None:
    gross = _money(tx.gross_amount)
    net = _money(tx.net_cash_impact)
    engine.cash_tracked = True
    engine.deposits_loaded = True
    engine.cash_usd = _money(engine.cash_usd + net)
    engine.current_equity_usd = _money(engine.current_equity_usd + net + gross)
    exposure = _money(gross * Decimal("0.25"))
    engine.gross_notional_usd = _money(engine.gross_notional_usd + gross)
    engine.correlated_exposure_usd = _money(engine.correlated_exposure_usd + exposure)
    engine.sector_exposure_usd = _money(engine.sector_exposure_usd + exposure)
    track = meta.get("track") if meta.get("track") in ("competition", "open_market") else "competition"
    side = meta.get("side") if meta.get("side") in ("buy", "sell") else "buy"
    stop_kind = meta.get("stop_kind") if meta.get("stop_kind") in ("atr", "structure") else "atr"
    engine.open_positions.append(
        ActionablePositionRecord(
            position_id=str(meta["position_id"]),
            track=track,
            instrument_id=str(meta.get("instrument_id") or tx.symbol or "paper"),
            side=side,
            notional_usd=gross,
            stop_kind=stop_kind,
            stop_distance_bps=Decimal(str(meta.get("stop_bps") or "180")),
            opened_at=_opened_at(str(tx.recorded_at)),
            status="open",
            entry_price=_price(meta.get("entry_price")),
        )
    )
    _bump_seq(engine, str(meta["position_id"]))


def _replay_sell(engine: ActionableControlPlaneEngine, tx: Any, meta: dict[str, Any]) -> None:
    released = _money(meta.get("closed_notional_usd") or "0")
    cash_in = _money(tx.net_cash_impact)
    pnl = _money(cash_in - released)
    engine.cash_tracked = True
    engine.cash_usd = _money(engine.cash_usd + cash_in)
    engine.current_equity_usd = _money(engine.current_equity_usd + pnl)
    if engine.current_equity_usd > engine.high_water_mark_usd:
        engine.high_water_mark_usd = engine.current_equity_usd
    if engine.high_water_mark_usd < engine.initial_equity_usd:
        engine.high_water_mark_usd = engine.initial_equity_usd
    cut = _money(released * Decimal("0.25"))
    engine.gross_notional_usd = max(Decimal("0"), _money(engine.gross_notional_usd - released))
    engine.correlated_exposure_usd = max(Decimal("0"), _money(engine.correlated_exposure_usd - cut))
    engine.sector_exposure_usd = max(Decimal("0"), _money(engine.sector_exposure_usd - cut))
    position_id = str(meta.get("position_id") or "")
    status = "flattened" if meta.get("atlas_paper") == "flatten" else "closed"
    updated: list[ActionablePositionRecord] = []
    for pos in engine.open_positions:
        if pos.position_id != position_id or pos.status != "open":
            updated.append(pos)
            continue
        remaining = _money(pos.notional_usd - released)
        if remaining <= 0 or status == "flattened":
            updated.append(pos.model_copy(update={"status": status}))
        else:
            updated.append(pos.model_copy(update={"notional_usd": remaining}))
    engine.open_positions = updated


def replay_paper_capital(
    engine: ActionableControlPlaneEngine,
    ledger: InvestmentPortfolioLedger,
) -> dict[str, Any]:
    """Rebuild the control-plane snapshot from the paper ledger.

    The funded in-memory demo book is left unchanged. An empty paper account
    leaves an unfunded engine unfunded.
    """
    if engine.deposits_loaded and not engine.cash_tracked:
        view = capital_status(engine, ledger)
        view["status"] = "skipped"
        view["reason"] = "funded_demo_book"
        return view
    txs = _paper_txs(ledger)
    if not txs:
        view = capital_status(engine, ledger)
        view["status"] = "empty"
        return view
    hand = engine.research_hand
    journal = engine.paper_journal
    engine.paper_journal = None
    engine.unload_deposits()
    engine.research_hand = hand
    for tx in txs:
        meta = _meta(tx.notes)
        if tx.tx_type == "DEPOSIT":
            engine.apply_external_cash(_money(tx.gross_amount))
        elif tx.tx_type == "WITHDRAWAL":
            engine.apply_external_cash(-_money(tx.gross_amount))
        elif tx.tx_type == "BUY" and meta.get("atlas_paper") == "fill":
            _replay_fill(engine, tx, meta)
        elif tx.tx_type == "SELL" and meta.get("atlas_paper") in ("close", "flatten"):
            _replay_sell(engine, tx, meta)
    engine.paper_journal = journal
    engine.research_hand = hand
    open_left = any(pos.status == "open" for pos in engine.open_positions)
    if engine.cash_usd <= 0 and engine.current_equity_usd <= 0 and not open_left:
        engine.unload_deposits()
        engine.research_hand = hand
        engine.paper_journal = journal
    view = capital_status(engine, ledger)
    view["status"] = "replayed"
    return view
