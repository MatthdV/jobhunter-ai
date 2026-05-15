"""Direct career page scanner — scrapes company career pages via API or Playwright."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from src.scrapers.base import BaseScraper
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_PORTALS_PATH = Path(__file__).parent.parent / "config" / "portals.yaml"

_GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_ASHBY_API = "https://jobs.ashbyhq.com/api/non-user-graphql"
_ASHBY_QUERY = """\
{
  jobBoard {
    jobPostings {
      id
      title
      locationName
      publishedDate
      externalLink
    }
  }
}"""


def load_portals(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load portal definitions from portals.yaml."""
    p = path or _PORTALS_PATH
    with p.open() as fh:
        data = yaml.safe_load(fh)
    return data.get("portals", {})


def load_default_title_filter(path: Path | None = None) -> dict[str, list[str]]:
    """Load default title filter from portals.yaml."""
    p = path or _PORTALS_PATH
    with p.open() as fh:
        data = yaml.safe_load(fh)
    return data.get("default_title_filter", {"positive": [], "negative": []})


class CareerPageScraper(BaseScraper):
    """Scan company career pages directly via Greenhouse / Ashby APIs.

    Unlike keyword-based scrapers, this scraper iterates over configured
    portals and applies title filters rather than search keywords.

    Usage::

        async with CareerPageScraper() as scraper:
            jobs = await scraper.scan_all_portals(seen_urls=existing_urls)
    """

    source = "career_page"
    MIN_DELAY = 1.0
    MAX_DELAY = 2.0
    MAX_RPH = 120

    def __init__(
        self,
        headless: bool = True,
        portals_path: Path | None = None,
        user_id: int | None = None,
    ) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._portals_path = portals_path
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
    # Abstract method implementations (required by BaseScraper ABC)
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        """Not used directly — scan_all_portals is the main entry point."""
        return []

    async def _parse_raw(self, raw: Any) -> Job:
        """Not used directly — jobs are built inline from API responses."""
        return Job(title="", url="", source=self.source)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan_all_portals(
        self,
        seen_urls: set[str] | None = None,
    ) -> list[Job]:
        """Scan all configured portals and return new matching jobs."""
        assert self._client is not None, "_setup() must be called via __aenter__"

        portals = load_portals(self._portals_path)
        default_filter = load_default_title_filter(self._portals_path)
        db_seen: set[str] = seen_urls or set()
        all_jobs: list[Job] = []

        for company_name, config in portals.items():
            platform = config.get("platform", "custom")
            slug = config.get("slug", company_name)
            title_filter = config.get("title_filter", default_filter)

            try:
                if platform == "greenhouse":
                    raw_jobs = await self._scan_greenhouse(slug, title_filter)
                elif platform == "ashby":
                    raw_jobs = await self._scan_ashby(slug, title_filter)
                else:
                    logger.info(
                        "Skipping %s — custom platform not yet supported",
                        company_name,
                    )
                    continue
            except Exception:
                logger.exception("Error scanning portal %s", company_name)
                continue

            for raw in raw_jobs:
                url = raw["url"]
                if url in db_seen:
                    continue
                db_seen.add(url)
                job = Job(
                    title=raw["title"],
                    url=url,
                    source=self.source,
                    location=raw.get("location"),
                    scraped_at=datetime.now(UTC),
                )
                all_jobs.append(job)

            logger.info(
                "Portal %s (%s): %d jobs after filter",
                company_name, platform, len(raw_jobs),
            )

        return all_jobs

    # ------------------------------------------------------------------
    # Platform-specific scanners
    # ------------------------------------------------------------------

    async def _scan_greenhouse(
        self, slug: str, filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Fetch jobs from Greenhouse public API."""
        assert self._client is not None
        await self._wait()

        url = _GREENHOUSE_API.format(slug=slug)
        response = await self._client.get(url)
        response.raise_for_status()

        data = response.json()
        jobs_data: list[dict[str, Any]] = data.get("jobs", [])

        results: list[dict[str, Any]] = []
        for item in jobs_data:
            title = item.get("title", "")
            if not self._apply_title_filter(title, filters):
                continue
            loc = item.get("location", {})
            results.append({
                "title": title,
                "url": item.get("absolute_url", ""),
                "location": loc.get("name") if isinstance(loc, dict) else str(loc),
            })
        return results

    async def _scan_ashby(
        self, slug: str, filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Fetch jobs from Ashby GraphQL API."""
        assert self._client is not None
        await self._wait()

        response = await self._client.post(
            _ASHBY_API,
            json={"operationName": None, "variables": {}, "query": _ASHBY_QUERY},
            headers={
                "Content-Type": "application/json",
                "apollographql-client-name": slug,
            },
        )
        response.raise_for_status()

        data = response.json()
        postings = (
            data.get("data", {})
            .get("jobBoard", {})
            .get("jobPostings", [])
        )

        results: list[dict[str, Any]] = []
        for item in postings:
            title = item.get("title", "")
            if not self._apply_title_filter(title, filters):
                continue
            results.append({
                "title": title,
                "url": item.get("externalLink", ""),
                "location": item.get("locationName"),
            })
        return results

    # ------------------------------------------------------------------
    # Title filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_title_filter(title: str, filters: dict[str, Any]) -> bool:
        """Return True if the job title matches positive keywords and no negative keywords.

        A title passes if:
        1. At least one positive keyword is found (case-insensitive), AND
        2. No negative keyword is found (case-insensitive).
        """
        lower_title = title.lower()

        negative = filters.get("negative", [])
        for kw in negative:
            if kw.lower() in lower_title:
                return False

        positive = filters.get("positive", [])
        if not positive:
            return True
        return any(kw.lower() in lower_title for kw in positive)
