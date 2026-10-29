"""Portfolio intelligence: exposure, correlation, historical VaR/CVaR and stress, over the control plane's open
paper positions and the feed's daily closes. Reuses library.historical_var_es. Read-only; never sizes or approves.

If there are no open positions the report still shows per-instrument risk per $10,000 notional (labelled as such),
never an invented book. Stress = (a) each instrument's own worst historical daily return in the window and
(b) labelled HYPOTHETICAL shocks; neither is a forecast."""
from __future__ import annotations

from typing import Any

import numpy as np

from atlas.features.price_action.library import historical_var_es

UNIT_NOTIONAL = 10_000.0
CLASS = {"GC": "metals", "MGC": "metals", "SI": "metals", "HG": "metals", "ES": "equity_index", "NQ": "equity_index",
         "SPY": "equity_index", "QQQ": "equity_index", "BTCUSDT": "crypto", "ETHUSDT": "crypto", "CL": "energy"}
HYPOTHETICAL_SHOCKS = {"equity_index -7%": {"equity_index": -0.07}, "metals -5%": {"metals": -0.05},
                       "crypto -15%": {"crypto": -0.15}, "risk-off combo": {"equity_index": -0.05, "crypto": -0.12, "metals": 0.02}}


def daily_returns(feed, symbols, limit: int = 260) -> dict[str, dict[int, float]]:
    out = {}
    for s in symbols:
        try:
            rows = [(int(b.event_time // 86400), b.close) for b in feed.bars(s, "1d")] if feed is not None else []
        except KeyError:            # instrument id not in the feed's master (e.g. a control-plane-only id)
            rows = []
        rows = rows[-(limit + 1):]
        out[s] = {d1: float(np.log(c1 / c0)) for (d0, c0), (d1, c1) in zip(rows, rows[1:]) if c0 > 0 and c1 > 0}
    return out


def correlation(rets: dict[str, dict[int, float]], min_overlap: int = 20) -> dict[str, Any]:
    syms = [s for s in rets if rets[s]]
    mat = []
    for a in syms:
        row = []
        for b in syms:
            common = sorted(set(rets[a]) & set(rets[b]))
            if len(common) < min_overlap:
                row.append(None); continue
            x = np.array([rets[a][d] for d in common]); y = np.array([rets[b][d] for d in common])
            row.append(None if x.std() == 0 or y.std() == 0 else round(float(np.corrcoef(x, y)[0, 1]), 3))
        mat.append(row)
    return {"symbols": syms, "matrix": mat, "min_overlap_days": min_overlap,
            "note": "Pearson on overlapping daily log returns; crypto trades weekends, so overlap uses common dates only"}


def report(feed, positions: list[dict[str, Any]], universe: list[str]) -> dict[str, Any]:
    pos = [p for p in positions if p.get("status", "open") == "open"]
    syms = sorted(set(universe) | {p["instrument_id"] for p in pos})
    rets = daily_returns(feed, syms)
    signed: dict[str, float] = {}
    for p in pos:
        signed[p["instrument_id"]] = signed.get(p["instrument_id"], 0.0) + float(p["notional_usd"]) * (1 if p["side"] == "buy" else -1)
    gross = sum(abs(v) for v in signed.values())
    by_class: dict[str, dict[str, float]] = {}
    for s, v in signed.items():
        c = by_class.setdefault(CLASS.get(s, "other"), {"gross": 0.0, "net": 0.0})
        c["gross"] += abs(v); c["net"] += v
    per = []
    for s in syms:
        r = list(rets[s].values())
        v95 = historical_var_es(r, 0.95); v99 = historical_var_es(r, 0.99)
        per.append({"symbol": s, "asset_class": CLASS.get(s, "other"), "n_days": len(r),
                    "var95_per_10k": None if not v95 else round(v95["var"] * UNIT_NOTIONAL, 2),
                    "cvar95_per_10k": None if not v95 else round(v95["cvar"] * UNIT_NOTIONAL, 2),
                    "var99_per_10k": None if not v99 else round(v99["var"] * UNIT_NOTIONAL, 2),
                    "worst_day_pct": round(min(r) * 100, 2) if r else None,
                    "data": "ok" if r else "no_feed_daily_series"})
    book: dict[str, Any] = {"status": "no_open_positions", "unpriced_positions": [], "n_days": 0, "var95_usd": None, "cvar95_usd": None,
                            "var99_usd": None, "stress": []}   # same shape as a priced book, so the UI never sees missing keys
    if signed:
        days = sorted(set().union(*[set(rets[s]) for s in signed]))
        pnl = [sum(signed[s] * (np.expm1(rets[s][d]) if d in rets[s] else 0.0) for s in signed) for d in days]
        v95, v99 = historical_var_es(pnl, 0.95), historical_var_es(pnl, 0.99)
        stress = [{"scenario": f"own worst day ({s})", "kind": "historical",
                   "pnl_usd": round(sum(signed[k] * np.expm1(min(rets[s].values())) for k in signed if k == s), 2)}
                  for s in signed if rets[s]]
        for name, shock in HYPOTHETICAL_SHOCKS.items():
            stress.append({"scenario": name, "kind": "hypothetical",
                           "pnl_usd": round(sum(v * shock.get(CLASS.get(s, "other"), 0.0) for s, v in signed.items()), 2)})
        unpriced = [s for s in signed if not rets[s]]
        book = {"status": "ok" if not unpriced else "partial", "unpriced_positions": unpriced, "n_days": len(pnl), "var95_usd": v95 and round(v95["var"], 2), "cvar95_usd": v95 and round(v95["cvar"], 2),
                "var99_usd": v99 and round(v99["var"], 2), "stress": stress}
        from atlas.ext.var import parametric_var   # normal (variance-covariance) VaR on the same daily book P&L
        p95, p99 = parametric_var(pnl, 0.95), parametric_var(pnl, 0.99)
        book.update({"param_var95_usd": p95 and round(p95["var"], 2), "param_cvar95_usd": p95 and round(p95["cvar"], 2),
                     "param_var99_usd": p99 and round(p99["var"], 2), "cvar99_usd": v99 and round(v99["cvar"], 2)})
    return {"positions": pos, "exposure": {"gross_usd": gross, "net_usd": sum(signed.values()), "by_symbol": signed, "by_class": by_class},
            "per_instrument": per, "correlation": correlation(rets), "book": book, "execution_permission": "none",
            "note": "historical simulation on feed daily closes; per-$10k figures are unit risk, not a position"}
