"""Gates applied before a research provider is called."""

import re

MAX_CONTEXT_CHARS = 12_000

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|api[_-]?secret|passphrase)\s*[:=]\s*\S{8,}"),
)


class PolicyError(RuntimeError):
    """The research call was refused before or after the provider ran."""


def screen_context(market_context: str) -> None:
    if not market_context.strip():
        raise PolicyError("Market context is empty.")
    if len(market_context) > MAX_CONTEXT_CHARS:
        raise PolicyError(
            f"Market context exceeds {MAX_CONTEXT_CHARS} characters."
        )
    for pattern in _SECRET_PATTERNS:
        if pattern.search(market_context):
            raise PolicyError(
                "Market context looks like it contains a secret. Remove it and retry."
            )
