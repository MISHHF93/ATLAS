"""Owner CLI for API keys (local only): create | list | revoke. The plaintext key is printed once.

    python -m atlas.keys.cli create --name claude-desktop --scope read [--rate 60]
    python -m atlas.keys.cli list
    python -m atlas.keys.cli revoke <key_id>
"""
from __future__ import annotations

import argparse
import json

from atlas.keys.api_keys import SCOPES, ApiKeyStore


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atlas.keys.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--name", required=True)
    c.add_argument("--scope", choices=SCOPES, required=True); c.add_argument("--rate", type=int, default=60)
    sub.add_parser("list")
    r = sub.add_parser("revoke"); r.add_argument("key_id")
    a = ap.parse_args(argv)
    st = ApiKeyStore()
    if a.cmd == "create":
        key, rec = st.create(a.name, a.scope, a.rate)
        print(json.dumps(rec, indent=1)); print("API key (shown once, store it in your client):"); print(key)
    elif a.cmd == "list":
        print(json.dumps(st.list(), indent=1))
    else:
        ok = st.revoke(a.key_id); print("revoked" if ok else "not found or already revoked")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
