"""atlas-payments CLI (SIMULATION ONLY). Approvals prompt for passphrase + TOTP."""
from __future__ import annotations
import argparse, getpass, json, os
from pathlib import Path
from atlas.ledgers import audit
from atlas.ledgers.costs import Costs
from atlas.ledgers.manual import Manual
from atlas.ledgers.db import connect
from atlas.ledgers.stepup import Approvers
from atlas.ledgers.treasury import Treasury

def _paths(a):
    var = Path(a.var); var.mkdir(parents=True, exist_ok=True)
    return str(var / "payments.sqlite"), var / "approvers.json"

def _creds(a):
    return a.approver, getpass.getpass("passphrase: "), input("TOTP code: ").strip()

def _offline(a):
    if a.cmd == "calendar":
        from atlas.ledgers.banking.calendars import calendar_view
        for r in calendar_view(a.year, a.region):
            print(f"{r['date']} {r['weekday']}  {r['name']}")
        return 0
    from atlas.ledgers.banking.bankids import InvalidIdentifier, validate_any
    try:
        print(json.dumps(validate_any(a.kind, a.value, institution=a.institution, transit=a.transit)))
        return 0
    except InvalidIdentifier as e:
        print(json.dumps({"valid": False, "error": str(e)})); return 1

def _wallet(c, a, appr):
    from atlas.ledgers.wallet.partners import fake_partners
    from atlas.ledgers.wallet.service import Wallet
    return Wallet(c, fake_partners(str(Path(a.var) / "partners_sim.sqlite")), appr)

def _sanctions(c, a, appr):
    from atlas.compliance.screening import Screener
    sc = Screener(c, audit=lambda actor, action, **d: audit.append(c, actor, "wallet." + action, d))
    if a.cmd == "sanctions-load":
        res = sc.load_samples("cli") if a.samples else sc.load_dir("cli", a.directory)
        for r in res: print(f"loaded {r['source']}: {r['entries']} entries (published {r['published'] or '?'})")
        a.cmd = "sanctions-rescreen"
    if a.cmd == "sanctions-rescreen":
        try:
            print("rescreen:", _wallet(c, a, appr).rescreen_all("cli"))
        except Exception as e:  # vault key needed to read investor details
            print(f"rescreen skipped ({e}); run it from the console Compliance tab"); return 0
    elif a.cmd == "sanctions-status": print(json.dumps(sc.status(), indent=2, default=str))
    elif a.cmd == "sanctions-screen":
        print(json.dumps(sc.match(a.name, a.dob, threshold=a.threshold), indent=2))
    return 0

def main(argv=None):
    p = argparse.ArgumentParser(prog="atlas-payments")
    p.add_argument("--var", default=os.environ.get("PAYMENTS_VAR", "var/payments"))
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init")
    e = sp.add_parser("enroll"); e.add_argument("name")
    r = sp.add_parser("payee-request"); [r.add_argument(x) for x in ("name", "kind", "rail", "currency", "destination")]
    for n in ("payee-approve", "transfer-approve"):
        x = sp.add_parser(n); x.add_argument("id", type=int); x.add_argument("--approver", required=True)
    t = sp.add_parser("transfer-request"); t.add_argument("idem_key"); t.add_argument("payee_id", type=int)
    t.add_argument("amount"); t.add_argument("currency"); t.add_argument("--source", default="asset:bank:cad"); t.add_argument("--purpose", default="")
    x = sp.add_parser("transfer-execute"); x.add_argument("id", type=int); x.add_argument("--adapter", default="bank")
    k = sp.add_parser("kill"); k.add_argument("--reason", default="")
    u = sp.add_parser("unkill"); u.add_argument("--approver", required=True)
    sh = sp.add_parser("sheet"); sh.add_argument("id", type=int)
    me = sp.add_parser("mark-executed"); me.add_argument("id", type=int); me.add_argument("--confirmation", required=True)
    me.add_argument("--approver", required=True)
    sp.add_parser("pending")
    bs = sp.add_parser("batch-sheet"); bs.add_argument("name"); bs.add_argument("ids", type=int, nargs="+")
    rc = sp.add_parser("reconcile"); rc.add_argument("statement_csv")
    sp.add_parser("audit-verify"); sp.add_parser("status")
    cr = sp.add_parser("cost-report"); cr.add_argument("month_from"); cr.add_argument("month_to")
    d = sp.add_parser("dashboard"); d.add_argument("--port", type=int, default=8766)  # 8765 = trading dashboard
    # banking / compliance (offline): calendars, identifier validation, sanctions lists from local files
    ca = sp.add_parser("calendar"); ca.add_argument("year", type=int); ca.add_argument("--region", default="CA")
    vi = sp.add_parser("validate-id"); vi.add_argument("kind", choices=["ca_account", "iban", "bic", "aba", "dprn", "micr"])
    vi.add_argument("value"); vi.add_argument("--institution"); vi.add_argument("--transit")
    sl = sp.add_parser("sanctions-load"); sl.add_argument("directory", nargs="?", default="var/sanctions")
    sl.add_argument("--samples", action="store_true", help="load the SYNTHETIC sample lists (demo/testing only)")
    sp.add_parser("sanctions-status"); sp.add_parser("sanctions-rescreen")
    ss = sp.add_parser("sanctions-screen"); ss.add_argument("name"); ss.add_argument("--dob"); ss.add_argument("--threshold", type=float)
    fr = sp.add_parser("fintrac-records"); fr.add_argument("--kind")
    sp.add_parser("fintrac-status"); sp.add_parser("fintrac-purge")
    vr = sp.add_parser("vault-rotate", help="re-encrypt the vault: current key from ATLAS_VAULT_KEY, new from ATLAS_VAULT_KEY_NEW")
    vr.add_argument("--dry-run", action="store_true")
    cc = sp.add_parser("cpa005-check"); cc.add_argument("file")
    a = p.parse_args(argv)
    if a.cmd in ("calendar", "validate-id"):
        return _offline(a)
    db, apath = _paths(a)
    if a.cmd == "dashboard":
        from atlas.ledgers.dashboard import serve
        print(f"read-only dashboard on http://127.0.0.1:{a.port}"); return serve(db, a.port)
    c = connect(db); appr = Approvers(apath); tr = Treasury(c, appr)
    if a.cmd.startswith("sanctions-"):
        return _sanctions(c, a, appr)
    if a.cmd == "cpa005-check":
        from atlas.ledgers.banking.cpa005 import CPA005Error, parse
        try:
            r = parse(Path(a.file).read_text(encoding="ascii"))
        except (CPA005Error, UnicodeDecodeError) as e:
            print(json.dumps({"valid": False, "error": str(e)})); return 1
        print(json.dumps({k: r[k] for k in ("valid", "errors", "header", "trailer")} | {"items": len(r["items"])}, indent=2))
        return 0 if r["valid"] else 1
    if a.cmd == "vault-rotate":
        from atlas.ledgers.wallet.vault import ENV, NEW_ENV, VaultUnavailable, rotate
        try:
            res = rotate(c, os.environ.get(ENV, ""), os.environ.get(NEW_ENV, ""), "cli", a.dry_run)
        except VaultUnavailable as e:
            print(f"vault-rotate refused: {e} (set {ENV} to the current key and {NEW_ENV} to a key from "
                  "`python -m atlas.ledgers.wallet.vault`)"); return 2
        print(json.dumps(res))
        if not a.dry_run:
            print(f"done: now set {ENV} to the new key and remove {NEW_ENV}; keep the old key offline until backups rotate")
        return 0
    if a.cmd.startswith("fintrac-"):
        from atlas.compliance.fintrac import Fintrac
        f = Fintrac(c, audit=lambda actor, action, **d: audit.append(c, actor, "wallet." + action, d))
        out = {"fintrac-records": lambda: f.records(a.kind), "fintrac-status": f.status, "fintrac-purge": lambda: f.purge_expired("cli")}[a.cmd]()
        print(json.dumps(out, indent=2, default=str)); return 0
    if a.cmd == "init": print(f"initialised {db}")
    elif a.cmd == "enroll":
        pw = getpass.getpass("new passphrase (>=12 chars): ")
        print("TOTP secret (add to authenticator, shown once):", appr.enroll(a.name, pw))
    elif a.cmd == "payee-request": print(tr.request_payee("cli", a.name, a.kind, a.rail, a.currency, a.destination))
    elif a.cmd == "payee-approve": print(dict(tr.approve_payee(a.id, *_creds(a))))
    elif a.cmd == "transfer-request":
        print(tr.request_transfer("cli", a.idem_key, a.payee_id, a.amount, a.currency, a.source, a.purpose))
    elif a.cmd == "transfer-approve": print(dict(tr.approve_transfer(a.id, *_creds(a))))
    elif a.cmd == "transfer-execute":
        print("NOTE: requires execution_mode=adapter; adapters are disabled by default and only simulate.")
        print(tr.execute(a.id, a.adapter, actor="cli"))
    elif a.cmd == "sheet":
        m = Manual(tr, Path(a.var) / "sheets")
        print(json.dumps(m.write_sheet(a.id) if tr.transfer(a.id)["status"] != "approved" else m.prepare(a.id), indent=2))
    elif a.cmd == "mark-executed":
        Manual(tr, Path(a.var) / "sheets").mark_executed(a.id, a.confirmation, *_creds(a)); print("pending_settlement")
    elif a.cmd == "pending": print(json.dumps(Manual(tr).pending(), indent=2, default=str))
    elif a.cmd == "batch-sheet": print(json.dumps(Manual(tr, Path(a.var) / "sheets").batch(a.ids, a.name), indent=2))
    elif a.cmd == "reconcile":
        from atlas.ledgers.recon import load_statement
        print(json.dumps(Manual(tr).reconcile(load_statement(a.statement_csv)), indent=2))
    elif a.cmd == "kill": tr.kill("cli", a.reason); print("kill switch ENGAGED")
    elif a.cmd == "unkill": tr.unkill(*_creds(a)); print("kill switch off")
    elif a.cmd == "audit-verify": print(audit.verify(c))
    elif a.cmd == "status":
        from atlas.ledgers.readonly import BalanceView
        print(json.dumps(BalanceView(db).summary(), indent=2))
    elif a.cmd == "cost-report": print(Costs(c).report_csv(a.month_from, a.month_to), end="")

if __name__ == "__main__":
    main()
