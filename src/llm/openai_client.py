"""OpenAI-compatible LLM client (GPT-4o, GPT-4-turbo, o1, etc.)."""


import openai

from src.config.settings import ConfigurationError
from src.llm.base import LLMClient


class OpenAIClient(LLMClient):
    """LLM client backed by the OpenAI API (or compatible endpoint)."""

    _KEY_ENV_NAME: str = "OPENAI_API_KEY"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(f"{self._KEY_ENV_NAME} is required for AI features")
        self._model = model
        self._raw = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(self, prompt: str, max_tokens: int, system: str = "") -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._raw.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content or ""
