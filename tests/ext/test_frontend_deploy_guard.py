"""Regression for 'Application error: a client-side exception has occurred' after `next build` under a running server."""
import pathlib

FE = pathlib.Path(__file__).parents[2] / "frontend"


def test_redeploy_builds_then_restarts_exact_pid_then_smokes():
    s = (FE / "scripts" / "redeploy3000.ps1").read_text()
    assert s.index("next build") < s.index("taskkill /PID $pid3000") < s.index("smoke_pages.cjs")
    assert "-LocalPort 3000" in s and "/T /F" in s


def test_smoke_covers_registry_hubs_tabs_and_fails_on_console_errors():
    s = (FE / "scripts" / "smoke_pages.cjs").read_text()
    assert "nav-registry.mjs" in s and "?tab=" in s and "pageerror" in s and "Application error" in s
    assert "process.exit(bad ? 1 : 0)" in s
