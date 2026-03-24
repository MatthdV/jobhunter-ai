"""Tests for the src/llm/ abstraction layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

from src.llm.base import LLMClient


# ---------------------------------------------------------------------------
# AnthropicClient tests
# ---------------------------------------------------------------------------

_RATE_LIMIT_RESPONSE = httpx.Response(
    429, request=httpx.Request("GET", "https://api.anthropic.com")
)


@pytest.fixture
def mock_anthropic_raw_client() -> AsyncMock:
    """Mocked anthropic.AsyncAnthropic that returns 'hello world'."""
    raw = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text="hello world")]
    raw.messages.create = AsyncMock(return_value=msg)
    return raw


@pytest.fixture
def anthropic_client(mock_anthropic_raw_client: AsyncMock) -> "AnthropicClient":
    from src.llm.anthropic_client import AnthropicClient
    with patch("anthropic.AsyncAnthropic", return_value=mock_anthropic_raw_client):
        return AnthropicClient(api_key="test-key", model="claude-opus-4-6")


class TestAnthropicClientInit:
    def test_raises_configuration_error_without_api_key(self) -> None:
        from src.config.settings import ConfigurationError
        from src.llm.anthropic_client import AnthropicClient
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            AnthropicClient(api_key="", model="claude-opus-4-6")


class TestAnthropicClientComplete:
    @pytest.mark.asyncio
    async def test_complete_returns_text(
        self, anthropic_client: "AnthropicClient", mock_anthropic_raw_client: AsyncMock
    ) -> None:
        result = await anthropic_client.complete(
            prompt="test prompt", max_tokens=100
        )
        assert result == "hello world"
        mock_anthropic_raw_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_passes_system_message(
        self, anthropic_client: "AnthropicClient", mock_anthropic_raw_client: AsyncMock
    ) -> None:
        await anthropic_client.complete(
            prompt="test", max_tokens=100, system="be concise"
        )
        call_kwargs = mock_anthropic_raw_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "be concise"

    @pytest.mark.asyncio
    async def test_complete_omits_system_when_empty(
        self, anthropic_client: "AnthropicClient", mock_anthropic_raw_client: AsyncMock
    ) -> None:
        await anthropic_client.complete(prompt="test", max_tokens=100, system="")
        call_kwargs = mock_anthropic_raw_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs or call_kwargs.get("system", "") == ""

    @pytest.mark.asyncio
    async def test_complete_retries_on_rate_limit(
        self, anthropic_client: "AnthropicClient", mock_anthropic_raw_client: AsyncMock
    ) -> None:
        """complete() retries on RateLimitError and succeeds on 3rd attempt."""
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text="ok")]
        rate_limit_error = anthropic.RateLimitError(
            message="rate limit", response=_RATE_LIMIT_RESPONSE, body={}
        )
        mock_anthropic_raw_client.messages.create = AsyncMock(
            side_effect=[rate_limit_error, rate_limit_error, good_msg]
        )
        with patch("asyncio.sleep"):
            result = await anthropic_client.complete("prompt", 100)
        assert result == "ok"
        assert mock_anthropic_raw_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_complete_raises_after_max_retries(
        self, anthropic_client: "AnthropicClient", mock_anthropic_raw_client: AsyncMock
    ) -> None:
        rate_limit_error = anthropic.RateLimitError(
            message="rate limit", response=_RATE_LIMIT_RESPONSE, body={}
        )
        mock_anthropic_raw_client.messages.create = AsyncMock(
            side_effect=rate_limit_error
        )
        with patch("asyncio.sleep"), pytest.raises(anthropic.RateLimitError):
            await anthropic_client.complete("prompt", 100)


# ---------------------------------------------------------------------------
# OpenAIClient tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_raw_client() -> AsyncMock:
    raw = AsyncMock()
    choice = MagicMock()
    choice.message.content = "openai response"
    raw.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[choice])
    )
    return raw


@pytest.fixture
def openai_client(mock_openai_raw_client: AsyncMock) -> "OpenAIClient":
    pytest.importorskip("openai")
    from src.llm.openai_client import OpenAIClient
    with patch("openai.AsyncOpenAI", return_value=mock_openai_raw_client):
        return OpenAIClient(api_key="test-key", model="gpt-4o")


class TestOpenAIClientInit:
    def test_raises_configuration_error_without_api_key(self) -> None:
        pytest.importorskip("openai")
        from src.config.settings import ConfigurationError
        from src.llm.openai_client import OpenAIClient
        with patch("openai.AsyncOpenAI"):
            with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
                OpenAIClient(api_key="", model="gpt-4o")


class TestOpenAIClientComplete:
    @pytest.mark.asyncio
    async def test_complete_returns_text(
        self, openai_client: "OpenAIClient", mock_openai_raw_client: AsyncMock
    ) -> None:
        result = await openai_client.complete(prompt="test", max_tokens=100)
        assert result == "openai response"

    @pytest.mark.asyncio
    async def test_complete_includes_system_message_in_messages(
        self, openai_client: "OpenAIClient", mock_openai_raw_client: AsyncMock
    ) -> None:
        await openai_client.complete(prompt="test", max_tokens=100, system="be concise")
        call_kwargs = mock_openai_raw_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "be concise"}
        assert messages[1] == {"role": "user", "content": "test"}

    @pytest.mark.asyncio
    async def test_complete_without_system_sends_only_user_message(
        self, openai_client: "OpenAIClient", mock_openai_raw_client: AsyncMock
    ) -> None:
        await openai_client.complete(prompt="test", max_tokens=100)
        call_kwargs = mock_openai_raw_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
