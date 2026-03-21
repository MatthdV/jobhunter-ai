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


class TestCVGeneratorFallback:
    @pytest.mark.asyncio
    async def test_generate_uses_fallback_when_select_highlights_raises(
        self, cv_generator: "CVGenerator", mock_cv_client: AsyncMock, tmp_path: Path
    ) -> None:
        mock_cv_client.messages.create = AsyncMock(side_effect=Exception("Claude down"))

        # _render_html and _html_to_pdf are still NotImplementedError at this slice.
        # Patch them directly on the instance to isolate the fallback logic.
        called_with: dict[str, Any] = {}

        def fake_render(context: dict[str, Any]) -> str:
            called_with.update(context)
            return "<html>fallback</html>"

        def fake_pdf(html: str, output_path: Path) -> Path:
            output_path.write_bytes(b"%PDF fallback")
            return output_path

        cv_generator._render_html = fake_render  # type: ignore[method-assign]
        cv_generator._html_to_pdf = fake_pdf  # type: ignore[method-assign]

        await cv_generator.generate(make_job(), tmp_path)

        assert "experiences" in called_with
        assert "skill_ids" in called_with
        assert called_with["skill_ids"] == []   # fallback: no highlights
        assert called_with["hook"] == ""


class TestCVGeneratorRenderHtml:
    def test_render_html_includes_candidate_name(self, cv_generator: "CVGenerator") -> None:
        import yaml
        profile = yaml.safe_load(_TEST_PROFILE.read_text())
        context: dict[str, Any] = {
            "candidate": profile["candidate"],
            "experiences": profile["experiences"][:2],
            "skills_all": ["n8n", "Python"],
            "skill_ids": ["n8n"],
            "education": profile.get("education", []),
            "projects": profile.get("projects", []),
            "hook": "Great fit for this role.",
        }
        html = cv_generator._render_html(context)
        assert "Test Candidate" in html
        assert "<strong>n8n</strong>" in html
