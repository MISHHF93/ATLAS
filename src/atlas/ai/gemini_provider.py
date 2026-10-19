"""Gemini research adapter.

Uses the official google-genai SDK. No tools, no order methods, and no OpenAI client.

Model ids checked on 2026-10-19:
- gemini-3.8-flash for frequent notes
- gemini-4-argon for deep notes
https://ai.google.dev/gemini-api/docs/models

Paid-tier data use is documented at:
https://ai.google.dev/gemini-api/docs/pricing
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Literal

from atlas.ai.policy import PolicyError, screen_context
from atlas.ai.schemas import MarketResearchResult

FREQUENT_MODEL = "gemini-3.8-flash"
DEEP_MODEL = "gemini-4-argon"
DEFAULT_TIMEOUT_MS = 30_000
_ANALYST_PREAMBLE = (
    "You are a market research analyst. "
    "Analyze the supplied observations. "
    "Do not recommend or place orders. "
    "Clearly identify uncertainty.\n\n"
)

logger = logging.getLogger("atlas.ai.gemini")
Generate = Callable[[str, str], str]


def _transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(token in text for token in ("timeout", "429", "500", "502", "503", "504"))


class GeminiResearchProvider:
    """Structured market notes. Constructing it does not call the network."""

    def __init__(
        self,
        model: str | None = None,
        *,
        workload: Literal["frequent", "deep"] = "frequent",
        api_key: str | None = None,
        tier: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        generate: Generate | None = None,
    ) -> None:
        if model is not None:
            self.model = model
        elif workload == "deep":
            self.model = os.getenv("ATLAS_GEMINI_DEEP_MODEL", DEEP_MODEL)
        else:
            self.model = os.getenv("ATLAS_GEMINI_MODEL", FREQUENT_MODEL)
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self._tier = (
            tier if tier is not None else os.environ.get("ATLAS_GEMINI_TIER", "")
        ).strip().lower()
        self._timeout_ms = timeout_ms
        self._generate = generate

    def analyze(self, market_context: str) -> MarketResearchResult:
        screen_context(market_context)
        if self._tier != "paid":
            raise PolicyError(
                "Gemini research calls require ATLAS_GEMINI_TIER=paid. "
                "The free tier is marked as used to improve Google products."
            )
        started = time.perf_counter()
        raw = self._generate(self.model, market_context) if self._generate else self._call(market_context)
        if not raw:
            raise RuntimeError("Gemini returned an empty response")
        result = MarketResearchResult.model_validate_json(raw)
        logger.info(
            "gemini_research_complete model=%s latency_ms=%d",
            self.model,
            int((time.perf_counter() - started) * 1000),
        )
        return result

    def _call(self, market_context: str) -> str:
        if not self._api_key:
            raise PolicyError("GEMINI_API_KEY is not set.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise PolicyError('Install the Gemini extra: pip install -e ".[gemini]"') from exc

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=self._timeout_ms),
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=_ANALYST_PREAMBLE + market_context,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=MarketResearchResult,
                        temperature=0.1,
                    ),
                )
                return response.text or ""
            except Exception as exc:
                last_error = exc
                if attempt == 2 or not _transient(exc):
                    logger.info(
                        "gemini_research_failed model=%s error_type=%s",
                        self.model,
                        type(exc).__name__,
                    )
                    raise
        assert last_error is not None
        raise last_error
