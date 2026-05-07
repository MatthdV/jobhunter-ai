"""Tests for scorer multi-country support (Task 6)."""

from unittest.mock import AsyncMock

import pytest

from src.llm.base import LLMClient
from src.matching.scorer import Scorer
from src.storage.models import Job


def _make_scorer() -> Scorer:
    """Create a Scorer with a mock LLM client."""
    mock_client = AsyncMock(spec=LLMClient)
    return Scorer(client=mock_client)


def _make_job_us() -> Job:
    return Job(
        title="Automation Engineer",
        url="https://example.com/job/1",
        source="indeed_api",
        description="Remote automation role.",
        salary_raw="$100,000 - $120,000",
        salary_min=100_000,
        salary_max=120_000,
        country_code="US",
        salary_currency="USD",
        salary_normalized_min=108_235,
        salary_normalized_max=129_882,
        is_remote=True,
        contract_type="CDI",
    )


class TestScorerMultiCountry:
    def test_build_prompt_includes_country(self) -> None:
        scorer = _make_scorer()
        job = _make_job_us()
        prompt = scorer._build_prompt(job)
        assert "US" in prompt
        assert "Country" in prompt

    def test_build_prompt_includes_normalized_salary(self) -> None:
        scorer = _make_scorer()
        job = _make_job_us()
        prompt = scorer._build_prompt(job)
        assert "PPP-normalized" in prompt or "normalized" in prompt.lower()
        assert "108235" in prompt or "108,235" in prompt

    def test_build_prompt_includes_original_currency(self) -> None:
        scorer = _make_scorer()
        job = _make_job_us()
        prompt = scorer._build_prompt(job)
        assert "USD" in prompt

    def test_build_prompt_fr_job_still_works(self) -> None:
        scorer = _make_scorer()
        job = Job(
            title="Automation Engineer",
            url="https://example.com/job/2",
            source="wttj",
            description="Role in France.",
            salary_min=80_000,
            salary_max=100_000,
            country_code="FR",
            salary_currency="EUR",
            is_remote=True,
        )
        prompt = scorer._build_prompt(job)
        assert "FR" in prompt
