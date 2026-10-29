"""Operator CLI (local only):  python -m atlas.accounts.cli <command>

  gen-master-key            print a fresh ATLAS_MASTER_KEY (store it in your .env or secret manager; it is never committed)
  create-owner EMAIL        create / promote the owner account (password read from a prompt, never argv)
  set-role EMAIL admin|user change a role (the owner role is only granted here)
  rewrap                    move every wrapped data key to the current ATLAS_MASTER_KEY (after setting ATLAS_MASTER_KEY_PREVIOUS)
  verify-audit              verify the audit hash chain
  create-invite [EMAIL]     mint a registration invite as the owner (the code is printed once; only its hash is stored)
  print-pg-schema           print the Postgres DDL (ledger immutability triggers rendered as a plpgsql guard)
  migrate-pg                apply the Postgres migrations to ATLAS_DATABASE_URL (needs psycopg; the app itself still runs on SQLite)
"""
from __future__ import annotations

import getpass
import sys

from . import audit, auth, connectors, crypto
from .db import connect, tx


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    cmd = a[0] if a else ""
    if cmd == "gen-master-key":
        print(crypto.generate_master_key())
        return 0
    if cmd == "print-pg-schema":
        from .dialect import render_schema
        print(render_schema("postgresql")); return 0
    if cmd == "migrate-pg":
        from . import dialect
        url = dialect.database_url()
        if not url:
            print("set ATLAS_DATABASE_URL (postgresql://...)"); return 1
        try:
            import psycopg
        except ImportError:
            print("psycopg is not installed: pip install 'psycopg[binary]'"); return 1
        with psycopg.connect(url) as pg:
            print("applied:", dialect.apply_postgres(pg))
        return 0
    with connect() as conn:
        if cmd == "create-invite" and len(a) in (1, 2):
            owner = conn.execute("SELECT id FROM users WHERE role='owner'").fetchone()
            if not owner:
                print("create the owner first (create-owner EMAIL)"); return 1
            from . import onboarding
            inv = onboarding.create_invite(conn, auth.get_user(conn, owner["id"]), a[1] if len(a) == 2 else None, send=False)
            print(f"invite code (shown once): {inv['code']}"); return 0
        if cmd == "create-owner" and len(a) == 2:
            email = auth.normalize_email(a[1])
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if conn.execute("SELECT 1 FROM users WHERE role='owner' AND email<>?", (email,)).fetchone():
                print("an owner already exists"); return 1
            if row:
                with tx(conn):
                    conn.execute("UPDATE users SET role='owner', email_verified=1 WHERE id=?", (row["id"],))
                    audit.log(conn, None, "cli.promote_owner", "user", row["id"])
                print("promoted existing user to owner"); return 0
            pw = getpass.getpass("Password (min 12 chars): ")
            if pw != getpass.getpass("Repeat: "):
                print("passwords differ"); return 1
            import os
            env = dict(os.environ, ATLAS_OWNER_EMAIL=email)
            u = auth.register(conn, email, pw, env=env, verified=True)
            print(f"created {u.role} {u.email}"); return 0
        if cmd == "set-role" and len(a) == 3 and a[2] in ("admin", "user"):
            email = auth.normalize_email(a[1])
            with tx(conn):
                n = conn.execute("UPDATE users SET role=? WHERE email=? AND role<>'owner'", (a[2], email)).rowcount
                audit.log(conn, None, "cli.set_role", "user", email, detail={"role": a[2], "changed": n})
            print("ok" if n else "no change"); return 0 if n else 1
        if cmd == "rewrap":
            print(connectors.rewrap_all(conn)); return 0
        if cmd == "verify-audit":
            r = audit.verify_chain(conn); print(r); return 0 if r["ok"] else 1
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main())
