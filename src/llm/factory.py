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


def get_client(
    provider: str, model: str | None = None, api_key: str | None = None
) -> LLMClient:
    """Return an LLMClient instance for the given provider name.

    Args:
        provider: One of "anthropic", "openai", "mistral", "deepseek", "openrouter".
        model: Optional model override. Falls back to settings.llm_model, then provider default.
        api_key: Optional key override (e.g. a per-user key). Falls back to the
            matching global settings key when None.

    Raises:
        ValueError: If the provider is not recognised.
        ConfigurationError: If the required API key is missing.
    """
    model = model or settings.llm_model or _DEFAULT_MODELS.get(provider, "")

    if provider == "anthropic":
        from src.llm.anthropic_client import AnthropicClient
        return AnthropicClient(api_key=api_key or settings.anthropic_api_key, model=model)

    if provider == "openai":
        from src.llm.openai_client import OpenAIClient
        return OpenAIClient(api_key=api_key or settings.openai_api_key, model=model)

    if provider == "mistral":
        from src.llm.mistral_client import MistralClient
        return MistralClient(api_key=api_key or settings.mistral_api_key, model=model)

    if provider == "deepseek":
        from src.llm.deepseek_client import DeepSeekClient
        return DeepSeekClient(api_key=api_key or settings.deepseek_api_key, model=model)

    if provider == "openrouter":
        from src.llm.openrouter_client import OpenRouterClient
        return OpenRouterClient(api_key=api_key or settings.openrouter_api_key, model=model)

    raise ValueError(f"Unknown LLM provider: {provider!r}")
