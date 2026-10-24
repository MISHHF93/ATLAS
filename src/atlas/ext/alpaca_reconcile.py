"""Reconcile the Alpaca PAPER account into ATLAS: equity/cash, positions, orders and fills, with checks.

Read-only: nothing here places, changes or cancels an order. Orders ATLAS sent carry client_order_id ``atlas-<id>``
(the control-plane order id); any other order on the paper account is flagged ``outside_control_plane``.
Checks are reported, never auto-corrected:
* each fill belongs to a known order;
* per symbol, net filled quantity from the fills window vs the position quantity (only when the window is complete);
* every ATLAS order has a control-plane id."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

EXECUTION_PERMISSION = "none"


def _f(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def reconcile(broker, fills_limit: int = 100) -> dict[str, Any]:
    acct = broker.get_account()
    base = {"paper_only": True, "execution_permission": EXECUTION_PERMISSION, "order_gate": "ActionableControlPlaneEngine.submit_order"}
    if acct["status"] != "ok":
        return {**base, "status": acct["status"], "reason": acct.get("reason"), "account": None, "positions": [], "orders": [], "fills": [], "checks": []}
    pos_r, ord_r, fill_r = broker.get_positions(), broker.get_orders("all"), broker.get_fills(fills_limit)
    errs = {k: r.get("reason") or r["status"] for k, r in (("positions", pos_r), ("orders", ord_r), ("fills", fill_r)) if r["status"] != "ok"}
    a = acct["data"] or {}
    account = {"account_number": a.get("account_number"), "status": a.get("status"), "currency": a.get("currency"),
               "equity": _f(a.get("equity")), "cash": _f(a.get("cash")), "buying_power": _f(a.get("buying_power")),
               "portfolio_value": _f(a.get("portfolio_value"))}
    positions = [{"symbol": p.get("symbol"), "qty": _f(p.get("qty")), "side": p.get("side"), "avg_entry_price": _f(p.get("avg_entry_price")),
                  "market_value": _f(p.get("market_value")), "unrealized_pl": _f(p.get("unrealized_pl"))} for p in (pos_r.get("data") or [])]
    orders = []
    for o in ord_r.get("data") or []:
        cid = str(o.get("client_order_id") or "")
        orders.append({"id": o.get("id"), "client_order_id": cid, "symbol": o.get("symbol"), "side": o.get("side"), "qty": _f(o.get("qty")),
                       "filled_qty": _f(o.get("filled_qty")), "type": o.get("type"), "order_class": o.get("order_class"), "status": o.get("status"),
                       "submitted_at": o.get("submitted_at"), "filled_avg_price": _f(o.get("filled_avg_price")),
                       "control_plane_order_id": cid[len("atlas-"):] if cid.startswith("atlas-") else None,
                       "origin": "atlas_control_plane" if cid.startswith("atlas-") else "outside_control_plane"})
    fills = [{"id": f.get("id"), "order_id": f.get("order_id"), "symbol": f.get("symbol"), "side": f.get("side"), "qty": _f(f.get("qty")),
              "price": _f(f.get("price")), "time": f.get("transaction_time")} for f in (fill_r.get("data") or [])]
    checks = []
    known = {o["id"] for o in orders}
    orphan = [f["id"] for f in fills if f["order_id"] not in known]
    checks.append({"check": "fills_match_orders", "ok": not orphan and "orders" not in errs,
                   "detail": "all fills belong to a listed order" if not orphan else f"{len(orphan)} fill(s) for orders outside the 100-order window"})
    outside = [o["id"] for o in orders if o["origin"] != "atlas_control_plane"]
    checks.append({"check": "orders_via_control_plane", "ok": not outside,
                   "detail": "every order carries an atlas- control-plane id" if not outside else f"{len(outside)} order(s) placed outside ATLAS (e.g. Alpaca dashboard)"})
    window_complete = len(fills) < fills_limit
    net: dict[str, float] = defaultdict(float)
    for f in fills:
        net[f["symbol"]] += (f["qty"] or 0) * (1 if f["side"] == "buy" else -1)
    pos_q = {p["symbol"]: (p["qty"] or 0) * (-1 if p["side"] == "short" and (p["qty"] or 0) > 0 else 1) for p in positions}
    if window_complete:
        mism = sorted(s for s in set(net) | set(pos_q) if abs(net.get(s, 0) - pos_q.get(s, 0)) > 1e-6)
        checks.append({"check": "positions_match_fills", "ok": not mism,
                       "detail": "net filled qty equals position qty per symbol" if not mism else "mismatch: " + ", ".join(mism)})
    else:
        checks.append({"check": "positions_match_fills", "ok": None, "detail": "fill history longer than the window; not compared"})
    return {**base, "status": "ok" if not errs else "partial", "errors": errs, "account": account, "positions": positions,
            "orders": orders, "fills": fills, "checks": checks}
