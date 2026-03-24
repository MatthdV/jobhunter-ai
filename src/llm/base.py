"""Abstract LLM client interface."""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Common interface for all LLM provider clients."""

    @abstractmethod
    async def complete(self, prompt: str, max_tokens: int, system: str = "") -> str:
        """Send a completion request and return the text response.

        Args:
            prompt: The user message / prompt.
            max_tokens: Maximum tokens to generate.
            system: Optional system message (empty string = no system message).

        Returns:
            The generated text string.
        """
