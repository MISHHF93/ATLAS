# ATLAS External Integrations & Governance

- **TradingView Indicator Search MCP Reference (`daviddme/tradingview-indicator-search-mcp-server`)**: MIT-licensed community reference. Live scraping disabled; offline SQLite corpus and manual license-verified Pine imports enabled.
- **TradingKit Pine Backtesting Reference (`help.tradingkit.com/backtests/pine-script/`)**: External documentation reference; ATLAS uses its own deterministic Pine v5/v6 parser and conservative OHLC replay.
- **Alpaca MCP Server (`alpacahq/alpaca-mcp-server`)**: Read-only market/account queries in `BROKER_READ_ONLY`; paper orders gated by `ActionableControlPlaneEngine`.
- **Interactive Brokers MCP (`https://api.ibkr.com/v1/api/mcp-public`)**: Read-only portfolio and margin intelligence.
- **Position Sizing Reference (`tradermonty/claude-trading-skills`)**: Fixed-fractional, ATR, and Quarter-Kelly mathematical models adapted with CME/COMEX contract multipliers (`atlas.market.contracts`).
- **Context Engineering Reference (`addyosmani/agent-skills`)**: Persistent repository context files (`docs/atlas/*.md`) and structured session handoffs (`var/research/session_handoffs.json`).

