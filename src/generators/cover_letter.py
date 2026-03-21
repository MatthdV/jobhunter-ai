"""Cover letter generation using Claude — human tone, no buzzwords."""

import logging
import re
from pathlib import Path
from typing import Any, Literal

import anthropic
import yaml

from src.config.settings import ConfigurationError, settings
from src.storage.models import Application, Job

logger = logging.getLogger(__name__)

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

_CL_MAX_TOKENS = 1024

_FORBIDDEN_WORDS: frozenset[str] = frozenset([
    "holistique", "synergique", "écosystème", "paradigme",
    "booster", "disruptif", "levier",
])

_ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset([
    "the", "and", "for", "with", "you", "our", "are", "this", "that", "will",
    "have", "from", "they", "your", "been", "has", "its", "can", "we", "their",
    "an", "be", "at", "by", "as", "is", "it", "in", "of", "to", "a",
    "who", "what", "which", "but", "not", "or", "if", "on", "so", "all",
    "more", "also", "when", "than", "then", "into", "about", "up", "out",
])
_ENGLISH_THRESHOLD: float = 0.25  # validated: FR max 0.23, EN min 0.36


class CoverLetterGenerator:
    """Generate a personalised cover letter for a specific job offer."""

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for cover letter generation")
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(self, job: Job) -> str:
        raise NotImplementedError

    async def refine(self, application: Application, feedback: str) -> str:
        raise NotImplementedError

    def _build_prompt(self, job: Job) -> str:
        raise NotImplementedError

    def _detect_language(self, job: Job) -> Literal["fr", "en"]:
        """Detect whether the job posting is in French or English."""
        description = job.description or ""
        if not description.strip():
            return "fr"
        tokens = [re.sub(r"[^a-z]", "", t) for t in description.lower().split()]
        tokens = [t for t in tokens if t]
        if not tokens:
            return "fr"
        en_count = sum(1 for t in tokens if t in _ENGLISH_FUNCTION_WORDS)
        return "en" if (en_count / len(tokens)) > _ENGLISH_THRESHOLD else "fr"
