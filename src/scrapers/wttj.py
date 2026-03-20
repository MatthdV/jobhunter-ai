"""Welcome to the Jungle scraper — Playwright XHR intercept."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Browser, Page, Response, async_playwright

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)


class WTTJScraper(BaseScraper):
    """Scrape Welcome to the Jungle via Playwright XHR intercept.

    WTTJ fires JSON requests to */api/*jobs* when the search page loads.
    We intercept those responses instead of parsing HTML.

    Usage::

        async with WTTJScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "wttj"
    MIN_DELAY = 1.0
    MAX_DELAY = 2.5
    MAX_RPH = 120

    _BASE_URL = "https://www.welcometothejungle.com/fr/jobs"

    def __init__(self, headless: bool = True) -> None:
        super().__init__(headless=headless)
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._playwright_ctx: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._playwright_ctx = await async_playwright().start()
        self._browser = await self._playwright_ctx.chromium.launch(headless=self.headless)

    async def _teardown(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright_ctx:
            await self._playwright_ctx.stop()

    # ------------------------------------------------------------------
    # _fetch_raw — XHR intercept
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
    ) -> list[Any]:
        assert self._browser is not None, "_setup() must be called first"

        collected: list[dict[str, Any]] = []
        page = await self._browser.new_page()

        async def _handle_response(response: Response) -> None:
            if "/api/" in response.url and "jobs" in response.url:
                try:
                    data = await response.json()
                    if isinstance(data, dict) and "jobs" in data:
                        collected.extend(data["jobs"])
                except Exception as exc:
                    logger.warning("Failed to parse XHR response from %s: %s", response.url, exc)

        page.on("response", _handle_response)

        query = quote_plus(" ".join(keywords))
        url = f"{self._BASE_URL}?query={query}&remote=true"

        try:
            await self._wait()
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
        except Exception as exc:
            logger.warning("WTTJ page load failed: %s", exc)
        finally:
            await page.close()

        return collected[:limit]

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Parse a WTTJ API job dict into a Job instance.

        WTTJ provides structured salary data — salary_min/max are set directly
        from JSON fields. _normalize() will not call _parse_salary() for these jobs.
        """
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        try:
            title: str = raw.get("name") or ""
            url: str = raw.get("website_url") or ""

            if not title or not url:
                raise ParseError("Missing required fields 'name' or 'website_url'")

            salary_data = raw.get("salary")
            salary_min: int | None = None
            salary_max: int | None = None
            salary_raw_str: str | None = None

            if isinstance(salary_data, dict):
                raw_min = salary_data.get("min")
                raw_max = salary_data.get("max")
                if raw_min is not None:
                    salary_min = int(raw_min)
                if raw_max is not None:
                    salary_max = int(raw_max)
                if salary_min is not None or salary_max is not None:
                    salary_raw_str = f"{salary_min}-{salary_max} EUR/an"

            contract_raw = raw.get("contract_type") or {}
            contract_type: str | None = (
                contract_raw.get("fr") or contract_raw.get("en") or None
            )

            location_data = raw.get("location") or {}
            city = location_data.get("city") or ""
            country = location_data.get("country_code") or ""
            location_str = ", ".join(filter(None, [city, country])) or None

            description = " ".join(
                filter(None, [raw.get("description") or "", raw.get("profile") or ""])
            ) or None

            return Job(
                title=title,
                url=url,
                source=self.source,
                description=description,
                location=location_str,
                salary_raw=salary_raw_str,
                salary_min=salary_min,
                salary_max=salary_max,
                contract_type=contract_type,
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse WTTJ job: {exc}") from exc
