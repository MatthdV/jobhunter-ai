"""Tests for CV and cover letter generators — Phase 3."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ConfigurationError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEST_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.yaml"

VALID_HIGHLIGHTS = '{"experience_ids": ["exp_acme_automation"], "skill_ids": ["n8n"], "hook": "Great fit."}'


def make_job(**kwargs: Any) -> MagicMock:
    job = MagicMock()
    job.title = kwargs.get("title", "Automation Engineer")
    job.description = kwargs.get("description", "Seeking an n8n expert with Python skills.")
    job.company = MagicMock()
    job.company.name = kwargs.get("company", "Acme Corp")
    return job


# ---------------------------------------------------------------------------
# CVGenerator tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cv_client() -> AsyncMock:
    client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=VALID_HIGHLIGHTS)]
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.fixture
def cv_generator(monkeypatch: pytest.MonkeyPatch, mock_cv_client: AsyncMock) -> "CVGenerator":
    monkeypatch.setattr(
        "src.generators.cv_generator.settings",
        MagicMock(anthropic_api_key="test-key", anthropic_model="claude-opus-4-6"),
    )
    monkeypatch.setattr("src.generators.cv_generator._PROFILE_PATH", _TEST_PROFILE)
    with patch("src.generators.cv_generator.anthropic.AsyncAnthropic", return_value=mock_cv_client):
        from src.generators.cv_generator import CVGenerator
        return CVGenerator()


class TestCVGeneratorSelectHighlights:
    @pytest.mark.asyncio
    async def test_select_highlights_calls_claude_returns_dict(
        self, cv_generator: "CVGenerator", mock_cv_client: AsyncMock
    ) -> None:
        job = make_job()
        result = await cv_generator._select_highlights(job)

        assert isinstance(result, dict)
        assert "experience_ids" in result
        assert isinstance(result["experience_ids"], list)
        assert "skill_ids" in result
        assert isinstance(result["skill_ids"], list)
        assert "hook" in result
        assert isinstance(result["hook"], str)
        mock_cv_client.messages.create.assert_called_once()
        call_kwargs = mock_cv_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 256


class TestCVGeneratorInit:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.generators.cv_generator.settings",
            MagicMock(anthropic_api_key="", anthropic_model="claude-opus-4-6"),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            from src.generators.cv_generator import CVGenerator
            CVGenerator()
