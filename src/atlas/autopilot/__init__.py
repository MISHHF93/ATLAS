"""Autopilot (PAPER ONLY): one Start/Stop switch for the continuous loop
feeds -> signals -> models -> sizing -> risk engine -> paper execution / owner approval -> monitoring.

Start needs owner step-up (console or `atlas-owner`); stop is instant and needs nothing. The autopilot never
changes policy, never approves orders (at autonomy L1 every sized order is queued for the owner), never enlarges a
trade (its risk-budget overlay only shrinks buys), and never touches payments or bank money."""
