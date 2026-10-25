#!/usr/bin/env python
"""Read-only connectivity check for ATLAS third-party services. Places NO orders and sends NO alerts.

Runs: Alpaca PAPER account + clock (live endpoint/accounts refused), SEC EDGAR submissions test, FRED series test,
then prints configured/mode for every other service. Secret values are never printed.

    python scripts/check_integrations.py            # human-readable
    python scripts/check_integrations.py --json     # machine-readable
Exit code: 0 if every configured probe passed (unconfigured ones are skipped), 1 otherwise."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, probes=None) -> int:
    from atlas.integrations.registry import load_env, status
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--live-crypto", action="store_true", help="optional live smoke: keyless Alpaca crypto bars (BTC/USD)")
    a = ap.parse_args(argv)
    env = load_env(a.env_file) if env is None else env
    rep = status(env=env, probe=True, probes=probes)
    failed = [r["id"] for r in rep["services"] if r["probe_available"] and r["configured"] and r["reachable"] is False]
    refused = rep["summary"]["live_refused"]
    if a.json:
        print(json.dumps({**rep, "failed": failed}, indent=2))
    else:
        print("ATLAS integrations check (read-only; no orders, no alerts sent)\n")
        for r in rep["services"]:
            reach = {True: "reachable", False: "UNREACHABLE", None: "-"}[r["reachable"]]
            missing = [k for k, ok in r["required_vars"].items() if not ok]
            print(f"  {r['id']:<16} {'configured' if r['configured'] else 'not set':<11} {r['mode']:<13} {reach:<12} "
                  f"{r['detail'] if r['probe_available'] else ''}{('  missing: ' + ', '.join(missing)) if missing else ''}")
        print("\nChecklist: still missing (add to .env, then restart the server)")
        todo = [r for r in rep["services"] if not r["configured"]]
        for r in todo:
            need = [k for k, ok in r["required_vars"].items() if not ok] or list(r["optional_vars"])
            print(f"  [ ] {r['title']} ({r['cost'].replace('_', ' ')}): {', '.join(need)}" + (f"  -> {r['signup']}" if r["signup"] else ""))
        if not todo:
            print("  nothing missing")
        print(f"\n{rep['summary']['configured']}/{rep['summary']['total']} configured; probes failed: {failed or 'none'}; live refused: {refused or 'none'}")
    if a.live_crypto:
        from atlas.api.integrations_api import alpaca_bars
        r = alpaca_bars("BTCUSDT", "1h", 5, crypto=True, environ=env)
        print(f"\nLive Alpaca crypto smoke (keyless, read-only): {r['status']} {len(r['bars'])} bars provider={r.get('provider')}")
        if r["status"] != "ok":
            failed.append("alpaca_crypto_live")
    return 1 if failed or refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
