"""Subsystem K: Key Management & Zero-Leak Secret Scrubbing (`src/atlas/keys/`).

Re-exports secret-redaction guards and credential masking utilities ensuring API keys,
bearer tokens, and private signing material never enter LLM prompts or logs.
"""
from atlas.ai.policy import scrub_secrets

__all__ = ["scrub_secrets"]
