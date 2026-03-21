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
        """Generate a personalised CV PDF for the given job."""
        try:
            highlights = await self._select_highlights(job)
        except Exception:
            logger.warning("_select_highlights failed — using fallback (natural order)")
            highlights = {
                "experience_ids": [e["id"] for e in self._profile.get("experiences", [])],
                "skill_ids": [],
                "hook": "",
            }

        exp_ids: list[str] = highlights["experience_ids"][:4]
        exp_by_id = {e["id"]: e for e in self._profile.get("experiences", [])}
        experiences = [exp_by_id[eid] for eid in exp_ids if eid in exp_by_id]

        skills = self._profile.get("skills", {})
        skills_all: list[str] = skills.get("top_3", []) + skills.get("additional", [])

        context: dict[str, Any] = {
            "candidate": self._profile.get("candidate", {}),
            "experiences": experiences,
            "skills_all": skills_all,
            "skill_ids": highlights.get("skill_ids", []),
            "education": self._profile.get("education", []),
            "projects": self._profile.get("projects", []),
            "hook": highlights.get("hook", ""),
        }

        html = self._render_html(context)

        company_name = job.company.name if job.company else "unknown"
        filename = (
            f"cv_{_slug(job.title)}_{_slug(company_name)}_{date.today().strftime('%Y%m%d')}.pdf"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._html_to_pdf(html, output_dir / filename)

    async def _select_highlights(self, job: Job) -> dict[str, Any]:
        """Use Claude to identify which experiences and skills to emphasise."""
        exp_ids = [e["id"] for e in self._profile.get("experiences", [])]
        skills = self._profile.get("skills", {})
        all_skills: list[str] = skills.get("top_3", []) + skills.get("additional", [])

        user_message = (
            "## Candidate Profile\n"
            f"Experience IDs available: {', '.join(exp_ids)}\n"
            f"Skills available: {', '.join(all_skills)}\n\n"
            "## Job Offer\n"
            f"Title: {job.title}\n"
            f"Company: {job.company.name if job.company else 'Unknown'}\n"
            f"Description:\n{(job.description or '')[:1500]}"
        )

        response = await self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=_CV_MAX_TOKENS,
            system=_CV_SYSTEM_MESSAGE,
            messages=[{"role": "user", "content": user_message}],
        )
        text = next(block.text for block in response.content if hasattr(block, "text"))

        data: dict[str, Any] | None = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(match.group())

        if data is None:
            raise ValueError(f"Could not parse JSON from _select_highlights: {text!r}")

        return data  # type: ignore[return-value]

    def _render_html(self, context: dict[str, Any]) -> str:
        """Render the Jinja2 CV template with the given context."""
        template = self._jinja_env.get_template("cv.html.jinja2")
        return template.render(**context)

    def _html_to_pdf(self, html: str, output_path: Path) -> Path:
        """Convert an HTML string to PDF using WeasyPrint."""
        from weasyprint import HTML  # type: ignore[import-untyped]
        HTML(string=html).write_pdf(str(output_path))
        return output_path
