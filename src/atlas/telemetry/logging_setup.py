"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

SENSITIVE_KEY = re.compile(r"(secret|password|passwd|token|api[_-]?key|private[_-]?key|credential|auth|dsn|session)", re.I)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)\b((?:[A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[=:]\s*)\S+"),
    re.compile(r"(\w+://[^:/\s]+:)[^@\s]+(@)"),  # passwords in URLs
]
REDACTED = "***REDACTED***"


def redact_text(text: str) -> str:
    out = text
    for pat in SENSITIVE_VALUE_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: m.group(1) + REDACTED + m.group(2), out)
        elif pat.groups == 1:
            out = pat.sub(lambda m: m.group(1) + REDACTED, out)
        else:
            out = pat.sub(REDACTED, out)
    return out


def redact(obj: Any, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY.search(key) and not isinstance(obj, (dict, list)):
        return REDACTED
    if isinstance(obj, dict):
        return {k: redact(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


class JsonRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = extra
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonRedactingFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
