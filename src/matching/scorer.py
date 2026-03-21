"""LLM-based job offer scorer using the Claude API."""

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import yaml
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
        delays = [0, 2, 4]
        last_error: anthropic.RateLimitError | None = None
        for delay in delays:
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._client.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=512,
                    system=_SYSTEM_MESSAGE,
                    messages=[{"role": "user", "content": self._build_prompt(job)}],
                )
                text = next(
                    block.text for block in response.content
                    if hasattr(block, "text")
                )
                return self._parse_response(text)
            except anthropic.RateLimitError as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]

    async def score_and_persist(self, job: Job, session: Session) -> MatchResult:
        result = await self.score(job)

        existing = session.execute(
            select(MatchResult).where(MatchResult.job_id == job.id)
        ).scalar_one_or_none()

        if existing:
            existing.score = result.score  # type: ignore[assignment]
            existing.reasoning = result.reasoning  # type: ignore[assignment]
            existing.strengths_json = json.dumps(result.strengths)  # type: ignore[assignment]
            existing.concerns_json = json.dumps(result.concerns)  # type: ignore[assignment]
            existing.model_used = settings.anthropic_model  # type: ignore[assignment]
            match_result = existing
        else:
            match_result = MatchResult(
                job_id=job.id,
                score=result.score,
                reasoning=result.reasoning,
                strengths_json=json.dumps(result.strengths),
                concerns_json=json.dumps(result.concerns),
                model_used=settings.anthropic_model,
            )
            session.add(match_result)

        job.match_score = result.score  # type: ignore[assignment]
        job.match_reasoning = result.reasoning  # type: ignore[assignment]
        threshold = settings.min_match_score
        job.status = (
            JobStatus.MATCHED if result.score >= threshold else JobStatus.SKIPPED  # type: ignore[assignment]
        )

        session.commit()
        return match_result

    async def score_batch(self, jobs: list[Job], session: Session) -> list[MatchResult]:
        semaphore = asyncio.Semaphore(5)

        async def _score_one(job: Job) -> MatchResult:
            async with semaphore:
                return await self.score_and_persist(job, session)

        tasks = [_score_one(job) for job in jobs]
        return await asyncio.gather(*tasks)

    def _build_prompt(self, job: Job) -> str:
        p = self._profile
        candidate = p.get("candidate", {})
        skills = p.get("skills", {})
        salary = p.get("salary", {})
        filters = p.get("filters", {})

        top_skills = skills.get("top", [])[:3]
        tech_stack = skills.get("tech_stack", [])

        return (
            "## Candidate Profile\n"
            f"- Title: {candidate.get('title', 'Unknown')}\n"
            f"- Experience: {candidate.get('experience_years', 'Unknown')} years\n"
            f"- Top skills: {', '.join(top_skills)}\n"
            f"- Full stack: {', '.join(tech_stack)}\n"
            f"- Salary target: {salary.get('min_annual', '')}–{salary.get('max_annual', '')} EUR/year"  # noqa: E501
            f" (or {salary.get('min_daily_rate', '')}–{salary.get('max_daily_rate', '')} EUR/day freelance)\n"  # noqa: E501
            f"- Remote only: {filters.get('remote_only', False)}\n"
            f"- Contract types: {', '.join(filters.get('preferred_contract_types', []))}\n"
            "\n"
            "## Job Offer\n"
            f"- Title: {job.title}\n"
            f"- Company: {job.company.name if job.company else 'Unknown'}\n"
            f"- Contract: {job.contract_type or 'Unknown'}\n"
            f"- Remote: {job.is_remote}\n"
            f"- Location: {job.location or 'Unknown'}\n"
            f"- Salary: {job.salary_raw or 'Not specified'} ({job.salary_min}–{job.salary_max} EUR)\n"  # noqa: E501
            f"- Description:\n{(job.description or '')[:2000]}"
        )

    def _parse_response(self, response_text: str) -> ScoreResult:
        data: dict[str, Any] | None = None
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(match.group())

        if data is None:
            raise ScoringError("Could not parse JSON from response", raw=response_text)

        for key in ("score", "reasoning", "strengths", "concerns"):
            if key not in data:
                raise ScoringError(f"Missing required key: {key}", raw=response_text)

        return ScoreResult(
            score=max(0.0, min(100.0, float(data["score"]))),
            reasoning=data["reasoning"],
            strengths=list(data["strengths"]),
            concerns=list(data["concerns"]),
        )
