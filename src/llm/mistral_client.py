"""Mistral AI LLM client."""

from src.config.settings import ConfigurationError
from src.llm.base import LLMClient


class MistralClient(LLMClient):
    """LLM client backed by the Mistral AI API."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ConfigurationError("MISTRAL_API_KEY is required for AI features")
        self._model = model
        from mistralai.client import Mistral  # deferred import — mistralai is optional
        self._raw = Mistral(api_key=api_key)

    async def complete(self, prompt: str, max_tokens: int, system: str = "") -> str:
        from mistralai.client.models import SystemMessage, UserMessage
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(UserMessage(content=prompt))

        response = await self._raw.chat.complete_async(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        content = response.choices[0].message.content
        return content if isinstance(content, str) else ""
