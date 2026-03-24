"""Tests for CV and cover letter generators — Phase 3."""

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import ConfigurationError

if TYPE_CHECKING:
    from src.generators.cover_letter import CoverLetterGenerator
    from src.generators.cv_generator import CVGenerator

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEST_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.yaml"

VALID_HIGHLIGHTS = (
    '{"experience_ids": ["exp_acme_automation"], "skill_ids": ["n8n"], "hook": "Great fit."}'
)


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
def cv_generator(monkeypatch: pytest.MonkeyPatch) -> "CVGenerator":
    from src.llm.base import LLMClient
    mock_llm: AsyncMock = AsyncMock(spec=LLMClient)
    mock_llm.complete = AsyncMock(return_value=VALID_HIGHLIGHTS)
    monkeypatch.setattr("src.generators.cv_generator._PROFILE_PATH", _TEST_PROFILE)
    from src.generators.cv_generator import CVGenerator
    return CVGenerator(client=mock_llm)


class TestCVGeneratorSelectHighlights:
    @pytest.mark.asyncio
    async def test_select_highlights_calls_llm_returns_dict(
        self, cv_generator: "CVGenerator"
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


class TestCVGeneratorInit:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.generators.cv_generator.get_client",
            MagicMock(side_effect=ConfigurationError("ANTHROPIC_API_KEY is required")),
        )
        monkeypatch.setattr(
            "src.generators.cv_generator.settings",
            MagicMock(llm_provider="anthropic"),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            from src.generators.cv_generator import CVGenerator
            CVGenerator()


class TestCVGeneratorFallback:
    @pytest.mark.asyncio
    async def test_generate_uses_fallback_when_select_highlights_raises(
        self, cv_generator: "CVGenerator", tmp_path: Path
    ) -> None:
        cv_generator._client.complete = AsyncMock(side_effect=Exception("LLM down"))

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
        assert called_with["skill_ids"] == []
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


class TestCVGeneratorHtmlToPdf:
    @pytest.mark.weasyprint
    def test_html_to_pdf_writes_nonempty_file(
        self, cv_generator: "CVGenerator", tmp_path: Path
    ) -> None:
        html = "<html><body><p>Test CV content</p></body></html>"
        output_path = tmp_path / "test.pdf"
        result = cv_generator._html_to_pdf(html, output_path)
        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestCVGeneratorGenerate:
    @pytest.mark.weasyprint
    @pytest.mark.asyncio
    async def test_generate_returns_existing_pdf_path(
        self, cv_generator: "CVGenerator", tmp_path: Path
    ) -> None:
        pdf_path = await cv_generator.generate(make_job(), tmp_path)
        assert pdf_path.exists()
        assert pdf_path.suffix == ".pdf"
        assert pdf_path.stat().st_size > 0
        assert "automation_engineer" in pdf_path.name
        assert "acme_corp" in pdf_path.name

    @pytest.mark.asyncio
    async def test_generate_output_filename_slugified(
        self, cv_generator: "CVGenerator", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cv_generator._html_to_pdf = lambda html, path: (path.write_bytes(b"%PDF"), path)[1]  # type: ignore[method-assign]
        pdf_path = await cv_generator.generate(
            make_job(title="Lead RevOps / Data Engineer", company="Acme Corp"), tmp_path
        )
        assert " " not in pdf_path.name
        assert "/" not in pdf_path.name


# ---------------------------------------------------------------------------
# CoverLetterGenerator tests
# ---------------------------------------------------------------------------


class TestCoverLetterGeneratorInit:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.generators.cover_letter.get_client",
            MagicMock(side_effect=ConfigurationError("ANTHROPIC_API_KEY is required")),
        )
        monkeypatch.setattr(
            "src.generators.cover_letter.settings",
            MagicMock(llm_provider="anthropic"),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            from src.generators.cover_letter import CoverLetterGenerator
            CoverLetterGenerator()


@pytest.fixture
def cl_generator(monkeypatch: pytest.MonkeyPatch) -> "CoverLetterGenerator":
    from src.llm.base import LLMClient
    mock_llm: AsyncMock = AsyncMock(spec=LLMClient)
    mock_llm.complete = AsyncMock(return_value="Voici ma lettre de motivation.")
    monkeypatch.setattr("src.generators.cover_letter._PROFILE_PATH", _TEST_PROFILE)
    from src.generators.cover_letter import CoverLetterGenerator
    return CoverLetterGenerator(client=mock_llm)


class TestCoverLetterDetectLanguage:
    def test_detect_language_returns_fr_for_french_job(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description=(
                "Nous recherchons un ingénieur en automatisation pour rejoindre notre équipe. "
                "Vous serez responsable de l'automatisation des processus CRM avec n8n et Python."
            )
        )
        assert cl_generator._detect_language(job) == "fr"

    def test_detect_language_returns_en_for_english_job(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description=(
                "We are looking for a senior automation engineer to join our platform team. "
                "You will be responsible for building and maintaining "
                "our workflow automation systems."
            )
        )
        assert cl_generator._detect_language(job) == "en"

    def test_detect_language_defaults_to_fr_for_empty_description(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(description="")
        assert cl_generator._detect_language(job) == "fr"


class TestCoverLetterBuildPrompt:
    def test_build_prompt_contains_forbidden_words_instruction(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job()
        prompt = cl_generator._build_prompt(job)
        assert "holistique" in prompt
        assert "synergique" in prompt
        assert "Never use" in prompt or "never use" in prompt.lower()

    def test_build_prompt_includes_job_title_and_company(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(title="Senior RevOps Engineer", company="Qonto")
        prompt = cl_generator._build_prompt(job)
        assert "Senior RevOps Engineer" in prompt
        assert "Qonto" in prompt

    def test_build_prompt_contains_language_instruction_french(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(description="Nous recherchons un ingénieur pour rejoindre notre équipe.")
        prompt = cl_generator._build_prompt(job)
        assert "French" in prompt or "french" in prompt.lower()

    def test_build_prompt_contains_language_instruction_english(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description=(
                "We are looking for an engineer to join our team "
                "and build automation workflows."
            )
        )
        prompt = cl_generator._build_prompt(job)
        assert "English" in prompt or "english" in prompt.lower()


@pytest.fixture
def mock_cl_client() -> AsyncMock:
    from src.llm.base import LLMClient
    client: AsyncMock = AsyncMock(spec=LLMClient)
    client.complete = AsyncMock(return_value="Voici ma lettre de motivation rédigée avec soin.")
    return client


@pytest.fixture
def cl_generator_with_mock(
    monkeypatch: pytest.MonkeyPatch, mock_cl_client: AsyncMock
) -> "CoverLetterGenerator":
    monkeypatch.setattr("src.generators.cover_letter._PROFILE_PATH", _TEST_PROFILE)
    from src.generators.cover_letter import CoverLetterGenerator
    return CoverLetterGenerator(client=mock_cl_client)


class TestCoverLetterGenerate:
    @pytest.mark.asyncio
    async def test_generate_returns_nonempty_string(
        self, cl_generator_with_mock: "CoverLetterGenerator"
    ) -> None:
        result = await cl_generator_with_mock.generate(make_job())
        assert isinstance(result, str)
        assert len(result) > 0


class TestCoverLetterRefine:
    @pytest.mark.asyncio
    async def test_refine_prompt_includes_letter_and_feedback(
        self, cl_generator_with_mock: "CoverLetterGenerator", mock_cl_client: AsyncMock
    ) -> None:
        application = MagicMock()
        application.cover_letter = "Ma lettre originale."
        application.job = make_job()
        feedback = "Rends le ton plus direct et mentionne n8n dès la première phrase."

        result = await cl_generator_with_mock.refine(application, feedback)

        assert isinstance(result, str)
        assert len(result) > 0
        call_args = mock_cl_client.complete.call_args
        prompt_content = call_args.kwargs.get("prompt") or call_args.args[0]
        assert "Ma lettre originale." in prompt_content
        assert feedback in prompt_content

    @pytest.mark.asyncio
    async def test_refine_raises_if_cover_letter_is_none(
        self, cl_generator_with_mock: "CoverLetterGenerator"
    ) -> None:
        application = MagicMock()
        application.cover_letter = None
        application.job = make_job()
        with pytest.raises(ValueError, match="cover_letter is None"):
            await cl_generator_with_mock.refine(application, "Some feedback")
