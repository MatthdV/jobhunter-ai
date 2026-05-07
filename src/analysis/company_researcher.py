"""Company research — enrich Company model with web data before scoring."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from src.config.settings import settings
from src.llm.base import LLMClient
from src.llm.factory import get_client
from src.storage.models import Company

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You are a company research analyst. Given a company name (and optionally a job URL), "
    "provide structured intelligence about the company.\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "size_estimate": "<string like 50-200, 1000+, or null>",\n'
    '  "sector": "<string like fintech, ai, saas, or null>",\n'
    '  "funding_stage": "<string like Series B, Public, Bootstrapped, or null>",\n'
    '  "tech_stack_signals": ["<technology>", ...],\n'
    '  "culture_signals": ["<signal>", ...],\n'
    '  "glassdoor_rating": <float or null>,\n'
    '  "growth_signals": ["<signal>", ...],\n'
    '  "red_flags": ["<flag>", ...]\n'
    "}\n"
    "Use your training knowledge. If you don't know a field, use null or empty list.\n"
    "Do not include any text outside the JSON object."
)


@dataclass
class CompanyInsight:
    """Structured research output for a company."""

    size_estimate: str | None = None
    sector: str | None = None
    funding_stage: str | None = None
    tech_stack_signals: list[str] = field(default_factory=list)
    culture_signals: list[str] = field(default_factory=list)
    glassdoor_rating: float | None = None
    growth_signals: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)


class CompanyResearcher:
    """Research companies using LLM-based knowledge extraction."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        if llm_client is None:
            llm_client = get_client(settings.llm_provider)
        self._client = llm_client

    async def research(
        self, company_name: str, website: str | None = None
    ) -> CompanyInsight:
        """Research a company using LLM knowledge.

        Args:
            company_name: Name of the company to research.
            website: Optional company website for additional context.

        Returns:
            Structured CompanyInsight with available data.
        """
        prompt = f"Research the company: {company_name}"
        if website:
            prompt += f"\nCompany website: {website}"

        text = await self._client.complete(
            prompt=prompt,
            max_tokens=1024,
            system=_SYSTEM_MESSAGE,
        )
        return self._parse_response(text)

    async def enrich_company_model(
        self, company: Company, session: Session
    ) -> Company:
        """Update Company in DB with research findings.

        Args:
            company: The Company ORM object to enrich.
            session: Active SQLAlchemy session.

        Returns:
            The updated Company object.
        """
        insight = await self.research(company.name, company.website)

        if insight.funding_stage:
            company.funding_stage = insight.funding_stage  # type: ignore[assignment]
        if insight.sector and not company.sector:
            company.sector = insight.sector  # type: ignore[assignment]
        if insight.size_estimate and not company.size:
            company.size = insight.size_estimate  # type: ignore[assignment]
        if insight.tech_stack_signals:
            company.tech_stack_signals = json.dumps(insight.tech_stack_signals)  # type: ignore[assignment]
        if insight.culture_signals:
            company.culture_signals = json.dumps(insight.culture_signals)  # type: ignore[assignment]
        if insight.glassdoor_rating is not None:
            company.glassdoor_rating = insight.glassdoor_rating  # type: ignore[assignment]
        if insight.growth_signals:
            company.growth_signals = json.dumps(insight.growth_signals)  # type: ignore[assignment]
        if insight.red_flags:
            company.red_flags = json.dumps(insight.red_flags)  # type: ignore[assignment]

        company.researched_at = datetime.utcnow()  # type: ignore[assignment]
        return company

    def _parse_response(self, response_text: str) -> CompanyInsight:
        """Parse LLM JSON response into CompanyInsight."""
        import contextlib
        import re

        # Strip markdown code fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()

        data: dict | None = None
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(match.group())

        if data is None:
            logger.warning(
                "Could not parse company research response: %r",
                response_text[:200],
            )
            return CompanyInsight()

        glassdoor = data.get("glassdoor_rating")
        if glassdoor is not None:
            try:
                glassdoor = float(glassdoor)
            except (ValueError, TypeError):
                glassdoor = None

        return CompanyInsight(
            size_estimate=data.get("size_estimate"),
            sector=data.get("sector"),
            funding_stage=data.get("funding_stage"),
            tech_stack_signals=list(data.get("tech_stack_signals") or []),
            culture_signals=list(data.get("culture_signals") or []),
            glassdoor_rating=glassdoor,
            growth_signals=list(data.get("growth_signals") or []),
            red_flags=list(data.get("red_flags") or []),
        )
