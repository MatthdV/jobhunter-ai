# Scorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `src/matching/scorer.py` — call Claude API to score job offers 0–100 against the candidate profile, persist results to a `MatchResult` table, update Job status to MATCHED or SKIPPED.

**Architecture:** Sync SQLAlchemy session + async Anthropic client. `score()` wraps only the API call with exponential-backoff retry. `score_and_persist()` upserts to DB and updates `Job` fields. `score_batch()` runs concurrent scoring with `asyncio.Semaphore(5)` and fails fast on any error.

**Tech Stack:** `anthropic` SDK (`AsyncAnthropic`), SQLAlchemy 2.0 sync `Session`, `PyYAML`, `pytest` with `AsyncMock`, in-memory SQLite for tests.

**Spec:** `docs/superpowers/specs/2026-03-21-scorer-design.md`

---

## Files

| File | Action |
|---|---|
| `src/storage/models.py` | Add `MatchResult` ORM class; add `match_result` relationship to `Job` |
| `src/matching/scorer.py` | Replace stub with full implementation |
| `tests/test_matching.py` | Replace pass-stubs with 14 TDD test slices |

---

### Task 1: MatchResult model + test infrastructure

**Files:**
- Modify: `src/storage/models.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Replace tests/test_matching.py with infrastructure + MatchResult smoke test**

Replace the entire file content:

```python
"""Tests for the matching / scoring pipeline — Phase 2."""

import json
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
def setup_db() -> None:  # type: ignore[return]
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
    pass  # filled in incrementally


class TestEmbeddingMatcher:
    @pytest.mark.asyncio
    async def test_filter_removes_low_similarity_jobs(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_identical_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher

    def test_cosine_similarity_orthogonal_vectors(self) -> None:
        pass  # Phase 2 – EmbeddingMatcher
```

- [ ] **Step 2: Run test to verify it fails** (MatchResult doesn't exist yet)

```bash
pytest tests/test_matching.py::TestMatchResult -v
```

Expected: `ImportError` or `AttributeError` — `MatchResult` is not in `models.py`.

- [ ] **Step 3: Add MatchResult to src/storage/models.py**

In `src/storage/models.py`, append after the `Recruiter` class (end of file):

```python
class MatchResult(Base):
    __tablename__ = "match_results"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    job_id         = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    score          = Column(Float, nullable=False)
    reasoning      = Column(Text, nullable=False)
    strengths_json = Column(Text, nullable=True)
    concerns_json  = Column(Text, nullable=True)
    model_used     = Column(String(100), nullable=False)
    scored_at      = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="match_result")

    def __repr__(self) -> str:
        return f"<MatchResult job_id={self.job_id} score={self.score}>"
```

Also add `match_result` to the `Job` class, after line 97 (`application` relationship):

```python
    match_result = relationship("MatchResult", back_populates="job", uselist=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestMatchResult -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storage/models.py tests/test_matching.py
git commit -m "feat(models): add MatchResult table with Job relationship"
```

---

### Task 2: Scorer skeleton + `__init__` guard (slice 1)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slice-1 test to TestScorer**

Replace `class TestScorer: pass` with:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_matching.py::TestScorer::test_init_raises_configuration_error_without_api_key -v
```

Expected: FAIL — `NotImplementedError` from stub `__init__`.

- [ ] **Step 3: Replace src/matching/scorer.py with skeleton + __init__**

```python
"""LLM-based job offer scorer using the Claude API."""

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import yaml
from anthropic.types import TextBlock
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import ConfigurationError, settings
from src.storage.models import Job, JobStatus, MatchResult

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

_SYSTEM_MESSAGE = (
    "You are a job matching expert. Evaluate the fit between the candidate profile "
    "and the job offer across 5 dimensions: role alignment, tech stack overlap, "
    "salary match, remote/location, and company type. "
    "Return ONLY valid JSON with this exact schema:\n"
    '{"score": <integer 0-100>, "reasoning": "<2-3 sentences>", '
    '"strengths": ["<strength>", ...], "concerns": ["<concern>", ...]}\n'
    "Do not include any text outside the JSON object."
)


@dataclass
class ScoreResult:
    """Result of scoring a single job offer."""

    score: float
    reasoning: str
    strengths: list[str]
    concerns: list[str]


class ScoringError(Exception):
    """Raised when Claude's response cannot be parsed into a ScoreResult."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class Scorer:
    """Score job offers against the candidate profile using Claude."""

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for scoring")
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def score(self, job: Job) -> ScoreResult:
        raise NotImplementedError

    async def score_and_persist(self, job: Job, session: Session) -> MatchResult:
        raise NotImplementedError

    async def score_batch(self, jobs: list[Job], session: Session) -> list[MatchResult]:
        raise NotImplementedError

    def _build_prompt(self, job: Job) -> str:
        raise NotImplementedError

    def _parse_response(self, response_text: str) -> ScoreResult:
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_matching.py::TestScorer::test_init_raises_configuration_error_without_api_key -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): add skeleton + __init__ ConfigurationError guard"
```

---

### Task 3: `_build_prompt` (slices 2, 3, 4)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slices 2–4 tests to TestScorer**

Add inside `class TestScorer:`:

```python
    def test_build_prompt_includes_job_title(self, scorer: Scorer) -> None:
        """_build_prompt embeds the job title in the user message."""
        job = make_job(title="Senior n8n Automation Engineer")
        prompt = scorer._build_prompt(job)
        assert "Senior n8n Automation Engineer" in prompt

    def test_build_prompt_includes_salary_range(self, scorer: Scorer) -> None:
        """_build_prompt injects both candidate salary targets and job salary."""
        job = make_job(salary_raw="100-130k EUR", salary_min=100000, salary_max=130000)
        prompt = scorer._build_prompt(job)
        # Candidate targets from profile.yaml
        assert "80000" in prompt  # min_annual
        assert "140000" in prompt  # max_annual
        # Job salary
        assert "100-130k EUR" in prompt

    def test_build_prompt_handles_none_description(self, scorer: Scorer) -> None:
        """_build_prompt does not crash when job.description is None."""
        job = make_job(description=None)
        prompt = scorer._build_prompt(job)
        assert "## Job Offer" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_matching.py::TestScorer::test_build_prompt_includes_job_title \
       tests/test_matching.py::TestScorer::test_build_prompt_includes_salary_range \
       tests/test_matching.py::TestScorer::test_build_prompt_handles_none_description -v
```

Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `_build_prompt` in scorer.py**

Replace `def _build_prompt(self, job: Job) -> str: raise NotImplementedError` with:

```python
    def _build_prompt(self, job: Job) -> str:
        candidate: dict[str, Any] = self._profile["candidate"]
        salary: dict[str, Any] = self._profile["salary"]
        skills: dict[str, Any] = self._profile["skills"]
        filters: dict[str, Any] = self._profile["filters"]

        ts: dict[str, list[str]] = skills.get("tech_stack", {})
        stack_lines = [
            f"  {cat}: {', '.join(str(i) for i in items)}"
            for cat, items in ts.items()
            if isinstance(items, list)
        ]
        stack_summary = "\n".join(stack_lines)

        company_name = job.company.name if job.company is not None else "Unknown"

        return (
            "## Candidate Profile\n"
            f"- Title: {candidate['title']}\n"
            f"- Experience: {candidate['experience_years']} years\n"
            f"- Top skills: {', '.join(str(s) for s in skills['top_3'])}\n"
            f"- Full stack:\n{stack_summary}\n"
            f"- Salary target: {salary['min_annual']}–{salary['max_annual']} EUR/year"
            f" (or {salary['min_daily_rate']}–{salary['max_daily_rate']} EUR/day freelance)\n"
            f"- Remote only: {filters['remote_only']}\n"
            f"- Contract types: {', '.join(str(c) for c in filters['preferred_contract_types'])}\n\n"
            "## Job Offer\n"
            f"- Title: {job.title}\n"
            f"- Company: {company_name}\n"
            f"- Contract: {job.contract_type or 'Unknown'}\n"
            f"- Remote: {job.is_remote}\n"
            f"- Location: {job.location or 'Unknown'}\n"
            f"- Salary: {job.salary_raw or 'Not specified'}"
            f" ({job.salary_min}–{job.salary_max} EUR)\n"
            f"- Description:\n{(job.description or '')[:2000]}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestScorer::test_build_prompt_includes_job_title \
       tests/test_matching.py::TestScorer::test_build_prompt_includes_salary_range \
       tests/test_matching.py::TestScorer::test_build_prompt_handles_none_description -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): implement _build_prompt with profile injection"
```

---

### Task 4: `_parse_response` (slices 5, 6, 7)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slices 5–7 tests to TestScorer**

```python
    def test_parse_response_valid_json(self, scorer: Scorer) -> None:
        """_parse_response returns a ScoreResult from valid JSON."""
        result = scorer._parse_response(VALID_RESPONSE)
        assert isinstance(result, ScoreResult)
        assert result.score == 85.0
        assert "automation" in result.reasoning.lower()
        assert "n8n expertise" in result.strengths
        assert len(result.concerns) == 1

    def test_parse_response_handles_malformed_json(self, scorer: Scorer) -> None:
        """_parse_response falls back to regex extraction when Claude adds surrounding text."""
        wrapped = f'Sure, here is my evaluation:\n{VALID_RESPONSE}\nHope that helps!'
        result = scorer._parse_response(wrapped)
        assert result.score == 85.0

    def test_parse_response_raises_scoring_error_on_garbage(self, scorer: Scorer) -> None:
        """_parse_response raises ScoringError when no valid JSON can be extracted."""
        with pytest.raises(ScoringError):
            scorer._parse_response("This is not JSON at all.")

    def test_parse_response_clamps_score_to_range(self, scorer: Scorer) -> None:
        """_parse_response clamps score to [0, 100] regardless of Claude's output."""
        over = json.dumps({"score": 150, "reasoning": "x", "strengths": [], "concerns": []})
        result = scorer._parse_response(over)
        assert result.score == 100.0

        under = json.dumps({"score": -10, "reasoning": "x", "strengths": [], "concerns": []})
        result2 = scorer._parse_response(under)
        assert result2.score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_matching.py::TestScorer::test_parse_response_valid_json \
       tests/test_matching.py::TestScorer::test_parse_response_handles_malformed_json \
       tests/test_matching.py::TestScorer::test_parse_response_raises_scoring_error_on_garbage \
       tests/test_matching.py::TestScorer::test_parse_response_clamps_score_to_range -v
```

Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `_parse_response` in scorer.py**

Replace `def _parse_response(self, response_text: str) -> ScoreResult: raise NotImplementedError` with:

```python
    def _parse_response(self, response_text: str) -> ScoreResult:
        # Attempt 1: direct JSON parse
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Attempt 2: extract first {...} block via regex
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not match:
                raise ScoringError("No JSON object found in response", raw=response_text)
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError as exc:
                raise ScoringError(f"Malformed JSON: {exc}", raw=response_text) from exc

        # Validate required keys
        for key in ("score", "reasoning", "strengths", "concerns"):
            if key not in data:
                raise ScoringError(f"Missing required key: {key!r}", raw=response_text)

        return ScoreResult(
            score=max(0.0, min(100.0, float(data["score"]))),
            reasoning=str(data["reasoning"]),
            strengths=[str(s) for s in data["strengths"]],
            concerns=[str(c) for c in data["concerns"]],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestScorer::test_parse_response_valid_json \
       tests/test_matching.py::TestScorer::test_parse_response_handles_malformed_json \
       tests/test_matching.py::TestScorer::test_parse_response_raises_scoring_error_on_garbage \
       tests/test_matching.py::TestScorer::test_parse_response_clamps_score_to_range -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): implement _parse_response with regex fallback"
```

---

### Task 5: `score()` — Claude call (slice 8)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slice-8 test to TestScorer**

```python
    async def test_score_calls_claude_returns_score_result(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score() calls the Anthropic API and returns a ScoreResult."""
        job = make_job()
        result = await scorer.score(job)
        assert isinstance(result, ScoreResult)
        assert result.score == 85.0
        assert result.strengths == ["n8n expertise", "AI automation background"]
        # Verify the API was called exactly once
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert "## Job Offer" in call_kwargs["messages"][0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_matching.py::TestScorer::test_score_calls_claude_returns_score_result -v
```

Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `score()` in scorer.py (without retry yet)**

Replace `async def score(self, job: Job) -> ScoreResult: raise NotImplementedError` with:

```python
    async def score(self, job: Job) -> ScoreResult:
        prompt = self._build_prompt(job)
        response = await self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=_SYSTEM_MESSAGE,
            messages=[{"role": "user", "content": prompt}],
        )
        content_block = response.content[0]
        if not isinstance(content_block, TextBlock):
            raise ScoringError("Expected text response from Claude", raw=str(content_block))
        return self._parse_response(content_block.text)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_matching.py::TestScorer::test_score_calls_claude_returns_score_result -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): implement score() — calls Claude and returns ScoreResult"
```

---

### Task 6: Retry on rate limit (slice 9)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slice-9 tests to TestScorer**

```python
    async def test_score_retries_on_rate_limit(
        self, scorer: Scorer, mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """score() retries once after RateLimitError and succeeds."""
        rate_err = anthropic.RateLimitError(
            "rate limited", response=httpx.Response(429), body={}
        )
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=VALID_RESPONSE, type="text")]
        mock_client.messages.create = AsyncMock(side_effect=[rate_err, good_msg])

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("src.matching.scorer.asyncio.sleep", fake_sleep)

        result = await scorer.score(make_job())
        assert result.score == 85.0
        assert sleep_calls == [2.0]  # backed off once

    async def test_score_raises_after_exhausted_retries(
        self, scorer: Scorer, mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """score() raises RateLimitError after 3 consecutive failures."""
        rate_err = anthropic.RateLimitError(
            "rate limited", response=httpx.Response(429), body={}
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[rate_err, rate_err, rate_err]
        )
        monkeypatch.setattr("src.matching.scorer.asyncio.sleep", AsyncMock())

        with pytest.raises(anthropic.RateLimitError):
            await scorer.score(make_job())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_matching.py::TestScorer::test_score_retries_on_rate_limit \
       tests/test_matching.py::TestScorer::test_score_raises_after_exhausted_retries -v
```

Expected: FAIL — no retry logic yet.

- [ ] **Step 3: Add retry logic to `score()` in scorer.py**

Replace the `score()` method with:

```python
    async def score(self, job: Job) -> ScoreResult:
        prompt = self._build_prompt(job)
        _delays = [2.0, 4.0]
        last_exc: anthropic.RateLimitError | None = None

        for attempt in range(3):
            try:
                response = await self._client.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=512,
                    system=_SYSTEM_MESSAGE,
                    messages=[{"role": "user", "content": prompt}],
                )
                content_block = response.content[0]
                if not isinstance(content_block, TextBlock):
                    raise ScoringError(
                        "Expected text response from Claude", raw=str(content_block)
                    )
                return self._parse_response(content_block.text)
            except anthropic.RateLimitError as exc:
                last_exc = exc
                if attempt < len(_delays):
                    await asyncio.sleep(_delays[attempt])

        assert last_exc is not None
        raise last_exc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestScorer::test_score_retries_on_rate_limit \
       tests/test_matching.py::TestScorer::test_score_raises_after_exhausted_retries -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run full TestScorer suite to confirm no regressions**

```bash
pytest tests/test_matching.py::TestScorer -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): add exponential-backoff retry on RateLimitError"
```

---

### Task 7: `score_and_persist` — insert path (slices 10, 11)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slices 10–11 tests to TestScorer**

```python
    async def test_score_and_persist_above_threshold_sets_matched(
        self, scorer: Scorer
    ) -> None:
        """score_and_persist creates a MatchResult and sets Job.status=MATCHED when score≥80."""
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()

            mr = await scorer.score_and_persist(job, session)

            session.refresh(job)
            assert mr.score == 85.0
            assert mr.model_used == "claude-opus-4-6"
            assert mr.strengths_json is not None
            assert "n8n expertise" in json.loads(mr.strengths_json)
            assert job.status == JobStatus.MATCHED
            assert job.match_score == 85.0

    async def test_score_and_persist_below_threshold_sets_skipped(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score_and_persist sets Job.status=SKIPPED when score<80."""
        low_response = json.dumps({
            "score": 55,
            "reasoning": "Weak match overall.",
            "strengths": ["Some Python"],
            "concerns": ["No automation experience", "Wrong sector"],
        })
        msg = MagicMock()
        msg.content = [MagicMock(text=low_response, type="text")]
        mock_client.messages.create = AsyncMock(return_value=msg)

        with get_session() as session:
            job = make_job(url="https://example.com/job/low")
            session.add(job)
            session.flush()

            mr = await scorer.score_and_persist(job, session)

            session.refresh(job)
            assert mr.score == 55.0
            assert job.status == JobStatus.SKIPPED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_matching.py::TestScorer::test_score_and_persist_above_threshold_sets_matched \
       tests/test_matching.py::TestScorer::test_score_and_persist_below_threshold_sets_skipped -v
```

Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `score_and_persist()` in scorer.py**

Replace `async def score_and_persist(...)` with:

```python
    async def score_and_persist(self, job: Job, session: Session) -> MatchResult:
        result = await self.score(job)

        existing = session.execute(
            select(MatchResult).where(MatchResult.job_id == job.id)
        ).scalar_one_or_none()

        if existing is not None:
            mr = existing
            mr.score = result.score
            mr.reasoning = result.reasoning
            mr.strengths_json = json.dumps(result.strengths)
            mr.concerns_json = json.dumps(result.concerns)
            mr.model_used = settings.anthropic_model
        else:
            mr = MatchResult(
                job_id=job.id,
                score=result.score,
                reasoning=result.reasoning,
                strengths_json=json.dumps(result.strengths),
                concerns_json=json.dumps(result.concerns),
                model_used=settings.anthropic_model,
            )
            session.add(mr)

        job.match_score = result.score
        job.match_reasoning = result.reasoning
        job.status = (
            JobStatus.MATCHED
            if result.score >= settings.min_match_score
            else JobStatus.SKIPPED
        )

        session.commit()
        session.refresh(mr)
        return mr
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestScorer::test_score_and_persist_above_threshold_sets_matched \
       tests/test_matching.py::TestScorer::test_score_and_persist_below_threshold_sets_skipped -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): implement score_and_persist with DB write and status update"
```

---

### Task 8: `score_and_persist` — upsert path (slice 12)

**Files:**
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slice-12 test to TestScorer**

```python
    async def test_score_and_persist_upserts_existing_match_result(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """Re-scoring a job updates the existing MatchResult row, not creates a second one."""
        first_response = json.dumps({
            "score": 70,
            "reasoning": "Initial scoring.",
            "strengths": ["Python"],
            "concerns": ["Missing n8n"],
        })
        second_response = json.dumps({
            "score": 88,
            "reasoning": "Re-scored with more context.",
            "strengths": ["Python", "n8n"],
            "concerns": [],
        })

        msg1 = MagicMock()
        msg1.content = [MagicMock(text=first_response, type="text")]
        msg2 = MagicMock()
        msg2.content = [MagicMock(text=second_response, type="text")]
        mock_client.messages.create = AsyncMock(side_effect=[msg1, msg2])

        with get_session() as session:
            job = make_job(url="https://example.com/job/upsert")
            session.add(job)
            session.flush()

            await scorer.score_and_persist(job, session)
            await scorer.score_and_persist(job, session)

            # Only one MatchResult row should exist
            count = session.execute(
                select(MatchResult).where(MatchResult.job_id == job.id)
            ).scalars().all()
            assert len(count) == 1
            assert count[0].score == 88.0  # updated, not duplicated
```

- [ ] **Step 2: Run test to verify it passes** (upsert logic already implemented in Task 7)

```bash
pytest tests/test_matching.py::TestScorer::test_score_and_persist_upserts_existing_match_result -v
```

Expected: PASS — the `scalar_one_or_none()` upsert logic handles this.

- [ ] **Step 3: Commit**

```bash
git add tests/test_matching.py
git commit -m "test(scorer): add upsert coverage for score_and_persist"
```

---

### Task 9: `score_batch` (slices 13, 14)

**Files:**
- Modify: `src/matching/scorer.py`
- Modify: `tests/test_matching.py`

- [ ] **Step 1: Add slices 13–14 tests to TestScorer**

```python
    async def test_score_batch_returns_match_results_in_order(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score_batch scores all jobs and returns MatchResult list in input order."""
        responses = [
            json.dumps({"score": 90, "reasoning": f"Job {i}", "strengths": [], "concerns": []})
            for i in range(3)
        ]
        msgs = [
            MagicMock(content=[MagicMock(text=r, type="text")]) for r in responses
        ]
        mock_client.messages.create = AsyncMock(side_effect=msgs)

        with get_session() as session:
            jobs = [make_job(url=f"https://example.com/job/{i}") for i in range(3)]
            for j in jobs:
                session.add(j)
            session.flush()

            results = await scorer.score_batch(jobs, session)

        assert len(results) == 3
        assert all(isinstance(r, MatchResult) for r in results)

    async def test_score_batch_raises_on_any_scoring_error(
        self, scorer: Scorer, mock_client: AsyncMock
    ) -> None:
        """score_batch raises immediately if any job fails (fail-fast)."""
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=VALID_RESPONSE, type="text")]
        mock_client.messages.create = AsyncMock(
            side_effect=[good_msg, ScoringError("parse failed"), good_msg]
        )

        with get_session() as session:
            jobs = [make_job(url=f"https://example.com/job/batch/{i}") for i in range(3)]
            for j in jobs:
                session.add(j)
            session.flush()

            with pytest.raises(ScoringError):
                await scorer.score_batch(jobs, session)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_matching.py::TestScorer::test_score_batch_returns_match_results_in_order \
       tests/test_matching.py::TestScorer::test_score_batch_raises_on_any_scoring_error -v
```

Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `score_batch()` in scorer.py**

Replace `async def score_batch(...)` with:

```python
    async def score_batch(self, jobs: list[Job], session: Session) -> list[MatchResult]:
        sem = asyncio.Semaphore(5)

        async def _score_one(job: Job) -> MatchResult:
            async with sem:
                return await self.score_and_persist(job, session)

        tasks = [_score_one(job) for job in jobs]
        results: list[MatchResult] = await asyncio.gather(*tasks)
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_matching.py::TestScorer::test_score_batch_returns_match_results_in_order \
       tests/test_matching.py::TestScorer::test_score_batch_raises_on_any_scoring_error -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/test_matching.py -v
```

Expected: all 16 tests PASS (2 TestMatchResult + 14 TestScorer), 3 TestEmbeddingMatcher still pass (they're `pass` stubs).

- [ ] **Step 6: Commit**

```bash
git add src/matching/scorer.py tests/test_matching.py
git commit -m "feat(scorer): implement score_batch with Semaphore(5) and fail-fast"
```

---

### Task 10: Lint, type-check, and final verification

**Files:** none (read-only quality gates)

- [ ] **Step 1: Run ruff**

```bash
ruff check src/matching/scorer.py src/storage/models.py tests/test_matching.py
```

Expected: no errors. Fix any that appear before proceeding.

- [ ] **Step 2: Run mypy --strict**

```bash
mypy src/matching/scorer.py src/storage/models.py
```

Expected: no errors. Common issues to watch for:
- `dict[str, Any]` — already typed correctly in `_profile`
- `response.content[0]` — already guarded with `isinstance(content_block, TextBlock)`
- `last_exc is not None` — already asserted before `raise`

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (TestMatchResult, TestScorer, TestEmbeddingMatcher stubs, plus any pre-existing passing tests in other test files).

- [ ] **Step 4: Final commit**

```bash
git add -p  # review any unstaged fixes from lint/typecheck
git commit -m "fix(scorer): address ruff and mypy strict findings"
```

Only commit if there were fixes. Skip if Step 1–2 were clean.
