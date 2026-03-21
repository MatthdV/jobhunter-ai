"""Tests for the matching / scoring pipeline — Phase 2."""

import json
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest
from sqlalchemy import select

from src.config.settings import ConfigurationError
from src.matching.scorer import ScoreResult, Scorer, ScoringError
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Job, JobStatus, MatchResult

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_RESPONSE = json.dumps({
    "score": 85,
    "reasoning": "Strong match on automation and AI stack.",
    "strengths": ["n8n expertise", "AI automation background"],
    "concerns": ["No Salesforce listed"],
})


def make_job(**kwargs: object) -> Job:
    defaults: dict[str, object] = {
        "title": "Automation Engineer",
        "url": "https://example.com/job/1",
        "source": "linkedin",
        "description": "Seeking an n8n automation expert with Python skills.",
        "salary_raw": "90-120k EUR",
        "salary_min": 90000,
        "salary_max": 120000,
        "is_remote": True,
        "location": "Full Remote",
        "contract_type": "CDI",
    }
    defaults.update(kwargs)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# DB fixtures — autouse resets to empty in-memory SQLite for every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


# ---------------------------------------------------------------------------
# Scorer fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> AsyncMock:
    """Mocked AsyncAnthropic client that returns VALID_RESPONSE by default."""
    client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=VALID_RESPONSE)]
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.fixture
def scorer(monkeypatch: pytest.MonkeyPatch, mock_client: AsyncMock) -> Scorer:
    """Scorer with mocked settings (no real API key) and mocked Anthropic client."""
    monkeypatch.setattr(
        "src.matching.scorer.settings",
        MagicMock(
            anthropic_api_key="test-key",
            anthropic_model="claude-opus-4-6",
            min_match_score=80,
        ),
    )
    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        return Scorer()


# ---------------------------------------------------------------------------
# Task 1 — MatchResult model
# ---------------------------------------------------------------------------


class TestMatchResult:
    def test_match_result_can_be_inserted_and_queried(self) -> None:
        """MatchResult rows survive a round-trip through in-memory SQLite."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr = MatchResult(
                job_id=job.id,
                score=85.0,
                reasoning="Good fit",
                strengths_json='["n8n", "Python"]',
                concerns_json='["No Salesforce"]',
                model_used="claude-opus-4-6",
            )
            session.add(mr)
            session.flush()
            assert mr.id is not None
            assert mr.score == 85.0
            assert mr.job_id == job.id

    def test_job_match_result_relationship(self) -> None:
        """Job.match_result back-reference works."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr = MatchResult(
                job_id=job.id,
                score=72.0,
                reasoning="Decent fit",
                strengths_json="[]",
                concerns_json="[]",
                model_used="claude-opus-4-6",
            )
            session.add(mr)
            session.flush()
            session.refresh(job)
            assert job.match_result is not None
            assert job.match_result.score == 72.0


# ---------------------------------------------------------------------------
# Scorer tests — filled in during Tasks 2–9
# ---------------------------------------------------------------------------


class TestScorer:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scorer.__init__ raises ConfigurationError when API key is empty."""
        monkeypatch.setattr(
            "src.matching.scorer.settings",
            MagicMock(anthropic_api_key="", anthropic_model="claude-opus-4-6", min_match_score=80),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            Scorer()


class TestEmbeddingMatcher:
    @pytest.mark.asyncio
    async def test_filter_removes_low_similarity_jobs(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_identical_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_orthogonal_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher
