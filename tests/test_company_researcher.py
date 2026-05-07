"""Tests for company deep research (Feature 6)."""

import json
from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.analysis.company_researcher import CompanyInsight, CompanyResearcher
from src.llm.base import LLMClient
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Company, Job, JobStatus


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

FULL_RESEARCH_RESPONSE = json.dumps({
    "size_estimate": "200-500",
    "sector": "fintech",
    "funding_stage": "Series C",
    "tech_stack_signals": ["Python", "Kubernetes", "PostgreSQL"],
    "culture_signals": ["remote-first", "async communication"],
    "glassdoor_rating": 4.3,
    "growth_signals": ["hiring 50+ engineers", "just raised Series C"],
    "red_flags": [],
})

RED_FLAG_RESPONSE = json.dumps({
    "size_estimate": "50-200",
    "sector": "e-commerce",
    "funding_stage": "Series A",
    "tech_stack_signals": ["PHP", "MySQL"],
    "culture_signals": ["office-first"],
    "glassdoor_rating": 2.8,
    "growth_signals": [],
    "red_flags": ["high turnover on Glassdoor", "recent layoffs reported", "CEO controversy"],
})

PARTIAL_RESPONSE = json.dumps({
    "size_estimate": None,
    "sector": "ai",
    "funding_stage": None,
    "tech_stack_signals": ["Python"],
    "culture_signals": [],
    "glassdoor_rating": None,
    "growth_signals": [],
    "red_flags": [],
})

UNPARSEABLE_RESPONSE = "I don't know anything about that company."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    client = AsyncMock(spec=LLMClient)
    client.complete = AsyncMock(return_value=FULL_RESEARCH_RESPONSE)
    return client


@pytest.fixture
def researcher(mock_llm_client: AsyncMock) -> CompanyResearcher:
    return CompanyResearcher(llm_client=mock_llm_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResearchReturnsInsight:
    @pytest.mark.asyncio
    async def test_research_returns_full_insight(
        self, researcher: CompanyResearcher
    ) -> None:
        """research() should return a fully populated CompanyInsight."""
        insight = await researcher.research("Qonto")
        assert isinstance(insight, CompanyInsight)
        assert insight.size_estimate == "200-500"
        assert insight.sector == "fintech"
        assert insight.funding_stage == "Series C"
        assert "Python" in insight.tech_stack_signals
        assert "Kubernetes" in insight.tech_stack_signals
        assert insight.glassdoor_rating == 4.3
        assert "hiring 50+ engineers" in insight.growth_signals
        assert insight.red_flags == []

    @pytest.mark.asyncio
    async def test_research_with_website(
        self, researcher: CompanyResearcher, mock_llm_client: AsyncMock
    ) -> None:
        """Company website should be included in the prompt sent to the LLM."""
        await researcher.research("Qonto", website="https://qonto.com")
        call_args = mock_llm_client.complete.call_args
        assert "https://qonto.com" in call_args.kwargs.get("prompt", call_args[0][0] if call_args[0] else "")

    @pytest.mark.asyncio
    async def test_research_partial_data(
        self, researcher: CompanyResearcher, mock_llm_client: AsyncMock
    ) -> None:
        """Partial responses with nulls should not crash."""
        mock_llm_client.complete = AsyncMock(return_value=PARTIAL_RESPONSE)
        insight = await researcher.research("Unknown Startup")
        assert insight.size_estimate is None
        assert insight.sector == "ai"
        assert insight.funding_stage is None
        assert insight.glassdoor_rating is None

    @pytest.mark.asyncio
    async def test_research_unparseable_returns_empty_insight(
        self, researcher: CompanyResearcher, mock_llm_client: AsyncMock
    ) -> None:
        """Unparseable responses should return an empty CompanyInsight."""
        mock_llm_client.complete = AsyncMock(return_value=UNPARSEABLE_RESPONSE)
        insight = await researcher.research("Fake Corp")
        assert insight.size_estimate is None
        assert insight.sector is None
        assert insight.tech_stack_signals == []
        assert insight.red_flags == []


class TestEnrichCompanyPersists:
    @pytest.mark.asyncio
    async def test_enrich_company_persists(
        self, researcher: CompanyResearcher
    ) -> None:
        """enrich_company_model() should update Company columns in DB."""
        with get_session() as session:
            company = Company(name="Qonto")
            session.add(company)
            session.flush()
            company_id = company.id

            await researcher.enrich_company_model(company, session)

        # Re-read from DB to confirm persistence
        with get_session() as session:
            db_company = session.get(Company, company_id)
            assert db_company is not None
            assert db_company.funding_stage == "Series C"
            assert db_company.glassdoor_rating == 4.3
            assert db_company.researched_at is not None
            tech = json.loads(db_company.tech_stack_signals)
            assert "Python" in tech
            assert "Kubernetes" in tech

    @pytest.mark.asyncio
    async def test_enrich_does_not_overwrite_existing_sector(
        self, researcher: CompanyResearcher
    ) -> None:
        """Existing sector should not be overwritten by research."""
        with get_session() as session:
            company = Company(name="Qonto", sector="banking")
            session.add(company)
            session.flush()

            await researcher.enrich_company_model(company, session)
            assert company.sector == "banking"  # kept original


class TestRedFlagsDetected:
    @pytest.mark.asyncio
    async def test_red_flags_detected(
        self, researcher: CompanyResearcher, mock_llm_client: AsyncMock
    ) -> None:
        """Red flags from LLM response should be correctly parsed."""
        mock_llm_client.complete = AsyncMock(return_value=RED_FLAG_RESPONSE)
        insight = await researcher.research("Sketchy Inc")
        assert len(insight.red_flags) == 3
        assert "high turnover on Glassdoor" in insight.red_flags
        assert "recent layoffs reported" in insight.red_flags
        assert insight.glassdoor_rating == 2.8

    @pytest.mark.asyncio
    async def test_red_flags_persisted_in_db(
        self, researcher: CompanyResearcher, mock_llm_client: AsyncMock
    ) -> None:
        """Red flags should be stored as JSON in the DB."""
        mock_llm_client.complete = AsyncMock(return_value=RED_FLAG_RESPONSE)
        with get_session() as session:
            company = Company(name="Sketchy Inc")
            session.add(company)
            session.flush()
            company_id = company.id

            await researcher.enrich_company_model(company, session)

        with get_session() as session:
            db_company = session.get(Company, company_id)
            flags = json.loads(db_company.red_flags)
            assert len(flags) == 3


class TestResearchPhaseSkipsAlreadyResearched:
    @pytest.mark.asyncio
    async def test_skip_already_researched(
        self, mock_llm_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_research_phase should skip companies with researched_at set."""
        from src.scheduler.job_scheduler import JobScheduler

        monkeypatch.setattr(
            "src.analysis.company_researcher.get_client",
            lambda _: mock_llm_client,
        )

        scheduler = JobScheduler(
            scorer=MagicMock(),
            cv_gen=MagicMock(),
            cl_gen=MagicMock(),
        )

        with get_session() as session:
            # Company already researched
            company_done = Company(
                name="Already Done Inc",
                researched_at=datetime.utcnow(),
            )
            session.add(company_done)
            session.flush()

            job_done = Job(
                title="Engineer",
                url="https://example.com/job/done",
                source="linkedin",
                status=JobStatus.NEW,
                company_id=company_done.id,
            )
            session.add(job_done)
            session.flush()

        count = await scheduler._research_phase()
        assert count == 0
        mock_llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_researches_unresearched_company(
        self, mock_llm_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_research_phase should research companies without researched_at."""
        from src.scheduler.job_scheduler import JobScheduler

        monkeypatch.setattr(
            "src.analysis.company_researcher.get_client",
            lambda _: mock_llm_client,
        )

        scheduler = JobScheduler(
            scorer=MagicMock(),
            cv_gen=MagicMock(),
            cl_gen=MagicMock(),
        )

        with get_session() as session:
            company = Company(name="New Startup")
            session.add(company)
            session.flush()

            job = Job(
                title="Engineer",
                url="https://example.com/job/new",
                source="linkedin",
                status=JobStatus.NEW,
                company_id=company.id,
            )
            session.add(job)
            session.flush()

        count = await scheduler._research_phase()
        assert count == 1
        mock_llm_client.complete.assert_called_once()


class TestCompanyInsightDataclass:
    def test_defaults(self) -> None:
        """CompanyInsight should have sane defaults."""
        insight = CompanyInsight()
        assert insight.size_estimate is None
        assert insight.sector is None
        assert insight.tech_stack_signals == []
        assert insight.red_flags == []
        assert insight.glassdoor_rating is None

    def test_full_init(self) -> None:
        """CompanyInsight should accept all fields."""
        insight = CompanyInsight(
            size_estimate="1000+",
            sector="ai",
            funding_stage="Series B",
            tech_stack_signals=["Python", "Rust"],
            culture_signals=["remote-first"],
            glassdoor_rating=4.5,
            growth_signals=["IPO planned"],
            red_flags=["CEO turnover"],
        )
        assert insight.funding_stage == "Series B"
        assert len(insight.tech_stack_signals) == 2
