"""Tests for the matching / scoring pipeline — Phase 2."""

import json
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest
from sqlalchemy import select

from src.config.settings import ConfigurationError
from src.matching.scorer import Scorer, ScoreResult, ScoringError
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Job, JobStatus, MatchResult

_RATE_LIMIT_RESPONSE = httpx.Response(
    429, request=httpx.Request("GET", "https://api.anthropic.com")
)

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


class TestScoreBatch:
    @pytest.mark.asyncio
    async def test_score_batch_returns_all_results_in_order(
        self, scorer: Scorer
    ) -> None:
        with get_session() as session:
            jobs = [  # noqa: E501
                make_job(title=f"Job {i}", url=f"https://example.com/job/{i}")
                for i in range(3)
            ]
            for job in jobs:
                session.add(job)
            session.flush()
            results = await scorer.score_batch(jobs, session)
            assert len(results) == 3
            assert all(isinstance(r, MatchResult) for r in results)

    @pytest.mark.asyncio
    async def test_score_batch_raises_on_any_scoring_error(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """Fail-fast: if one job raises ScoringError, score_batch raises."""
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(content=[MagicMock(text="not json")])
        )
        with get_session() as session:
            jobs = [make_job(url=f"https://example.com/batch/{i}") for i in range(2)]
            for job in jobs:
                session.add(job)
            session.flush()
            with pytest.raises(ScoringError):
                await scorer.score_batch(jobs, session)


class TestScoreAndPersist:
    @pytest.mark.asyncio
    async def test_score_and_persist_above_threshold_sets_matched(
        self, scorer: Scorer
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr = await scorer.score_and_persist(job, session)
            assert mr.score == 85.0
            assert job.status == JobStatus.MATCHED
            assert job.match_score == 85.0

    @pytest.mark.asyncio
    async def test_score_and_persist_below_threshold_sets_skipped(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        low_response = json.dumps({
            "score": 50,
            "reasoning": "Poor fit.",
            "strengths": [],
            "concerns": ["No Python"],
        })
        msg = MagicMock()
        msg.content = [MagicMock(text=low_response)]
        mock_client.messages.create = AsyncMock(return_value=msg)
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr = await scorer.score_and_persist(job, session)
            assert mr.score == 50.0
            assert job.status == JobStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_score_and_persist_upserts_existing_match_result(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """Second call updates existing MatchResult in-place instead of inserting."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            await scorer.score_and_persist(job, session)
            first_id = job.match_result.id

            updated_response = json.dumps({
                "score": 90,
                "reasoning": "Even better fit.",
                "strengths": ["Python"],
                "concerns": [],
            })
            msg = MagicMock()
            msg.content = [MagicMock(text=updated_response)]
            mock_client.messages.create = AsyncMock(return_value=msg)

            await scorer.score_and_persist(job, session)
            assert job.match_result.id == first_id
            assert job.match_result.score == 90.0
            count = session.execute(
                select(MatchResult).where(MatchResult.job_id == job.id)
            ).scalars().all()
            assert len(count) == 1


class TestScore:
    @pytest.mark.asyncio
    async def test_score_calls_claude_returns_score_result(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        job = make_job()
        result = await scorer.score(job)
        assert isinstance(result, ScoreResult)
        assert result.score == 85.0
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_retries_on_rate_limit(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score() retries on RateLimitError and succeeds on 3rd attempt."""
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=VALID_RESPONSE)]
        rate_limit_error = anthropic.RateLimitError(
            message="rate limit", response=_RATE_LIMIT_RESPONSE, body={}
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[rate_limit_error, rate_limit_error, good_msg]
        )
        with patch("asyncio.sleep"):
            result = await scorer.score(job=make_job())
        assert result.score == 85.0
        assert mock_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_score_raises_after_max_retries(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score() propagates RateLimitError after 3 retries."""
        rate_limit_error = anthropic.RateLimitError(
            message="rate limit", response=_RATE_LIMIT_RESPONSE, body={}
        )
        mock_client.messages.create = AsyncMock(side_effect=rate_limit_error)
        with patch("asyncio.sleep"), pytest.raises(anthropic.RateLimitError):
            await scorer.score(job=make_job())


class TestParseResponse:
    def test_parse_response_valid_json(self, scorer: Scorer) -> None:
        result = scorer._parse_response(VALID_RESPONSE)
        assert isinstance(result, ScoreResult)
        assert result.score == 85.0
        assert "automation" in result.reasoning
        assert "n8n expertise" in result.strengths
        assert "No Salesforce listed" in result.concerns

    def test_parse_response_handles_malformed_json(self, scorer: Scorer) -> None:
        wrapped = (
            'Sure! Here is the result: {"score": 70, "reasoning": "OK",'
            ' "strengths": [], "concerns": []} done.'
        )
        result = scorer._parse_response(wrapped)
        assert result.score == 70.0

    def test_parse_response_raises_scoring_error_on_garbage(self, scorer: Scorer) -> None:
        with pytest.raises(ScoringError) as exc_info:
            scorer._parse_response("this is not json at all")
        assert exc_info.value.raw == "this is not json at all"


class TestBuildPrompt:
    def test_build_prompt_includes_job_title(self, scorer: Scorer) -> None:
        job = make_job(title="Senior DevOps Engineer")
        prompt = scorer._build_prompt(job)
        assert "Senior DevOps Engineer" in prompt

    def test_build_prompt_includes_salary_range(self, scorer: Scorer) -> None:
        job = make_job(salary_min=90000, salary_max=130000)
        prompt = scorer._build_prompt(job)
        assert "90000" in prompt
        assert "130000" in prompt

    def test_build_prompt_handles_none_description(self, scorer: Scorer) -> None:
        job = make_job(description=None)
        prompt = scorer._build_prompt(job)
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestEmbeddingMatcher:
    @pytest.mark.asyncio
    async def test_filter_removes_low_similarity_jobs(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_identical_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_orthogonal_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher
