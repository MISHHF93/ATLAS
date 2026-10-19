"""Provider-independent research interface."""

from typing import Protocol

from atlas.ai.schemas import MarketResearchResult


class LLMProvider(Protocol):
    """A research model. Implementations must not place or cancel orders."""

    def analyze(self, market_context: str) -> MarketResearchResult:
        """Interpret observations. The result is not a trade authorization."""
