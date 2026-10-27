# ATLAS Architectural Decisions

1. **ADR-001 (No Live Execution)**: Every AI/ML/research endpoint carries `execution_permission: "none"`. Live broker URLs (`https://api.alpaca.markets`) are refused by `guard_alpaca_url`.
2. **ADR-002 (Authentic Assets & Speculative Token Quarantine)**: Pump.fun and PumpSwap modules are quarantined to read-only historical research (`RESEARCH_REJECTED` for execution) in favour of the Authentic Assets Catalog (Gold, Silver, ETFs, Equities, Sovereign Bonds).
3. **ADR-003 (TradingView & Pine Governance)**: Unauthenticated live scraping of TradingView is disabled. Strategy discovery uses offline SQLite corpus search and license-verified open-source Pine v5/v6 import into `StrategyIR`.
4. **ADR-004 (Quarter-Kelly & Strictest Constraint Cascade)**: Kelly fractions are capped at 0.25x, penalized by calibration ECE, and subordinate to the 0.5%–1.0% fixed-fractional risk budget and deterministic control plane.
5. **ADR-005 (Raw Evidence Separation)**: `var/research/research_memory.json` stores content-hashed `raw_evidence` separately from `ai_interpretation`.

