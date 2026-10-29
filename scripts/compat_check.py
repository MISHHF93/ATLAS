#!/usr/bin/env python
"""Account compatibility check: ONE read-only verify call per configured provider, then a status table.

Providers: Massive, OANDA practice, Alpaca public crypto (keyless), Bank of Canada + ECB FX (keyless), Gemini key status.
Table columns: provider | configured | verified | data flowing | notes. Secret values are never printed, only yes/no and states.
No orders, no alerts, no writes except the existing Verify state file. Paper/practice only; execution_permission stays none.

    python scripts/compat_check.py            # table
    python scripts/compat_check.py --json
    python scripts/compat_check.py --no-network   # configured + stored state + store freshness only"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
STORE = ROOT / "var" / "feeds" / "atlas_feed.sqlite"


def store_flow(provider: str, store: Path = STORE, now: float | None = None) -> dict:
    """Read-only look at the bar store (mode=ro: never blocks the ingest writer)."""
    now = time.time() if now is None else now
    if not Path(store).exists():
        return {"bars": 0, "latest": None, "age_h": None}
    try:
        db = sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=5)
        try:
            n, last = db.execute("SELECT COUNT(*), MAX(event_time) FROM bar_revisions WHERE provider=?", (provider,)).fetchone()
        finally:
            db.close()
    except sqlite3.Error as ex:
        return {"bars": 0, "latest": None, "age_h": None, "error": type(ex).__name__}
    return {"bars": int(n or 0), "latest": int(last) if last else None, "age_h": round((now - last) / 3600, 1) if last else None}


def _flow_text(f: dict) -> str:
    if not f["bars"]:
        return "no bars stored yet"
    return f"{f['bars']} bars stored; newest {f['age_h']} h old"


def _probe(adapter_cls, instrument: str, interval: str, span_s: int, env: dict | None = None) -> tuple[bool, str]:
    now = int(time.time())
    try:
        bars = adapter_cls(env=env or {}).history(instrument, interval, now - span_s, now)
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {str(ex)[:90]}"
    return bool(bars), f"{len(bars)} {interval} bars for {instrument}" if bars else f"0 bars returned for {instrument}"


def run(env: dict[str, str], network: bool = True, verify_fn=None, probe_fn=None, flow_fn=store_flow) -> list[dict]:
    from atlas.integrations import verify as V
    from atlas.integrations.registry import _is_set
    verify_fn, probe_fn = verify_fn or V.verify, probe_fn or _probe
    rows: list[dict] = []

    def keyed(label: str, sid: str, required: tuple[str, ...], provider: str | None, notes: str = "") -> None:
        configured = all(_is_set(env, k) for k in required)
        row = {"provider": label, "configured": configured, "verified": "no key", "data_flowing": "-", "notes": notes}
        if configured:
            if network:
                r = verify_fn(sid, env, throttle=False)
                row["verified"] = r["state"]
                row["notes"] = (r.get("detail") or "")[:140] + (f" | {notes}" if notes else "")
            else:
                st = V.state_for(next(s for s in __import__("atlas.integrations.registry", fromlist=["SERVICES"]).SERVICES if s.id == sid), env)
                row["verified"] = st["state"] + " (stored, not re-checked)"
        else:
            row["notes"] = "Enter " + ", ".join(k for k in required if not _is_set(env, k)) + " in Settings -> Setup, then Verify." + (f" {notes}" if notes else "")
        if provider:
            row["data_flowing"] = _flow_text(flow_fn(provider))
        rows.append(row)

    keyed("Massive (stocks/ETFs)", "polygon", ("POLYGON_API_KEY",), "polygon", "free plan: end-of-day lag, 5 calls/min")
    keyed("OANDA practice (FX/XAU/indices)", "oanda", ("OANDA_API_TOKEN",), "oanda", "practice hosts only; OANDA_ACCOUNT_ID optional (discovered)")
    # Gemini: status only (key present + tier); the verify call is the read-only model list.
    keyed("Gemini (reviewer LLM)", "gemini", ("GEMINI_API_KEY",), None,
          f"ATLAS_GEMINI_TIER={'paid' if (env.get('ATLAS_GEMINI_TIER') or '').lower() == 'paid' else 'not paid: reviewer refuses to run'}")
    from atlas.feeds.providers.alpaca import AlpacaCryptoAdapter
    from atlas.feeds.providers.boc import BankOfCanadaFXAdapter
    from atlas.feeds.providers.ecb import ECBFXAdapter
    for label, prov, cls, inst, itv, span in (("Alpaca public crypto (no key)", "alpaca_crypto", AlpacaCryptoAdapter, "BTCUSDT", "1h", 6 * 3600),
                                              ("Bank of Canada Valet (no key)", "boc_valet", BankOfCanadaFXAdapter, "USD_CAD", "1d", 10 * 86400),
                                              ("ECB FX (no key)", "ecb_fx", ECBFXAdapter, "EUR_USD", "1d", 10 * 86400)):
        row = {"provider": label, "configured": True, "verified": "keyless", "data_flowing": _flow_text(flow_fn(prov)), "notes": ""}
        if network:
            ok, msg = probe_fn(cls, inst, itv, span)
            row["verified"] = "ok" if ok else "failed"
            row["notes"] = "live read-only probe: " + msg
        rows.append(row)
    return rows


def table(rows: list[dict]) -> str:
    cols = ("provider", "configured", "verified", "data_flowing", "notes")
    head = "| " + " | ".join(c.replace("_", " ") for c in cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(("yes" if r[c] is True else "no" if r[c] is False else str(r[c])).replace("|", "/") for c in cols) + " |" for r in rows)


def main(argv: list[str] | None = None) -> int:
    from atlas.integrations.registry import load_env
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args(argv)
    env = load_env(a.env_file)
    rows = run(env, network=not a.no_network)
    print(json.dumps(rows, indent=2) if a.json else table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
