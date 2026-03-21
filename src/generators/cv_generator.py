"""Personalised CV generation per job offer using Jinja2 + WeasyPrint."""

import contextlib
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
import yaml
from jinja2 import Environment, FileSystemLoader

from src.config.settings import ConfigurationError, settings
from src.storage.models import Job

logger = logging.getLogger(__name__)

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

_CV_SYSTEM_MESSAGE = (
    "You are a CV personalisation assistant. Given a candidate profile and a job offer, "
    "identify which experiences and skills to highlight. "
    "Return ONLY valid JSON with this exact schema:\n"
    '{"experience_ids": ["<id>", ...], "skill_ids": ["<value>", ...], "hook": "<one sentence>"}\n'
    "experience_ids must be a subset of the IDs present in the profile. "
    "skill_ids must be string values from the candidate's skills list. "
    "Do not include any text outside the JSON object."
)
_CV_MAX_TOKENS = 256


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]


class CVGenerator:
    """Generate a tailored PDF CV for a specific job offer."""

    TEMPLATE_DIR = Path(__file__).parent / "templates"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for CV generation")
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATE_DIR)),
            autoescape=False,
        )

    async def generate(self, job: Job, output_dir: Path) -> Path:
        raise NotImplementedError

    async def _select_highlights(self, job: Job) -> dict[str, Any]:
        raise NotImplementedError

    def _render_html(self, context: dict[str, Any]) -> str:
        raise NotImplementedError

    def _html_to_pdf(self, html: str, output_path: Path) -> Path:
        raise NotImplementedError
