"""Abstract base class for all job board scrapers."""

from abc import ABC, abstractmethod
from typing import Any

from src.storage.models import Job


class BaseScraper(ABC):
    """Contract that every scraper must satisfy.

    Each concrete scraper handles one job board (LinkedIn, Indeed, WTTJ…).
    Scrapers are async context managers so they can own a Playwright browser
    or an HTTP session for their lifetime.

    Usage::

        async with LinkedInScraper() as scraper:
            jobs = await scraper.scrape(keywords=["automation engineer"], limit=50)
    """

    #: Identifier stored in Job.source — must be overridden in subclasses.
    source: str

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self, keywords: list[str], limit: int = 50) -> list[Job]:
        """Scrape offers matching *keywords* and return unsaved Job instances.

        The caller is responsible for persisting jobs to the database.

        Args:
            keywords: Search terms to query the job board with.
            limit: Maximum number of offers to return.

        Returns:
            List of Job ORM instances (not yet committed to the session).
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle — override in subclasses as needed
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialise browser / HTTP session. Called by __aenter__."""
        ...

    async def _teardown(self) -> None:
        """Clean up resources. Called by __aexit__."""
        ...

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @abstractmethod
    async def _parse_raw(self, raw: dict[str, Any]) -> Job:
        """Convert a raw dict (from HTML or API) into a Job instance."""
        ...

    @abstractmethod
    def _parse_salary(self, salary_str: str) -> tuple[int | None, int | None]:
        """Parse a free-text salary string into (min, max) in EUR/year.

        Returns (None, None) if parsing fails.
        """
        ...

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseScraper":
        await self._setup()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._teardown()
