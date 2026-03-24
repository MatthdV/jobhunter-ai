"""Indeed scraper — JSearch RapidAPI (httpx, no Playwright required)."""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from src.config.settings import ConfigurationError, settings
from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://jsearch.p.rapidapi.com"
_API_HOST = "jsearch.p.rapidapi.com"
_COUNTRY = "FR"

_CONTRACT_TYPE_MAP: dict[str, str] = {
    "FULLTIME": "CDI",
    "PARTTIME": "CDD",
    "CONTRACTOR": "Freelance",
    "INTERN": "Stage",
    "TEMPORARY": "CDD",
}


class IndeedApiScraper(BaseScraper):
    """Scrape Indeed France via the JSearch RapidAPI — no Playwright required.

    Calls GET /search (one batch) then GET /job-details per result for full
    descriptions needed by the LLM scorer.

    Usage::

        async with IndeedApiScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "indeed_api"
    MIN_DELAY = 1.0
    MAX_DELAY = 2.5
    MAX_RPH = 60

    def __init__(self, headless: bool = True, api_key: str = "") -> None:
        super().__init__(headless=headless)
        resolved_key = api_key or settings.indeed_api_key
        if not resolved_key:
            raise ConfigurationError(
                "INDEED_API_KEY is not set — cannot initialise IndeedApiScraper"
            )
        self._api_key = resolved_key
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # _fetch_raw
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
    ) -> list[Any]:
        assert self._client is not None, "_setup() must be called first"

        query = " ".join(keywords)
        num_pages = min(10, math.ceil(limit / 10))

        await self._wait()
        response = await self._client.get(
            f"{_BASE_URL}/search",
            params={
                "query": query,
                "location": location,
                "country": _COUNTRY,
                "num_pages": num_pages,
                "date_posted": "all",
            },
            headers=self._headers(),
        )
        self._check_response(response)

        data: list[dict[str, Any]] = response.json().get("data", [])
        return data[:limit]

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Fetch job detail for raw["job_id"] and map to a Job instance."""
        assert self._client is not None, "_setup() must be called first"

        job_id: str = raw["job_id"]
        await self._wait()
        response = await self._client.get(
            f"{_BASE_URL}/job-details",
            params={"job_id": job_id},
            headers=self._headers(),
        )
        self._check_response(response)

        data = response.json().get("data", [])
        if not data:
            raise ParseError(f"No detail returned for job_id={job_id!r}")

        detail: dict[str, Any] = data[0]

        title: str = detail.get("job_title") or ""
        url: str = detail.get("job_apply_link") or f"https://fr.indeed.com/viewjob?jk={job_id}"
        description: str | None = detail.get("job_description") or None

        # Location: "City, COUNTRY" or just "COUNTRY" when city is absent
        city: str | None = detail.get("job_city") or None
        country: str | None = detail.get("job_country") or None
        location_parts = [p for p in [city, country] if p]
        location_str: str | None = ", ".join(location_parts) or None

        # Salary — structured values set directly; _normalize skips re-parsing
        raw_min = detail.get("job_min_salary")
        raw_max = detail.get("job_max_salary")
        salary_min: int | None = int(raw_min) if raw_min is not None else None
        salary_max: int | None = int(raw_max) if raw_max is not None else None

        employment_type: str = (detail.get("job_employment_type") or "").upper()
        contract_type: str | None = _CONTRACT_TYPE_MAP.get(employment_type)

        return Job(
            title=title,
            url=url,
            source=self.source,
            location=location_str,
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=None,
            contract_type=contract_type,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": getattr(self, "_api_key", ""),
            "X-RapidAPI-Host": _API_HOST,
        }

    def _check_response(self, response: httpx.Response) -> None:
        """Map HTTP error codes to scraper exceptions."""
        if response.status_code == 429:
            raise RateLimitError("Indeed API rate limited (HTTP 429)")
        if response.status_code in (401, 403):
            raise ParseError(
                f"Indeed API key invalid or expired (HTTP {response.status_code})"
            )
        response.raise_for_status()
