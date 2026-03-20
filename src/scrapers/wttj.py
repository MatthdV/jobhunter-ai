"""Welcome to the Jungle scraper using their public API."""

from typing import Any

from src.scrapers.base import BaseScraper
from src.storage.models import Job


class WTTJScraper(BaseScraper):
    """Scrape Welcome to the Jungle via their JSON API.

    WTTJ exposes a public search API at https://www.welcometothejungle.com/api/v1/jobs.
    No authentication required. More stable than HTML parsing.
    """

    source = "wttj"
    _BASE_URL = "https://www.welcometothejungle.com/api/v1/jobs"

    async def _setup(self) -> None:
        """Initialise HTTPX async client."""
        raise NotImplementedError

    async def _teardown(self) -> None:
        """Close HTTPX client."""
        raise NotImplementedError

    async def scrape(self, keywords: list[str], limit: int = 50) -> list[Job]:
        """Fetch remote job offers matching keywords from WTTJ.

        Args:
            keywords: Search terms.
            limit: Max offers to return.
        """
        raise NotImplementedError

    async def _parse_raw(self, raw: dict[str, Any]) -> Job:
        """Parse a WTTJ API job object into a Job instance."""
        raise NotImplementedError

    def _parse_salary(self, salary_str: str) -> tuple[int | None, int | None]:
        """Parse WTTJ salary range into EUR/year."""
        raise NotImplementedError
