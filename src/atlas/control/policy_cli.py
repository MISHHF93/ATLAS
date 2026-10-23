from __future__ import annotations

import sys

from atlas.control.policy import ConfigError, load_all
from atlas.risk.safety import assert_paper_only


def validate_main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    assert_paper_only()
    d = argv[0] if argv else "config/founder"
    try:
        cfg = load_all(d)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"config OK: {cfg.digests}")
    return 0
