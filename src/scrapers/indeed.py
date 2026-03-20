"""Indeed scraper using Playwright + BeautifulSoup."""

from typing import Any

from src.scrapers.base import BaseScraper
from src.storage.models import Job


class IndeedScraper(BaseScraper):
    """Scrape Indeed job listings.

    Does not require authentication. Parses HTML with BeautifulSoup.
    Target URL pattern: https://fr.indeed.com/jobs?q={keyword}&remotejob=true
    """

    source = "indeed"

    async def _setup(self) -> None:
        """Launch headless browser."""
        raise NotImplementedError

    async def _teardown(self) -> None:
        """Close browser."""
        raise NotImplementedError

    async def scrape(self, keywords: list[str], limit: int = 50) -> list[Job]:
        """Scrape Indeed for remote job offers matching keywords.

        Args:
            keywords: Search terms.
            limit: Max offers to return.
        """
        raise NotImplementedError

    async def _parse_raw(self, raw: dict[str, Any]) -> Job:
        """Parse an Indeed listing dict into a Job instance."""
        raise NotImplementedError

    def _parse_salary(self, salary_str: str) -> tuple[int | None, int | None]:
        """Parse Indeed salary string (e.g. '50 000 € - 70 000 € par an') into EUR/year."""
        raise NotImplementedError
