"""LLM provider abstraction. Keys come from env var NAMES only; a provider without a key is disabled.

All network providers speak a tool-calling protocol restricted to the read-only allowlist. The offline `local`
provider (rule-based intent router) is always available and needs no network or key."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class ProviderError(RuntimeError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code            # no_key | timeout | rate_limited | http | bad_response


@dataclass
class ProviderInfo:
    id: str
    label: str
    key_env: str | None
    model_env: str | None
    default_model: str
    endpoint: str
    style: str                      # openai | anthropic | local

    def enabled(self, env=os.environ) -> bool:
        return self.key_env is None or bool(env.get(self.key_env))

    def model(self, env=os.environ) -> str:
        return env.get(self.model_env, self.default_model) if self.model_env else self.default_model

    def public(self, env=os.environ) -> dict:
        return {"id": self.id, "label": self.label, "enabled": self.enabled(env), "key_env": self.key_env,
                "model": self.model(env), "network": self.style != "local",
                "status": "ready" if self.enabled(env) else f"disabled: set env {self.key_env}"}


PROVIDERS = {
    "local": ProviderInfo("local", "Offline assistant (no AI provider)", None, None, "rules-v1", "", "local"),
    "grok": ProviderInfo("grok", "xAI Grok", "XAI_API_KEY", "XAI_MODEL", "grok-4", "https://api.x.ai/v1/chat/completions", "openai"),
    "claude": ProviderInfo("claude", "Anthropic Claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-sonnet-4-5",
                           "https://api.anthropic.com/v1/messages", "anthropic"),
    "gpt": ProviderInfo("gpt", "OpenAI GPT", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5", "https://api.openai.com/v1/chat/completions", "openai"),
}

Transport = Callable[[str, dict, dict, float], dict]


def http_transport(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise ProviderError("rate_limited", "the AI provider is rate-limiting requests; try again in a minute")
        raise ProviderError("http", f"AI provider returned HTTP {e.code}")
    except (TimeoutError, urllib.error.URLError) as e:
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            raise ProviderError("timeout", "the AI provider did not answer in time")
        raise ProviderError("http", "could not reach the AI provider (offline?)")


class LLMClient:
    """One chat turn with tool calling. `run_tool(name, args) -> str` returns FENCED, redacted tool output."""

    def __init__(self, info: ProviderInfo, transport: Transport = http_transport, timeout: float = 30.0, env=os.environ):
        self.info, self.transport, self.timeout, self.env = info, transport, timeout, env

    def chat(self, system: str, messages: list[dict], tools: list[dict], run_tool: Callable[[str, dict], str],
             max_rounds: int = 4) -> tuple[str, list[dict]]:
        if not self.info.enabled(self.env):
            raise ProviderError("no_key", f"{self.info.label} is disabled: set env {self.info.key_env}")
        key = self.env[self.info.key_env]
        calls: list[dict] = []
        if self.info.style == "anthropic":
            hdr = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            msgs = [dict(m) for m in messages]
            tl = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
            for _ in range(max_rounds):
                r = self.transport(self.info.endpoint, hdr, {"model": self.info.model(self.env), "max_tokens": 1200, "system": system,
                                                              "messages": msgs, "tools": tl}, self.timeout)
                content = r.get("content") or []
                uses = [c for c in content if c.get("type") == "tool_use"]
                if not uses:
                    return "".join(c.get("text", "") for c in content if c.get("type") == "text"), calls
                msgs.append({"role": "assistant", "content": content})
                results = []
                for u in uses:
                    out = run_tool(u["name"], u.get("input") or {})
                    calls.append({"tool": u["name"], "args": u.get("input") or {}})
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": out})
                msgs.append({"role": "user", "content": results})
            raise ProviderError("bad_response", "too many tool rounds")
        hdr = {"Authorization": f"Bearer {key}"}
        msgs = [{"role": "system", "content": system}] + [dict(m) for m in messages]
        tl = [{"type": "function", "function": t} for t in tools]
        for _ in range(max_rounds):
            r = self.transport(self.info.endpoint, hdr, {"model": self.info.model(self.env), "messages": msgs, "tools": tl,
                                                          "tool_choice": "auto", "temperature": 0.2}, self.timeout)
            try:
                m = r["choices"][0]["message"]
            except (KeyError, IndexError):
                raise ProviderError("bad_response", "unexpected response from the AI provider")
            tcs = m.get("tool_calls") or []
            if not tcs:
                return m.get("content") or "", calls
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                out = run_tool(fn.get("name", ""), args)
                calls.append({"tool": fn.get("name", ""), "args": args})
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": out})
        raise ProviderError("bad_response", "too many tool rounds")


def provider_list(env=os.environ) -> list[dict[str, Any]]:
    return [p.public(env) for p in PROVIDERS.values()]
