"""Configuration for the ATLAS multi-agent research graph."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class MultiAgentConfig:
    root_dir: Path = field(default_factory=lambda: Path(os.environ.get("ATLAS_MULTI_AGENT_DIR", "var/multi_agent")))
    debate_rounds: int = 2
    max_parallel_analysts: int = 4
    analyst_timeout_seconds: float = 20.0
    node_timeout_seconds: float = 60.0
    max_retries: int = 1
    directional_threshold: float = 3.0
    min_reports_for_debate: int = 1
    default_notional_usd: float = 1000.0
    default_timeframe: str = "15m"
    enable_llm: bool = False
    llm_model: str = ""
    llm_deep_model: str = ""
    prompt_version: str = "multi-agent-v1"
    allow_network_fundamentals: bool = True
    max_news_items: int = 40
    max_macro_events: int = 40
    store_audit_payloads: bool = True

    @classmethod
    def from_env(cls) -> "MultiAgentConfig":
        return cls(
            root_dir=Path(os.environ.get("ATLAS_MULTI_AGENT_DIR", "var/multi_agent")),
            debate_rounds=max(0, min(5, _env_int("ATLAS_MULTI_AGENT_DEBATE_ROUNDS", 2))),
            max_parallel_analysts=max(1, min(8, _env_int("ATLAS_MULTI_AGENT_MAX_PARALLEL", 4))),
            analyst_timeout_seconds=max(1.0, _env_float("ATLAS_MULTI_AGENT_ANALYST_TIMEOUT_S", 20.0)),
            node_timeout_seconds=max(5.0, _env_float("ATLAS_MULTI_AGENT_NODE_TIMEOUT_S", 60.0)),
            max_retries=max(0, min(3, _env_int("ATLAS_MULTI_AGENT_MAX_RETRIES", 1))),
            directional_threshold=max(0.1, _env_float("ATLAS_MULTI_AGENT_DIRECTIONAL_THRESHOLD", 3.0)),
            default_notional_usd=max(1.0, _env_float("ATLAS_MULTI_AGENT_DEFAULT_NOTIONAL_USD", 1000.0)),
            default_timeframe=os.environ.get("ATLAS_MULTI_AGENT_DEFAULT_TIMEFRAME", "15m"),
            enable_llm=_env_bool("ATLAS_MULTI_AGENT_LLM", False),
            llm_model=os.environ.get("ATLAS_MULTI_AGENT_LLM_MODEL", ""),
            llm_deep_model=os.environ.get("ATLAS_MULTI_AGENT_LLM_DEEP_MODEL", ""),
            prompt_version=os.environ.get("ATLAS_MULTI_AGENT_PROMPT_VERSION", "multi-agent-v1"),
            allow_network_fundamentals=_env_bool("ATLAS_MULTI_AGENT_NETWORK_FUNDAMENTALS", True),
            max_news_items=max(1, min(200, _env_int("ATLAS_MULTI_AGENT_MAX_NEWS", 40))),
            max_macro_events=max(1, min(200, _env_int("ATLAS_MULTI_AGENT_MAX_MACRO", 40))),
            store_audit_payloads=_env_bool("ATLAS_MULTI_AGENT_STORE_AUDIT_PAYLOADS", True),
        )

    @property
    def db_path(self) -> Path:
        return self.root_dir / "multi_agent.sqlite"

    @property
    def audit_dir(self) -> Path:
        return self.root_dir / "audit"

    @property
    def reflections_path(self) -> Path:
        return self.root_dir / "reflections.jsonl"

    @property
    def checkpoints_dir(self) -> Path:
        return self.root_dir / "checkpoints"

    def ensure_dirs(self) -> None:
        for p in (self.root_dir, self.audit_dir, self.checkpoints_dir):
            p.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "debate_rounds": self.debate_rounds,
            "max_parallel_analysts": self.max_parallel_analysts,
            "analyst_timeout_seconds": self.analyst_timeout_seconds,
            "node_timeout_seconds": self.node_timeout_seconds,
            "max_retries": self.max_retries,
            "directional_threshold": self.directional_threshold,
            "default_notional_usd": self.default_notional_usd,
            "default_timeframe": self.default_timeframe,
            "llm_enabled": self.enable_llm,
            "prompt_version": self.prompt_version,
            "execution_permission": "none",
        }
