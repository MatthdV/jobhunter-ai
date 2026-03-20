"""LinkedIn Jobs scraper using Playwright."""

from typing import Any

from src.scrapers.base import BaseScraper
from src.storage.models import Job


class LinkedInScraper(BaseScraper):
    """Scrape LinkedIn Jobs via authenticated Playwright session.

    Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env.
    Respects LinkedIn rate limits — do not reduce delays below 2s between pages.
    """

    source = "linkedin"

    async def _setup(self) -> None:
        """Launch Playwright browser and log in to LinkedIn."""
        raise NotImplementedError

    async def _teardown(self) -> None:
        """Close browser and Playwright context."""
        raise NotImplementedError

    async def scrape(self, keywords: list[str], limit: int = 50) -> list[Job]:
        """Search LinkedIn Jobs and return matching offers.

        Args:
            keywords: Search terms (e.g. ["automation engineer", "n8n"]).
            limit: Max offers to return.
        """
        raise NotImplementedError

    async def _parse_raw(self, raw: dict[str, Any]) -> Job:
        """Parse a LinkedIn job card dict into a Job instance."""
        raise NotImplementedError

    def _parse_salary(self, salary_str: str) -> tuple[int | None, int | None]:
        """Parse LinkedIn salary range string into (min, max) EUR/year."""
        raise NotImplementedError
