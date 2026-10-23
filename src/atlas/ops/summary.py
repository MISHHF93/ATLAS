"""Daily summary report (BRD §12.7): P&L by sleeve, limits used, fills, notable events,
autonomy rung, tax warnings. Writes Markdown + JSON. Delivery (email/push) is NOT wired:
this offline build writes files only."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from atlas.risk.autonomy import autonomy_status
from atlas.ops.equity import equity_series

from atlas.ops.timez import TORONTO as TOR  # noqa: E402
NOTABLE = ("kill_switch", "risk.breach", "risk.daily_halt", "screener.failure", "screener.verdict", "ml.", "tax.event_error",
           "ops.drill", "reconcile", "anomaly", "dashboard.auth_failed", "watchdog")


def _on(ts: str, d: date) -> bool:
    return datetime.fromisoformat(ts).astimezone(TOR).date() == d


def daily_summary(svc, d: date) -> dict:
    st = svc.get_status()
    snap = svc.broker.snapshot()
    by_sleeve = defaultdict(lambda: {"market_value": 0.0, "unrealized": 0.0, "positions": 0})
    for p in snap.positions.values():
        b = by_sleeve[p.sleeve]
        b["market_value"] += p.market_value_base
        b["unrealized"] += (p.last_price - p.avg_price) * p.qty * p.fx_rate_to_base
        b["positions"] += 1
    entries = svc.audit.entries()
    fills = [e["payload"] for e in entries if e["event"] == "paper.fill" and _on(e["ts"], d)]
    for f in fills:
        by_sleeve[f.get("sleeve") or "?"]["fills"] = by_sleeve[f.get("sleeve") or "?"].get("fills", 0) + 1
    notable = [{"ts": e["ts"], "event": e["event"]} for e in entries
               if _on(e["ts"], d) and any(e["event"].startswith(n) for n in NOTABLE)]
    tax = svc.tax.report() if getattr(svc, "tax", None) else None
    eq = [p for p in equity_series(svc) if _on(p[0], d)]
    out = {
        "date": d.isoformat(), "mode": "paper", "bot_equity": st["bot_equity"], "pnl_today": snap.bot_equity - snap.start_of_day_equity,
        "equity_open_close": [eq[0][1], eq[-1][1]] if eq else None,
        "sleeves": dict(by_sleeve), "fills": len(fills),
        "limits_used": {"daily_loss_pct": st["daily_loss_pct"], "daily_limit_pct": st["daily_loss_limit_pct"],
                        "weekly_loss_pct": st.get("weekly_loss_pct"), "drawdown_pct": st.get("drawdown_pct")},
        "halted": st["halted"], "kill_reason": st["kill_reason"], "pending_approvals": st["pending_approvals"],
        "autonomy": autonomy_status(svc.cfg.risk), "notable_events": notable[-50:],
        "tax_warnings": tax.warnings[-20:] if tax else [], "realized_dispositions_today": sum(1 for x in (tax.dispositions if tax else []) if x.date == d),
        "benchmark": "not computed (needs benchmark data feed)",
    }
    return out


def render_md(s: dict) -> str:
    L = [f"# Daily summary {s['date']} (PAPER)", "",
         f"- Bot equity: ${s['bot_equity']:,.2f}  ·  P&L today: ${s['pnl_today']:+,.2f}  ·  fills: {s['fills']}",
         f"- Daily loss used: {s['limits_used']['daily_loss_pct']:.2f}% of {s['limits_used']['daily_limit_pct']}%"
         f"  ·  drawdown {s['limits_used']['drawdown_pct'] or 0:.2f}%",
         f"- Kill switch: {'ENGAGED: ' + str(s['kill_reason']) if s['halted'] else 'off'}  ·  pending approvals: {s['pending_approvals']}",
         f"- Autonomy: L{s['autonomy']['level']} ({s['autonomy']['profile']}), live locked", "", "| sleeve | positions | value | unrealized | fills |", "|---|---|---|---|---|"]
    for k, v in sorted(s["sleeves"].items()):
        L.append(f"| {k} | {v.get('positions', 0)} | {v.get('market_value', 0):,.2f} | {v.get('unrealized', 0):+,.2f} | {v.get('fills', 0)} |")
    L += ["", "## Notable events"] + ([f"- {e['ts']} {e['event']}" for e in s["notable_events"]] or ["- none"])
    L += ["", "## Tax warnings (not tax advice)"] + ([f"- {w}" for w in s["tax_warnings"]] or ["- none"])
    return "\n".join(L) + "\n"


def write_daily_summary(svc, d: date, out_dir: str | Path = "var/reports") -> Path:
    s = daily_summary(svc, d)
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / f"daily-{d.isoformat()}.json").write_text(json.dumps(s, indent=1, default=str))
    md = p / f"daily-{d.isoformat()}.md"
    md.write_text(render_md(s))
    svc.audit.append("ops.daily_summary", {"date": d.isoformat(), "path": str(md)})
    return md


def main(argv=None) -> None:
    """Generate today's summary from persisted state (audit/state/tax DBs)."""
    import argparse
    from atlas.mcp.trading.service import build_service
    ap = argparse.ArgumentParser(prog="atlas-summary")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--var", default="var")
    ap.add_argument("--date", default=None)
    a = ap.parse_args(argv)
    v = Path(a.var)
    svc = build_service(a.config, str(v / "audit.sqlite"), str(v / "state.sqlite"), tax_db_path=str(v / "tax.sqlite"))
    d = date.fromisoformat(a.date) if a.date else datetime.now(TOR).date()
    print(write_daily_summary(svc, d, v / "reports"))
