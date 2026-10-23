"""atlas-console: up | serve | seed-demo | enroll.

  atlas-console up --demo              # ONE command: seed demo data if missing, then start the paper core loop,
                                            # the external watchdog and the console (http://127.0.0.1:8770); Ctrl-C stops all
  atlas-console up                     # same on the real var/ (needs `enroll` first)

  atlas-console seed-demo              # DEMO data under var/demo (random creds in var/demo/DEMO_CREDENTIALS.txt)
  atlas-console serve --demo           # http://127.0.0.1:8770 on the DEMO data (banner says DEMO)
  atlas-console enroll                 # console login for the policy owner (real var/)
  atlas-console serve                  # real var/ (viewer of the core's state; payments var/payments)"""
from __future__ import annotations

import argparse
import getpass
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="atlas-console")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--config", default="config/founder")
    s.add_argument("--var", default=None, help="data dir (default var/, or var/demo with --demo)")
    s.add_argument("--payments-var", default=None)
    s.add_argument("--demo", action="store_true")
    d = sub.add_parser("seed-demo")
    d.add_argument("--var", default="var/demo")
    d.add_argument("--config", default="config/founder")
    d.add_argument("--no-sim", action="store_true")
    u = sub.add_parser("up", help="start core + watchdog + console together (paper only)")
    u.add_argument("--port", type=int, default=8770)
    u.add_argument("--config", default="config/founder")
    u.add_argument("--var", default=None)
    u.add_argument("--demo", action="store_true")
    u.add_argument("--reseed", action="store_true", help="re-create the demo data first")
    u.add_argument("--no-core", action="store_true", help="console only (viewer)")
    e = sub.add_parser("enroll")
    e.add_argument("--var", default="var")
    e.add_argument("--config", default="config/founder")
    a = ap.parse_args(argv)
    if a.cmd == "seed-demo":
        from atlas.console.demo import seed
        seed(a.var, a.config, run_sim=not a.no_sim)
        return 0
    if a.cmd == "enroll":
        from atlas.control.policy import load_all
        from atlas.console.app import ConsolePaths
        from atlas.console.auth import Users
        owner = load_all(a.config).risk.owner
        pw, pw2 = getpass.getpass("new console passphrase (>=12 chars): "), getpass.getpass("repeat: ")
        if pw != pw2:
            print("passphrases differ"); return 2
        Users(ConsolePaths.under(a.var, a.config).users).enroll(owner, pw)
        print(f"console login enrolled for {owner}. Step-up uses `atlas-owner init-stepup` (trading) and "
              f"`atlas-payments enroll {owner}` (payments).")
        return 0
    if a.cmd == "up":
        return up(a)
    if a.cmd != "serve":
        ap.print_help(); return 1
    from pathlib import Path
    from atlas.mcp.trading.service import build_service
    from atlas.console.app import ConsolePaths, make_server
    var = a.var or ("var/demo" if a.demo else "var")
    if a.demo and not (Path(var) / "DEMO_DATA_MARKER").exists():
        print(f"no demo data in {var}; run: atlas-console seed-demo --var {var}"); return 2
    paths = ConsolePaths.under(var, a.config, a.payments_var)
    for p in (paths.state_db, paths.audit_db):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    svc = build_service(a.config, paths.audit_db, paths.state_db, tax_db_path=paths.tax_db)
    svc.models_root = str(paths.models)
    if a.demo and not os.environ.get("ATLAS_VAULT_KEY") and (Path(var) / "DEMO_VAULT_KEY").exists():
        os.environ["ATLAS_VAULT_KEY"] = (Path(var) / "DEMO_VAULT_KEY").read_text().strip()   # DEMO key only
    if a.demo:
        from atlas.console.demo import enqueue_demo_approvals
        if enqueue_demo_approvals(svc, only_if_empty=True):
            print("DEMO: re-queued sample owner approvals (previous ones expired)")
    srv = make_server(svc, paths, a.port, demo=a.demo)
    print(f"console on http://127.0.0.1:{a.port}  ({'DEMO data' if a.demo else var}; paper only; loopback only)")
    if not srv.app.users.names():
        print("no console login enrolled: run `atlas-console enroll`", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def launch_plan(var: str, config: str, port: int, demo: bool, core: bool = True) -> list[tuple[str, list[str]]]:
    """(name, argv) of the processes `up` starts, in order. The core starts first: with
    ATLAS_REQUIRE_EXTERNAL_WATCHDOG=true it refuses every order until the watchdog is alive. The watchdog
    starts once the core's heartbeat is fresh (it halts trading on a stale heartbeat, fail-closed)."""
    from pathlib import Path
    py, state = sys.executable, str(Path(var) / "state.sqlite")
    plan = []
    if core:
        plan.append(("core", [py, "-c", "from atlas.ops.runner import main; main()", "--config", config, "--var", var]))
        plan.append(("watchdog", [py, "-c", "from atlas.risk.watchdog_proc import main; main()", "--state", state]))
    plan.append(("console", [py, "-c", "from atlas.console.cli import main; import sys; sys.exit(main())", "serve",
                             "--port", str(port), "--config", config, "--var", var, *(["--demo"] if demo else [])]))
    return plan


def _wait_core_heartbeat(state, proc, timeout: float = 120.0) -> bool:
    import time
    from atlas.risk.state_store import StateStore
    from atlas.risk.watchdog_proc import CORE_HB
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            hb = StateStore(str(state)).get(CORE_HB) if state.exists() else None
            if hb is not None and float(hb) >= t0 - 1:
                return True
        except Exception:  # noqa: BLE001  DB being created
            pass
        time.sleep(0.5)
    return False


def up(a) -> int:
    import signal
    import subprocess
    import time
    from pathlib import Path
    from atlas.risk.safety import assert_paper_only
    assert_paper_only()
    try:
        sys.stdout.reconfigure(line_buffering=True)   # status lines show up promptly even when redirected to a file
    except AttributeError:
        pass
    var = a.var or ("var/demo" if a.demo else "var")
    if a.demo and (a.reseed or not (Path(var) / "DEMO_DATA_MARKER").exists()):
        print(f"seeding demo data in {var} (one-time, about a minute) ...")
        from atlas.console.demo import seed
        seed(var, a.config, run_sim=True)
    logs = Path(var) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ATLAS_REQUIRE_EXTERNAL_WATCHDOG="true", TRADING_MODE="paper", PYTHONUNBUFFERED="1")
    if a.demo and not env.get("ATLAS_VAULT_KEY") and (Path(var) / "DEMO_VAULT_KEY").exists():
        env["ATLAS_VAULT_KEY"] = (Path(var) / "DEMO_VAULT_KEY").read_text().strip()     # DEMO key only
    def _stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)          # also when started in the background (SIGINT otherwise ignored)
    procs = []
    try:
        for name, argv in launch_plan(var, a.config, a.port, a.demo, core=not a.no_core):
            out = open(logs / f"{name}.log", "ab")
            procs.append((name, subprocess.Popen(argv, env=env, stdout=out, stderr=subprocess.STDOUT), out))
            print(f"started {name:8s} pid {procs[-1][1].pid}  log {logs / (name + '.log')}")
            if name == "core" and not _wait_core_heartbeat(Path(var) / "state.sqlite", procs[-1][1]):
                print("core did not report a heartbeat within 120 s; stopping", file=sys.stderr)
                return 1
        print(f"console on http://127.0.0.1:{a.port}  ({'DEMO data' if a.demo else var}; paper only; loopback only). Ctrl-C stops everything.")
        if a.demo:
            print(f"demo logins: {Path(var) / 'DEMO_CREDENTIALS.txt'}")
        while True:
            for name, p, _ in procs:
                if p.poll() is not None:
                    print(f"{name} exited with code {p.returncode}; stopping (see {logs / (name + '.log')})", file=sys.stderr)
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)   # a second Ctrl-C / SIGTERM must not abort the shutdown and orphan children
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # reverse start order: console, watchdog, core (a core without its watchdog refuses orders)
        for name, p, out in reversed(procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
            out.close()


if __name__ == "__main__":
    sys.exit(main())
