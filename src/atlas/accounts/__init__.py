"""Multi-user accounts for ATLAS: auth, per-user encrypted connector credentials, billing schema.

Nothing here can place an order. ``EXECUTION_PERMISSION`` stays ``none``: credentials are used only to read data and to
reach paper/practice endpoints that the control plane already guards. See ``docs/atlas/security-review.md``.
"""
EXECUTION_PERMISSION = "none"
