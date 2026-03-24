"""DeepSeek LLM client — OpenAI-compatible API with custom base URL."""

from src.llm.openai_client import OpenAIClient

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekClient(OpenAIClient):
    """LLM client backed by the DeepSeek API (OpenAI-compatible)."""

    _KEY_ENV_NAME = "DEEPSEEK_API_KEY"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, base_url=_DEEPSEEK_BASE_URL)
