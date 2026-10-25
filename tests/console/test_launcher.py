"""One-command launcher: `atlas-console up --demo` starts the paper core loop, the external watchdog and the
console; the console sees a healthy core heartbeat + live watchdog; SIGTERM stops all three without halting trading."""
from __future__ import annotations

import signal
import subprocess
import sys
import time

from test_console_api import CONFIG, Client, _free_port
from atlas.console.cli import launch_plan
from atlas.console.demo import seed


def test_launch_plan_order_and_paper_only():
    names = [n for n, _ in launch_plan("var/demo", "config", 8770, True)]
    assert names == ["core", "watchdog", "console"]
    argv = dict(launch_plan("var/demo", "config", 8770, True))
    assert "--demo" in argv["console"] and argv["watchdog"][-1].endswith("state.sqlite")
    assert [n for n, _ in launch_plan("var", "config", 8770, False, core=False)] == ["console"]


def test_up_starts_core_watchdog_console_and_stops_cleanly(tmp_path):
    import re
    import shutil
    from atlas.ops.procutil import child_pids, pid_alive, terminate_pid_tree

    var = tmp_path / "demo"
    seed(var, CONFIG, run_sim=False, verbose=False)
    port = _free_port()
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
    p = subprocess.Popen([sys.executable, "-c", "from atlas.console.cli import main; import sys; sys.exit(main())", "up", "--demo",
                          "--var", str(var), "--config", str(CONFIG), "--port", str(port)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
    sig = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM) if sys.platform == "win32" else signal.SIGTERM
    try:
        cred = dict(line.split("=", 1) for line in (var / "DEMO_CREDENTIALS.txt").read_text().splitlines()[1:])
        hb, t0 = None, time.time()
        while time.time() - t0 < 120:
            try:
                c = Client(port)
                if c.login(cred["username"], cred["passphrase"]).status == 200:
                    hb = c.call("GET", "/api/t/state").json["status"]["core_heartbeat"]
                    if hb["healthy"] and hb["watchdog_alive"]:
                        break
            except OSError:
                pass
            assert p.poll() is None, p.stdout.read().decode()
            time.sleep(1)
        assert hb and hb["healthy"] and hb["watchdog_alive"], hb
        assert c.call("GET", "/api/t/state").json["status"]["halted"] is False
    finally:
        if sys.platform == "win32":
            (var / ".stop").write_text("1")
        try:
            p.send_signal(sig)
        except OSError:
            pass
        time.sleep(0.5)
        if p.poll() is None:
            try:
                p.send_signal(sig)                               # an impatient second signal must not orphan children
            except OSError:
                pass
        rc = p.wait(40)
        terminate_pid_tree(p.pid)
        assert rc == 0
    out = p.stdout.read().decode()
    assert "started core" in out and "started watchdog" in out and "started console" in out
    if shutil.which("pgrep"):
        ps = subprocess.run(["pgrep", "-f", str(var)], capture_output=True, text=True).stdout.split()
        assert not ps, ps                                                   # no orphaned children
    else:
        pids = [int(m) for m in re.findall(r"pid\s+(\d+)", out)]
        assert pids and not any(pid_alive(cpid) or child_pids(cpid) for cpid in pids), pids
    from atlas.risk.state_store import StateStore
    assert StateStore(str(var / "state.sqlite")).get("kill_switch")["engaged"] is False
