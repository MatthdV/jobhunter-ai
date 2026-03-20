"""LLM-based job offer scorer using the Claude API."""

from dataclasses import dataclass

from src.storage.models import Job


@dataclass
class ScoreResult:
    """Result of scoring a single job offer."""

    score: float          # 0–100
    reasoning: str        # Claude's explanation
    strengths: list[str]  # Why this is a good match
    concerns: list[str]   # Potential issues or gaps


class Scorer:
    """Score job offers against the candidate profile using Claude.

    Loads the candidate profile from src/config/profile.yaml and builds
    a structured prompt that asks Claude to evaluate fit on:
    - Role alignment (title, responsibilities)
    - Tech stack overlap
    - Salary match
    - Remote / location
    - Company type (fintech, saas, consulting)

    Usage::

        scorer = Scorer()
        result = await scorer.score(job)
        if result.score >= settings.min_match_score:
            job.status = JobStatus.MATCHED
    """

    def __init__(self) -> None:
        """Load profile.yaml and initialise Anthropic client."""
        raise NotImplementedError

    async def score(self, job: Job) -> ScoreResult:
        """Send job description to Claude and return a ScoreResult.

        Args:
            job: Job ORM instance with populated title, description, salary_raw.

        Returns:
            ScoreResult with score (0–100) and structured reasoning.
        """
        raise NotImplementedError

    async def score_batch(self, jobs: list[Job]) -> list[ScoreResult]:
        """Score multiple jobs, respecting Claude API rate limits.

        Args:
            jobs: List of Job instances to score.

        Returns:
            List of ScoreResult in the same order as input.
        """
        raise NotImplementedError

    def _build_prompt(self, job: Job) -> str:
        """Build the scoring prompt from job data and candidate profile."""
        raise NotImplementedError

    def _parse_response(self, response_text: str) -> ScoreResult:
        """Parse Claude's JSON response into a ScoreResult."""
        raise NotImplementedError
