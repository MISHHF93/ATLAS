"""Load the local gitignored .env into os.environ at server start (no third-party dependency).

Only non-blank values are applied and an already-set process variable always wins, so a blank key in .env leaves the
integration "not configured" and keeps built-in defaults. Values are never logged."""
from __future__ import annotations

import os
import re
from pathlib import Path


def load_env_file(path: str | Path, environ: dict[str, str] | None = None) -> list[str]:
    environ = os.environ if environ is None else environ
    p = Path(path)
    applied: list[str] = []
    if not p.exists():
        return applied
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip('"').strip("'")
        if k and v and not v.startswith("<") and not environ.get(k):
            environ[k] = v
            applied.append(k)
    from atlas import envalias
    envalias.apply(environ)  # ALPACA_API_KEY etc. -> the canonical ALPACA_API_KEY_ID names
    return applied
