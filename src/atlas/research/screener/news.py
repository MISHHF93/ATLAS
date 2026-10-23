"""LLM news/risk screener interface. It can ONLY veto or downsize an EXISTING intent.

Enforced structurally: `NewsScreener.screen(intent, ...)` returns either None (veto) or a copy
of the same intent with qty multiplied by m in (0, 1]. Nothing else about the intent can change,
and the screener has no way to create an intent. Provider output is untrusted: it is validated
against a strict schema, and anything invalid, unknown, or late is treated as a failure.

DECISION (owner, 2026-10-16): on timeout or error the default is VETO (block the trade).
Configurable in risk_policy.yaml ai_controls.llm_screener.on_timeout / on_error
(veto | downsize | pass | safe_default). The TRD's original "safe_default" means downsize.

Providers are pluggable: offline_stub (default), finbert_local and http_llm (both opt-in via env; see providers.py)."""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="screener")


@dataclass(frozen=True)
class Headline:
    """Untrusted vendor text. Never interpreted as instructions."""
    ts: datetime
    source: str
    text: str


class ScreenerVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action: Literal["none", "downsize", "veto"]
    size_mult: float = Field(default=1.0, gt=0, le=1.0, allow_inf_nan=False)
    flags: list[str] = Field(default_factory=list, max_length=20)
    severity: Literal["low", "medium", "high"] = "low"
    rationale: str = Field(default="", max_length=500)
    model_id: str = "unknown"
    prompt_version: str = "v0"


class ScreenerProvider(Protocol):
    name: str

    def screen(self, symbol: str, headlines: list[Headline]) -> dict: ...


class OfflineStubProvider:
    """Deterministic keyword classifier. No network, no model, same input => same output."""
    name = "offline_stub"
    VETO = ("trading halt", "halted", "bankruptcy", "chapter 11", "delisting", "fraud", "sec charges",
            "going concern", "accounting restatement")
    DOWNSIZE_HALF = ("offering", "guidance cut", "downgrade", "lawsuit", "investigation", "recall", "ceo resign")
    DOWNSIZE_QUARTER = ("profit warning", "short report", "data breach")

    def screen(self, symbol: str, headlines: list[Headline]) -> dict:
        text = " \n ".join(h.text.lower() for h in headlines)
        hits = lambda words: sorted(w for w in words if w in text)  # noqa: E731
        if v := hits(self.VETO):
            return {"action": "veto", "size_mult": 1.0, "flags": v, "severity": "high",
                    "rationale": f"veto keywords: {', '.join(v)}", "model_id": self.name, "prompt_version": "stub-1"}
        if q := hits(self.DOWNSIZE_QUARTER):
            return {"action": "downsize", "size_mult": 0.25, "flags": q, "severity": "medium",
                    "rationale": f"downsize keywords: {', '.join(q)}", "model_id": self.name, "prompt_version": "stub-1"}
        if h := hits(self.DOWNSIZE_HALF):
            return {"action": "downsize", "size_mult": 0.5, "flags": h, "severity": "medium",
                    "rationale": f"downsize keywords: {', '.join(h)}", "model_id": self.name, "prompt_version": "stub-1"}
        return {"action": "none", "size_mult": 1.0, "flags": [], "severity": "low", "rationale": "no event keywords",
                "model_id": self.name, "prompt_version": "stub-1"}


def make_provider(name: str) -> ScreenerProvider | None:
    if name == "offline_stub":
        return OfflineStubProvider()
    if name == "none":
        return None
    if name == "http_llm":
        from atlas.research.screener.providers import HttpLLMProvider
        return HttpLLMProvider()
    if name == "finbert_local":
        from atlas.research.screener.providers import FinBertProvider
        return FinBertProvider()
    raise ValueError(f"screener provider {name!r} not available in this build (offline only)")


@dataclass(frozen=True)
class ScreenResult:
    intent: object | None            # None => vetoed
    verdict: ScreenerVerdict | None
    applied_mult: float              # 0 => veto
    failure: str | None = None


class NewsScreener:
    def __init__(self, cfg, provider: ScreenerProvider | None = None, audit=None):
        self.cfg = cfg
        self.provider = provider if provider is not None else make_provider(cfg.provider)
        self.audit = audit

    def _fail(self, intent, kind: str, err: str) -> ScreenResult:
        mode = self.cfg.on_timeout if kind == "timeout" else self.cfg.on_error
        if mode == "safe_default":
            mode = "downsize"
        if self.audit:
            self.audit.append("screener.failure", {"intent_id": intent.intent_id, "kind": kind, "error": err[:300], "policy": mode})
        if mode == "veto":
            return ScreenResult(None, None, 0.0, f"{kind}: {err}")
        if mode == "downsize":
            m = min(self.cfg.allowed_downsize_mults)
            return ScreenResult(intent.model_copy(update={"qty": intent.qty * m}), None, m, f"{kind}: {err}")
        return ScreenResult(intent, None, 1.0, f"{kind}: {err}")

    def screen(self, intent, headlines: list[Headline]) -> ScreenResult:
        if not self.cfg.enabled or self.provider is None:
            return ScreenResult(intent, None, 1.0, None)
        fut = _POOL.submit(self.provider.screen, intent.symbol, list(headlines))
        try:
            raw = fut.result(timeout=self.cfg.timeout_s)
        except cf.TimeoutError:
            fut.cancel()
            return self._fail(intent, "timeout", f"no verdict within {self.cfg.timeout_s}s")
        except Exception as e:  # noqa: BLE001
            return self._fail(intent, "error", f"{type(e).__name__}: {e}")
        try:
            v = ScreenerVerdict.model_validate(raw)
        except ValidationError as e:
            return self._fail(intent, "error", f"invalid verdict schema: {e.errors()[:2]}")
        if v.action not in self.cfg.allowed_actions:
            return self._fail(intent, "error", f"action {v.action!r} not allowed by policy")
        if v.action == "veto":
            res = ScreenResult(None, v, 0.0)
        elif v.action == "downsize":
            allowed = sorted(m for m in self.cfg.allowed_downsize_mults if m <= min(v.size_mult, self.cfg.max_size_mult))
            m = allowed[-1] if allowed else min(self.cfg.allowed_downsize_mults)   # snap DOWN, never up
            res = ScreenResult(intent.model_copy(update={"qty": intent.qty * m}), v, m)
        else:
            res = ScreenResult(intent, v, 1.0)
        if self.audit:
            self.audit.append("screener.verdict", {"intent_id": intent.intent_id, "action": v.action,
                                                   "applied_mult": res.applied_mult, "flags": v.flags, "model_id": v.model_id})
        return res
