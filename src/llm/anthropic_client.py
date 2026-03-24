"""Anthropic (Claude) LLM client with built-in rate-limit retry."""

import asyncio

import anthropic

from src.config.settings import ConfigurationError
from src.llm.base import LLMClient

_RETRY_DELAYS = [0, 2, 4]


class AnthropicClient(LLMClient):
    """LLM client backed by the Anthropic Claude API."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for AI features")
        self._model = model
        self._raw = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, prompt: str, max_tokens: int, system: str = "") -> str:
        last_error: anthropic.RateLimitError | None = None
        messages: list[anthropic.types.MessageParam] = [
            {"role": "user", "content": prompt}
        ]
        for delay in _RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                if system:
                    response = await self._raw.messages.create(
                        model=self._model,
                        max_tokens=max_tokens,
                        messages=messages,
                        system=system,
                    )
                else:
                    response = await self._raw.messages.create(
                        model=self._model,
                        max_tokens=max_tokens,
                        messages=messages,
                    )
                text = next(
                    (block.text for block in response.content if hasattr(block, "text")),
                    "",
                )
                return str(text)
            except anthropic.RateLimitError as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]
