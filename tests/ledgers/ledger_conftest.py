import pytest
from atlas.ledgers.db import connect
from atlas.ledgers.stepup import Approvers, totp
from atlas.ledgers.treasury import Treasury, COOLING_OFF_S

PW = "correct horse battery staple"

class Clock:
    def __init__(self, t=1_792_000_000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s

@pytest.fixture
def env(tmp_path):
    clock = Clock()
    c = connect(str(tmp_path / "p.sqlite"))
    appr = Approvers(tmp_path / "approvers.json", clock=clock)
    secrets = {n: appr.enroll(n, PW) for n in ("owner", "cofounder")}
    tr = Treasury(c, appr, clock=clock)
    tr._set("execution_mode", "adapter")  # legacy simulated-adapter tests; manual is the default
    for a in tr.adapters.values():
        a.enabled = True  # simulated adapters only; disabled by default
    step = {"n": 0}
    def creds(name):
        # unique code per call: advance 30s so TOTP replay protection doesn't trip
        clock.advance(31)
        return name, PW, totp(secrets[name], clock())
    def ready_payee(name="Vendor", rail="EFT", ccy="CAD", kind="bank", dest="CA-XXXX-1234"):
        pid = tr.request_payee("ops", name, kind, rail, ccy, dest)
        for n in (["owner", "cofounder"] if tr.required_approvals() == 2 else ["owner"]):
            tr.approve_payee(pid, *creds(n))
        clock.advance(COOLING_OFF_S + 1)
        return pid
    class E: pass
    e = E(); e.c, e.tr, e.clock, e.creds, e.ready_payee, e.path = c, tr, clock, creds, ready_payee, tmp_path / "p.sqlite"
    return e
