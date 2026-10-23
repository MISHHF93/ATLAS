"""atlas-console: local owner web app (single-page app + stdlib JSON API).

Process boundaries are unchanged:
  * trading_api talks to the PAPER trading service (read views; owner writes are queued in the
    shared state DB exactly like `atlas-owner`; this process never executes orders).
  * payments_api talks to the SIMULATION payments service through its own Treasury/Manual
    classes with its own approver identities; there is NO adapter-execute route.
  * trading_api never imports atlas.ledgers; payments_api never imports tradingbot.
"""
