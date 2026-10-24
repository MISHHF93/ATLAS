"""ATLAS external-capability pack (seven-repo gap audit, 2026-10-24).

Research analytics (options greeks, VaR, DCF, SEC EDGAR fundamentals, VWAP/volume profile, high-touch S/R zones,
watchlist scan, Pine v5 export, dossier/conviction, persona scorers, multi-agent pipeline), an Alpaca PAPER broker
facade gated by the deterministic control plane, an alert formatter/dispatcher that is disabled by default, and an
MCP-style discovery surface. Everything here is advisory research (execution_permission "none") except the Alpaca
paper actions, which only run after the control plane authorises them. No module fabricates data: when a source is
missing the payload says so ("unavailable" / "not_configured")."""
EXECUTION_PERMISSION = "none"
ADVISORY = "research-only advisory; not investment advice; cannot place or size an order"
