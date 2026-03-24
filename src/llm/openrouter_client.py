"""OpenRouter LLM client — OpenAI-compatible API, access to 100+ models."""

from src.llm.openai_client import OpenAIClient

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient(OpenAIClient):
    """LLM client backed by OpenRouter (OpenAI-compatible, 100+ models)."""

    _KEY_ENV_NAME = "OPENROUTER_API_KEY"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, base_url=_OPENROUTER_BASE_URL)
