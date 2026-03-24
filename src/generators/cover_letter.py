"""Cover letter generation using an LLM — human tone, no buzzwords."""

import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml

from src.config.settings import settings
from src.llm.base import LLMClient
from src.llm.factory import get_client
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
_ENGLISH_THRESHOLD: float = 0.25


class CoverLetterGenerator:
    """Generate a personalised cover letter for a specific job offer."""

    def __init__(self, client: LLMClient | None = None) -> None:
        if client is None:
            client = get_client(settings.llm_provider)
        self._client = client
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)

    async def generate(self, job: Job) -> str:
        """Generate a cover letter text for the given job."""
        return await self._client.complete(
            prompt=self._build_prompt(job),
            max_tokens=_CL_MAX_TOKENS,
        )

    async def refine(self, application: Application, feedback: str) -> str:
        """Refine an existing cover letter based on human feedback."""
        if application.cover_letter is None:
            raise ValueError("application.cover_letter is None — generate a letter first")

        prompt = (
            f"{self._build_prompt(application.job)}\n\n"
            "---\n"
            "EXISTING LETTER:\n"
            f"{application.cover_letter}\n\n"
            "---\n"
            "FEEDBACK:\n"
            f"{feedback}\n\n"
            "---\n"
            "Revise the letter above according to the feedback. "
            "Keep the same language, length, and tone constraints."
        )
        return await self._client.complete(
            prompt=prompt,
            max_tokens=_CL_MAX_TOKENS,
        )

    def _build_prompt(self, job: Job) -> str:
        lang = self._detect_language(job)
        lang_str = "French" if lang == "fr" else "English"

        candidate = self._profile.get("candidate", {})
        experiences = self._profile.get("experiences", [])[:3]
        skills_top: list[str] = self._profile.get("skills", {}).get("top_3", [])

        exp_lines = ""
        for exp in experiences:
            bullets = exp.get("bullets", [])[:2]
            bullet_text = "\n".join(f"  - {b}" for b in bullets)
            exp_lines += f"- {exp['title']} @ {exp['company']}\n{bullet_text}\n"

        company_name = job.company.name if job.company else "unknown"
        description = (job.description or "")[:1500]
        forbidden = ", ".join(sorted(_FORBIDDEN_WORDS))

        return (
            f"## Candidate: {candidate.get('name', '')} — {candidate.get('title', '')}\n"
            f"Top skills: {', '.join(skills_top)}\n\n"
            "## Relevant experiences:\n"
            f"{exp_lines}\n"
            f"## Job: {job.title} at {company_name}\n"
            f"{description}\n\n"
            "---\n"
            f"Write entirely in {lang_str}.\n"
            "Open with a concrete hook tied to the company's product or challenge"
            " — no generic opener.\n"
            "Highlight 2–3 experiences with measurable outcomes.\n"
            "End with a direct call-to-action. No hollow enthusiasm.\n"
            f"Never use the following words: {forbidden}.\n"
            "Target length: 300–400 words."
        )

    def _detect_language(self, job: Job) -> Literal["fr", "en"]:
        description = job.description or ""
        if not description.strip():
            return "fr"
        tokens = [re.sub(r"[^a-z]", "", t) for t in description.lower().split()]
        tokens = [t for t in tokens if t]
        if not tokens:
            return "fr"
        en_count = sum(1 for t in tokens if t in _ENGLISH_FUNCTION_WORDS)
        return "en" if (en_count / len(tokens)) > _ENGLISH_THRESHOLD else "fr"
