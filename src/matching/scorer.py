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
