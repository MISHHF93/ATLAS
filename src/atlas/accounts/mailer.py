"""SMTP-agnostic mail interface for account email (verification, password reset, invites).

Backends (``ATLAS_MAIL_BACKEND``):

* ``console`` (default): nothing is sent. The message is written to the log. On a public deployment only metadata is logged (a log
  is not a safe place for live sign-in links), so a public deployment that still uses ``console`` cannot deliver mail; the status
  endpoint reports ``mail_backend: console`` so the operator sees it.
* ``smtp``: ``ATLAS_SMTP_HOST``, ``ATLAS_SMTP_PORT`` (587), ``ATLAS_SMTP_USER``, ``ATLAS_SMTP_PASSWORD``, ``ATLAS_SMTP_FROM``,
  ``ATLAS_SMTP_SECURITY`` (``starttls`` default | ``ssl`` | ``none``). Works with any provider's SMTP relay.
* ``file``: one JSON file per message in ``ATLAS_MAIL_OUTBOX`` (demos, local previews). Never use with real users.
* ``memory``: an in-process list (tests).

Anything with a ``send(Message)`` method satisfies ``Mailer``, so a provider API (Postmark, SES, Resend) is one small class away.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import time
import uuid
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Mapping, Protocol

from . import netinfo

log = logging.getLogger("atlas.mail")


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    kind: str = ""


class Mailer(Protocol):
    name: str

    def send(self, msg: Message) -> None: ...


def mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


class ConsoleMailer:
    name = "console"

    def __init__(self, full: bool = True):
        self.full = full

    def send(self, msg: Message) -> None:
        if self.full:
            log.warning("MAIL (console backend, not delivered) to=%s kind=%s subject=%r\n%s", msg.to, msg.kind, msg.subject, msg.text)
        else:
            log.warning("MAIL (console backend, NOT delivered) to=%s kind=%s subject=%r. Configure ATLAS_MAIL_BACKEND=smtp.", mask(msg.to), msg.kind, msg.subject)


class MemoryMailer:
    name = "memory"

    def __init__(self) -> None:
        self.outbox: list[Message] = []

    def send(self, msg: Message) -> None:
        self.outbox.append(msg)


class FileMailer:
    name = "file"

    def __init__(self, directory: str):
        self.dir = Path(directory)

    def send(self, msg: Message) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(msg), fh, indent=2)


class SmtpMailer:
    name = "smtp"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, security: str = "starttls", timeout: float = 15.0):
        self.host, self.port, self.user, self.password, self.sender, self.security, self.timeout = host, port, user, password, sender, security, timeout

    def send(self, msg: Message) -> None:
        em = EmailMessage()
        em["From"], em["To"], em["Subject"] = self.sender, msg.to, msg.subject
        em["Message-ID"] = f"<{uuid.uuid4().hex}@atlas>"
        em.set_content(msg.text)
        ctx = ssl.create_default_context()
        if self.security == "ssl":
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ctx)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with server:
            if self.security == "starttls":
                server.starttls(context=ctx)
            if self.user:
                server.login(self.user, self.password)
            server.send_message(em)


_OVERRIDE: Mailer | None = None


def set_mailer(m: Mailer | None) -> None:
    """Tests / embedding: force a mailer instance (None restores env selection)."""
    global _OVERRIDE
    _OVERRIDE = m


def backend_name(env: Mapping[str, str] | None = None) -> str:
    if _OVERRIDE is not None:
        return _OVERRIDE.name
    return get_mailer(env).name  # the backend actually in effect (an unconfigured smtp/file choice falls back to console)


def get_mailer(env: Mapping[str, str] | None = None) -> Mailer:
    if _OVERRIDE is not None:
        return _OVERRIDE
    e = env if env is not None else os.environ
    kind = (e.get("ATLAS_MAIL_BACKEND", "console").strip().lower() or "console")
    if kind == "smtp":
        host = e.get("ATLAS_SMTP_HOST", "").strip()
        if not host:
            log.error("ATLAS_MAIL_BACKEND=smtp but ATLAS_SMTP_HOST is empty; falling back to console (nothing is delivered)")
        else:
            security = e.get("ATLAS_SMTP_SECURITY", "starttls").strip().lower()
            default_port = 465 if security == "ssl" else 587
            try:
                port = int(e.get("ATLAS_SMTP_PORT", "") or default_port)
            except ValueError:
                port = default_port
            return SmtpMailer(host, port, e.get("ATLAS_SMTP_USER", ""), e.get("ATLAS_SMTP_PASSWORD", ""),
                              e.get("ATLAS_SMTP_FROM", "") or "ATLAS <no-reply@localhost>", security if security in ("starttls", "ssl", "none") else "starttls")
    if kind == "file" and e.get("ATLAS_MAIL_OUTBOX", "").strip():
        return FileMailer(e["ATLAS_MAIL_OUTBOX"].strip())
    if kind == "memory":
        return _memory_singleton()
    return ConsoleMailer(full=not netinfo.public_deployment(e))


_MEM: MemoryMailer | None = None


def _memory_singleton() -> MemoryMailer:
    global _MEM
    if _MEM is None:
        _MEM = MemoryMailer()
    return _MEM


def send_safe(msg: Message, env: Mapping[str, str] | None = None) -> bool:
    """Send, never raise (a mail outage must not change an API response, which would also leak whether an address exists)."""
    try:
        get_mailer(env).send(msg)
        return True
    except Exception as ex:  # noqa: BLE001
        log.error("mail send failed kind=%s to=%s: %s", msg.kind, mask(msg.to), type(ex).__name__)
        return False


# ------------------------------------------------------------------ templates
def base_url(env: Mapping[str, str] | None = None) -> str:
    e = env if env is not None else os.environ
    return (e.get("ATLAS_PUBLIC_URL", "").strip() or "http://localhost:3000").rstrip("/")


def _link(query: str, env) -> str:
    return f"{base_url(env)}/settings?tab=profile&{query}"


def verify_email(to: str, token: str, ttl_hours: int, env=None) -> Message:
    return Message(to, "Confirm your ATLAS email address",
                   f"Welcome to ATLAS.\n\nConfirm this email address to finish creating your account:\n{_link('verify=' + token, env)}\n\n"
                   f"The link works once and expires in {ttl_hours} hours. If you did not create an account, ignore this message.", "verify")


def reset_password(to: str, token: str, ttl_minutes: int, env=None) -> Message:
    return Message(to, "Reset your ATLAS password",
                   f"Someone asked to reset the password for this ATLAS account.\n\nChoose a new password here:\n{_link('reset=' + token, env)}\n\n"
                   f"The link works once and expires in {ttl_minutes} minutes. Resetting signs out every device. If this was not you, ignore this message: your password is unchanged.", "reset")


def already_registered(to: str, env=None) -> Message:
    return Message(to, "Your ATLAS account",
                   f"Someone tried to create an ATLAS account with this email address, but one already exists.\n\nSign in: {base_url(env)}/settings?tab=profile\n"
                   f"Forgot your password? Use \"Forgot password\" on the sign-in form.\n\nIf this was not you, no action is needed.", "already_registered")


def invite(to: str, code: str, inviter: str, kind: str, env=None) -> Message:
    what = "join a team on ATLAS" if kind == "team" else "create an ATLAS account"
    key = "team_invite" if kind == "team" else "invite"
    return Message(to, "You are invited to ATLAS",
                   f"{inviter} invited you to {what}.\n\nAccept here:\n{_link(key + '=' + code, env)}\n\nThe invite is single-use and expires. ATLAS is a paper-trading research tool; it never places live trades.", f"invite_{kind}")
