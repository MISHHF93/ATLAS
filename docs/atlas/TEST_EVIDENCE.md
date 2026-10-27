# ATLAS Verification & Test Evidence

- **Complete System Verification Suite**: `tests/test_complete_system_verification.py` (`15 passed`) covering live ML inference across all symbols, 17 market states, CME maintenance breaks, Nasdaq 23/5 readiness, EV evolution, Champion/Challenger rollback, and Privacy/ISO/3rd-party links.
- **Research-to-Execution Integration Suite**: `tests/test_research_integration.py` covering strategy discovery, Pine v5/v6 parsing, repainting/lookahead rejection, unsupported syntax rejection, license/prompt-injection checks, Pine-to-Python parity, realistic walk-forward backtesting, broker capability guards, dynamic position sizing, research memory, and session handoffs.
- **Frontend Invariant Tests**: `frontend/scripts/one-chart.test.mjs` and `frontend/scripts/pages.test.mjs` (`9/9 passed`).

