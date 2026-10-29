"""Gate, fence and call the LLM for news work. Fails closed: if anything required is missing the answer is ``disabled`` with a reason.

Enabled ONLY when all of: a Gemini key is present for this scope AND it was verified through ``integrations.verify`` (state ``verified``)
AND ``ATLAS_GEMINI_TIER=paid`` (the free tier may be used to improve Google products). ``llm_other`` keys are never used: ATLAS cannot probe
them, so they can never reach ``verified``. The model gets no tools, only fenced text, and must return JSON that we validate."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping

LLM = Callable[[str, str], dict[str, Any]]   # (prompt, prompt_version) -> parsed JSON object
MAX_ITEM_CHARS = 300
_FENCE = re.compile(r"<<<|>>>|[\x00-\x08\x0b-\x1f\x7f]")


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def clean(text: str, n: int = MAX_ITEM_CHARS) -> str:
    """Untrusted text -> single line, no fence markers or control characters, bounded."""
    return re.sub(r"\s+", " ", _FENCE.sub(" ", text or "")).strip()[:n]


def fence_item(sid: str, it: Mapping[str, Any]) -> str:
    import datetime as dt
    when = dt.datetime.fromtimestamp(float(it["published_at"]), dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return (f'<<<UNTRUSTED_ITEM id="{sid}" source="{clean(str(it.get("source", "")), 24)}" tier={int(it.get("tier", 2))} published="{when}">>>\n'
            f'{clean(str(it.get("title", "")))}\n<<<END_ITEM>>>')


def llm_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from atlas.accounts.credentials import effective_environ
    from atlas.integrations import verify as V
    from atlas.integrations.registry import SERVICES, load_env
    env = dict(env) if env is not None else load_env(environ=dict(effective_environ()))
    svc = next(s for s in SERVICES if s.id == "gemini")
    st = V.state_for(svc, env)
    import os
    tier = (env.get("ATLAS_GEMINI_TIER") or os.environ.get("ATLAS_GEMINI_TIER") or "").strip().lower()
    other = {"state": "not_used", "reason": "llm_other keys (OpenAI/Anthropic/xAI) cannot be verified inside ATLAS, so they are never used for news or review"}
    base = {"provider": None, "model": None, "gemini_state": st["state"], "gemini_tier": tier or None, "llm_other": other, "execution_permission": "none"}
    if st["state"] != "verified":
        return {**base, "enabled": False, "reason": f"Gemini key is {st['state'].replace('_', ' ')}: {st.get('detail', '')}".strip()}
    if tier != "paid":
        return {**base, "enabled": False, "reason": "ATLAS_GEMINI_TIER is not 'paid'; the free tier may be used to improve Google products, so ATLAS does not send news text to it"}
    from atlas.ai.gemini_provider import FREQUENT_MODEL
    return {**base, "enabled": True, "provider": "gemini", "model": env.get("ATLAS_GEMINI_MODEL") or os.environ.get("ATLAS_GEMINI_MODEL") or FREQUENT_MODEL, "reason": "verified key, paid tier"}


def get_llm(env: Mapping[str, str] | None = None) -> tuple[LLM | None, dict[str, Any]]:
    """(callable, status). The callable is None unless every gate passes. Constructing it makes no network call."""
    from atlas.accounts.credentials import effective_environ
    from atlas.integrations.registry import load_env
    env = dict(env) if env is not None else load_env(environ=dict(effective_environ()))
    st = llm_status(env)
    if not st["enabled"]:
        return None, st
    from atlas.multi_agent.llm import GeminiSynthesisLLM
    return GeminiSynthesisLLM(st["model"], api_key=env["GEMINI_API_KEY"].strip()), st
