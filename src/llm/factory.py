"""Factory: instantiate the correct LLMClient based on provider name."""

from src.config.settings import settings
from src.llm.base import LLMClient

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-4o",
    "mistral": "mistral-large-latest",
    "deepseek": "deepseek-chat",
    "openrouter": "openai/gpt-4o",
}


def get_client(provider: str) -> LLMClient:
    """Return an LLMClient instance for the given provider name.

    Args:
        provider: One of "anthropic", "openai", "mistral", "deepseek", "openrouter".

    Raises:
        ValueError: If the provider is not recognised.
        ConfigurationError: If the required API key is missing.
    """
    model = settings.llm_model or _DEFAULT_MODELS.get(provider, "")

    if provider == "anthropic":
        from src.llm.anthropic_client import AnthropicClient
        return AnthropicClient(api_key=settings.anthropic_api_key, model=model)

    if provider == "openai":
        from src.llm.openai_client import OpenAIClient
        return OpenAIClient(api_key=settings.openai_api_key, model=model)

    if provider == "mistral":
        from src.llm.mistral_client import MistralClient
        return MistralClient(api_key=settings.mistral_api_key, model=model)

    if provider == "deepseek":
        from src.llm.deepseek_client import DeepSeekClient
        return DeepSeekClient(api_key=settings.deepseek_api_key, model=model)

    if provider == "openrouter":
        from src.llm.openrouter_client import OpenRouterClient
        return OpenRouterClient(api_key=settings.openrouter_api_key, model=model)

    raise ValueError(f"Unknown LLM provider: {provider!r}")
