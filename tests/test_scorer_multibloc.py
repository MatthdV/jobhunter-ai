"""Tests for multi-bloc A-F scorer evaluation (Feature 1)."""

import json
from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from src.llm.base import LLMClient
from src.matching.scorer import BlockScore, Scorer, ScoreResult, ScoringError
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Company, Job, JobStatus, MatchResult


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

FULL_MULTIBLOC_RESPONSE = json.dumps({
    "archetype": "automation_engineer",
    "global_score": 85,
    "blocks": {
        "A_role_summary": {
            "score": 4.2,
            "archetype_detected": "automation_engineer",
            "domain": "platform",
            "function": "build",
            "seniority": "senior",
            "work_arrangement": "full_remote",
            "one_liner": "Senior Automation Engineer building internal workflow platform",
        },
        "B_cv_match": {
            "score": 4.5,
            "matched_requirements": [
                {"requirement": "n8n experience", "cv_proof": "Built 50+ n8n workflows", "strength": "exact_match"},
            ],
            "gaps": [
                {"requirement": "Kubernetes", "severity": "nice_to_have", "mitigation": "Docker experience"},
            ],
        },
        "C_level_strategy": {
            "score": 4.0,
            "detected_level": "senior",
            "candidate_level": "senior",
            "positioning_notes": "Direct match on seniority.",
            "downlevel_contingency": None,
        },
        "D_compensation": {
            "score": 3.8,
            "salary_assessment": "Within range",
            "market_context": "Market rate 85-110k EUR",
            "ppp_analysis": "PPP-normalized aligns with FR market",
        },
        "E_personalization": {
            "score": 4.0,
            "cv_changes": [
                {"current": "Generic bullet", "proposed": "Emphasize n8n", "reason": "JD priority"},
            ],
            "cover_letter_hooks": ["Company Series B + automation focus"],
        },
        "F_interview_prep": {
            "score": 4.0,
            "stories": [
                {"requirement": "scaling", "star_prompt": "Tell me about scaling", "suggested_story_id": "story_n8n"},
            ],
            "red_flag_questions": ["Why leaving?"],
        },
    },
    "reasoning": "Strong match on automation skills.",
    "strengths": ["n8n expertise", "Full remote"],
    "concerns": ["Salary lower quartile"],
})

# Response with only 5 blocks (missing F_interview_prep)
MISSING_BLOCK_RESPONSE = json.dumps({
    "archetype": "ai_engineer",
    "global_score": 72,
    "blocks": {
        "A_role_summary": {"score": 3.5, "one_liner": "AI Engineer role"},
        "B_cv_match": {"score": 4.0, "matched_requirements": [], "gaps": []},
        "C_level_strategy": {"score": 3.0, "detected_level": "mid", "candidate_level": "senior",
                             "positioning_notes": "Slight downlevel", "downlevel_contingency": "Negotiate"},
        "D_compensation": {"score": 3.5, "salary_assessment": "OK", "market_context": "N/A", "ppp_analysis": "N/A"},
        "E_personalization": {"score": 3.0, "cv_changes": [], "cover_letter_hooks": []},
        # F_interview_prep is intentionally missing
    },
    "reasoning": "Decent match but missing block.",
    "strengths": ["AI background"],
    "concerns": ["Missing interview prep data"],
})

# Old-style response (backward compat)
OLD_STYLE_RESPONSE = json.dumps({
    "score": 75,
    "reasoning": "Good fit overall.",
    "strengths": ["Python", "n8n"],
    "concerns": ["No K8s"],
})


def make_job(**kwargs: object) -> Job:
    defaults: dict[str, object] = {
        "title": "Automation Engineer",
        "url": "https://example.com/job/multibloc",
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
    client.complete = AsyncMock(return_value=FULL_MULTIBLOC_RESPONSE)
    return client


@pytest.fixture
def scorer(monkeypatch: pytest.MonkeyPatch, mock_llm_client: AsyncMock) -> Scorer:
    monkeypatch.setattr(
        "src.matching.scorer.settings",
        MagicMock(
            min_match_score=80, llm_provider="anthropic", llm_model="claude-opus-4-6",
            llm_scoring_provider="", llm_scoring_model="",
        ),
    )
    return Scorer(client=mock_llm_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMultiBlocScoring:
    @pytest.mark.asyncio
    async def test_score_returns_6_blocks(self, scorer: Scorer) -> None:
        """ScoreResult should contain exactly 6 BlockScore objects for a full response."""
        job = make_job()
        result = await scorer.score(job)
        assert isinstance(result, ScoreResult)
        assert len(result.blocks) == 6
        block_names = {b.name for b in result.blocks}
        assert block_names == {
            "A_role_summary", "B_cv_match", "C_level_strategy",
            "D_compensation", "E_personalization", "F_interview_prep",
        }

    @pytest.mark.asyncio
    async def test_backward_compat_score_0_100(self, scorer: Scorer) -> None:
        """Score should remain a float in [0, 100] range."""
        job = make_job()
        result = await scorer.score(job)
        assert 0.0 <= result.score <= 100.0
        # Deterministic: computed from block scores, not LLM's global_score (85)
        # A=4.2, B=4.5, C=4.0, D=3.8, E=4.0, F=4.0 -> weighted=4.115 -> 77.9
        assert result.score == 77.9

    @pytest.mark.asyncio
    async def test_missing_block_graceful(
        self, scorer: Scorer, mock_llm_client: AsyncMock
    ) -> None:
        """When LLM returns 5/6 blocks, don't crash — just log and return 5 blocks."""
        mock_llm_client.complete = AsyncMock(return_value=MISSING_BLOCK_RESPONSE)
        job = make_job()
        result = await scorer.score(job)
        assert isinstance(result, ScoreResult)
        assert len(result.blocks) == 5
        block_names = {b.name for b in result.blocks}
        assert "F_interview_prep" not in block_names
        # Deterministic: A=3.5, B=4.0, C=3.0, D=3.5, E=3.0, F=3.0(default)
        # weighted=3.375 -> ((3.375-1.0)/4.0)*100 = 59.4
        assert result.score == 59.4

    @pytest.mark.asyncio
    async def test_archetype_detection(self, scorer: Scorer) -> None:
        """Archetype should be extracted from the LLM response."""
        job = make_job()
        result = await scorer.score(job)
        assert result.archetype == "automation_engineer"

    @pytest.mark.asyncio
    async def test_evaluation_json_persisted(self, scorer: Scorer) -> None:
        """evaluation_json and archetype should be stored in DB."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr = await scorer.score_and_persist(job, session)
            assert mr.evaluation_json is not None
            eval_data = json.loads(mr.evaluation_json)
            assert eval_data["archetype"] == "automation_engineer"
            assert eval_data["global_score"] == 77.9  # computed, not LLM's 85
            assert "A_role_summary" in eval_data["blocks"]
            assert mr.archetype == "automation_engineer"

    @pytest.mark.asyncio
    async def test_old_style_response_backward_compat(
        self, scorer: Scorer, mock_llm_client: AsyncMock
    ) -> None:
        """Old-style responses (score/reasoning/strengths/concerns) should still parse."""
        mock_llm_client.complete = AsyncMock(return_value=OLD_STYLE_RESPONSE)
        job = make_job()
        result = await scorer.score(job)
        assert result.score == 75.0
        assert result.reasoning == "Good fit overall."
        assert result.blocks == []
        assert result.archetype == "generic"


class TestBlockScore:
    def test_block_score_fields(self) -> None:
        block = BlockScore(name="A_role_summary", score=4.2, details={"one_liner": "test"})
        assert block.name == "A_role_summary"
        assert block.score == 4.2
        assert block.details["one_liner"] == "test"


class TestScoreResultDefaults:
    def test_score_result_defaults(self) -> None:
        result = ScoreResult(score=80, reasoning="test", strengths=[], concerns=[])
        assert result.archetype == "generic"
        assert result.blocks == []


class TestBuildPromptMultiBloc:
    def test_prompt_includes_archetype_info(self, scorer: Scorer) -> None:
        """Prompt should include archetype proof_priorities when detected."""
        job = make_job(
            title="n8n Automation Engineer",
            description="Build workflow automation with n8n, zapier integration.",
        )
        prompt = scorer._build_prompt(job)
        assert "Archetype Detected" in prompt
        assert "automation" in prompt.lower()

    def test_prompt_description_4000_chars(self, scorer: Scorer) -> None:
        """Description should be truncated at 4000 chars, not 2000."""
        long_desc = "x" * 5000
        job = make_job(description=long_desc)
        prompt = scorer._build_prompt(job)
        # Should contain 4000 x's, not 2000
        assert "x" * 4000 in prompt
        assert "x" * 4001 not in prompt

    def test_prompt_includes_experiences(self, scorer: Scorer) -> None:
        """Prompt should include candidate experiences."""
        job = make_job()
        prompt = scorer._build_prompt(job)
        assert "Key Experiences" in prompt

    def test_prompt_includes_country(self, scorer: Scorer) -> None:
        """Country info still present (backward compat with multicountry tests)."""
        job = make_job()
        job.country_code = "US"  # type: ignore[assignment]
        prompt = scorer._build_prompt(job)
        assert "US" in prompt


class TestParseMultiBlocResponse:
    def test_parse_extracts_blocks(self, scorer: Scorer) -> None:
        result = scorer._parse_response(FULL_MULTIBLOC_RESPONSE)
        assert len(result.blocks) == 6
        a_block = next(b for b in result.blocks if b.name == "A_role_summary")
        assert a_block.score == 4.2
        assert a_block.details["one_liner"] == "Senior Automation Engineer building internal workflow platform"

    def test_parse_global_score_key(self, scorer: Scorer) -> None:
        result = scorer._parse_response(FULL_MULTIBLOC_RESPONSE)
        # Deterministic: computed from blocks, not LLM's global_score
        assert result.score == 77.9

    def test_parse_clamps_score(self, scorer: Scorer) -> None:
        over = json.dumps({
            "global_score": 150,
            "reasoning": "test",
            "strengths": [],
            "concerns": [],
            "blocks": {},
        })
        result = scorer._parse_response(over)
        assert result.score == 100.0

    def test_parse_missing_reasoning_raises(self, scorer: Scorer) -> None:
        bad = json.dumps({"global_score": 50, "strengths": [], "concerns": []})
        with pytest.raises(ScoringError, match="reasoning"):
            scorer._parse_response(bad)

    def test_parse_markdown_fenced_json(self, scorer: Scorer) -> None:
        """LLMs often wrap JSON in ```json ... ``` — parser should handle it."""
        fenced = "```json\n" + FULL_MULTIBLOC_RESPONSE + "\n```"
        result = scorer._parse_response(fenced)
        assert result.score == 77.9
        assert len(result.blocks) == 6
        assert result.archetype == "automation_engineer"

    def test_parse_markdown_fenced_no_lang(self, scorer: Scorer) -> None:
        """Also handle ``` ... ``` without language hint."""
        fenced = "```\n" + FULL_MULTIBLOC_RESPONSE + "\n```"
        result = scorer._parse_response(fenced)
        assert result.score == 77.9

    def test_parse_with_preamble_text(self, scorer: Scorer) -> None:
        """Handle LLM adding text before the JSON (e.g., 'Here is my evaluation:')."""
        with_preamble = "Here is my evaluation:\n\n" + FULL_MULTIBLOC_RESPONSE
        result = scorer._parse_response(with_preamble)
        assert result.score == 77.9
        assert len(result.blocks) == 6

    def test_strip_markdown_fences_static(self) -> None:
        """Unit test the static helper directly."""
        assert Scorer._strip_markdown_fences('```json\n{"a":1}\n```') == '{"a":1}'
        assert Scorer._strip_markdown_fences('```\n{"a":1}\n```') == '{"a":1}'
        assert Scorer._strip_markdown_fences('{"a":1}') == '{"a":1}'
        assert Scorer._strip_markdown_fences('  ```json\n{"a":1}\n```  ') == '{"a":1}'


class TestCompanyIntelligenceInPrompt:
    def test_prompt_includes_company_intelligence_when_researched(self, scorer: Scorer) -> None:
        """When company has researched_at set, prompt should contain Company Intelligence section."""
        company = Company(
            name="Acme Corp",
            funding_stage="Series B",
            tech_stack_signals=json.dumps(["Python", "Kubernetes", "Terraform"]),
            culture_signals=json.dumps(["async-first", "engineering-led"]),
            glassdoor_rating=4.2,
            growth_signals=json.dumps(["50% YoY headcount growth"]),
            red_flags=json.dumps(["high turnover in engineering"]),
            researched_at=datetime(2026, 4, 1),
        )
        job = make_job()
        job.company = company
        prompt = scorer._build_prompt(job)
        assert "## Company Intelligence" in prompt
        assert "Series B" in prompt
        assert "4.2" in prompt
        assert "Python" in prompt
        assert "async-first" in prompt
        assert "50% YoY headcount growth" in prompt
        assert "high turnover in engineering" in prompt

    def test_prompt_no_company_intelligence_when_not_researched(self, scorer: Scorer) -> None:
        """When company has no researched_at, prompt should NOT contain Company Intelligence."""
        company = Company(name="Boring Inc", funding_stage="Seed")
        job = make_job()
        job.company = company
        prompt = scorer._build_prompt(job)
        assert "Company Intelligence" not in prompt

    def test_prompt_no_company_intelligence_when_no_company(self, scorer: Scorer) -> None:
        """When job has no company, prompt should NOT contain Company Intelligence."""
        job = make_job()
        job.company = None
        prompt = scorer._build_prompt(job)
        assert "Company Intelligence" not in prompt


class TestPersistMultiBloc:
    @pytest.mark.asyncio
    async def test_upsert_preserves_evaluation_json(
        self, scorer: Scorer, mock_llm_client: AsyncMock
    ) -> None:
        """Second score_and_persist should update evaluation_json."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            mr1 = await scorer.score_and_persist(job, session)
            first_id = mr1.id
            assert mr1.archetype == "automation_engineer"

            # Re-score with different response
            mock_llm_client.complete = AsyncMock(return_value=MISSING_BLOCK_RESPONSE)
            mr2 = await scorer.score_and_persist(job, session)
            assert mr2.id == first_id
            assert mr2.archetype == "ai_engineer"
            eval_data = json.loads(mr2.evaluation_json)
            assert len(eval_data["blocks"]) == 5
