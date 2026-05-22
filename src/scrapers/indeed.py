"""Indeed scraper — Playwright + BeautifulSoup."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Browser, async_playwright

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job
from src.utils.salary_normalizer import get_country_config

logger = logging.getLogger(__name__)

_INDEED_BASE_URL = "https://fr.indeed.com/jobs"
# Remote filter param for Indeed France
_REMOTE_PARAM = "032b3"

_INDEED_REMOTE_QS: dict[str, str] = {
    "remote": f"remotejob={_REMOTE_PARAM}",
    "hybrid": "sc=0kf%3Attr(DSQF7)%3B",
    "on-site": "",
}


class IndeedScraper(BaseScraper):
    """Scrape Indeed France job listings.

    No authentication required. Renders the page with Playwright then
    parses the HTML with BeautifulSoup.

    Usage::

        async with IndeedScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "indeed"
    USES_BROWSER = True
    MIN_DELAY = 2.0
    MAX_DELAY = 4.0
    MAX_RPH = 60

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._browser: Browser | None = None
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
    # _fetch_raw
    # ------------------------------------------------------------------

    def _get_base_url(self, country_code: str) -> str:
        """Return the Indeed base URL for a given country."""
        config = get_country_config(country_code)
        domain = config.indeed_domain if config else "fr"
        return f"https://{domain}.indeed.com/jobs"

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        assert self._browser is not None, "_setup() must be called first"

        base_url = self._get_base_url(country_code)
        all_cards: list[Tag] = []
        page = await self._browser.new_page()
        query = quote_plus(" ".join(keywords))
        start = 0

        try:
            while len(all_cards) < limit:
                work_mode = (filters.work_modes or ["remote"])[0]
                remote_qs_part = _INDEED_REMOTE_QS.get(work_mode, f"remotejob={_REMOTE_PARAM}")
                remote_qs = f"&{remote_qs_part}" if remote_qs_part else ""
                age_qs = f"&fromage={filters.max_days_old}" if filters.max_days_old else ""
                url = f"{base_url}?q={query}{remote_qs}{age_qs}&start={start}"
                await self._wait()
                await page.goto(url)
                await page.wait_for_load_state("networkidle")

                html = await page.content()
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(".job_seen_beacon")

                if not cards:
                    break

                all_cards.extend(cards)
                start += 10  # Indeed paginates by 10
        except Exception as exc:
            logger.warning("Indeed page load failed: %s", exc)
        finally:
            await page.close()

        return all_cards[:limit]

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Parse a BeautifulSoup Tag (.job_seen_beacon card) into a Job instance."""
        if not isinstance(raw, Tag):
            raise ParseError(f"Expected bs4.Tag, got {type(raw).__name__}")

        try:
            title_el = raw.select_one(".jobTitle span[title]")
            title: str = (title_el.get_text(strip=True) if title_el else "") or ""

            link_el = raw.select_one(".jobTitle a[data-jk]")
            job_key = link_el["data-jk"] if link_el else ""
            # Always use the canonical /viewjob URL — the href is a tracking redirect
            url = f"https://fr.indeed.com/viewjob?jk={job_key}" if job_key else ""

            if not title or not url:
                raise ParseError("Missing title or URL in Indeed card")

            location_el = raw.select_one(".companyLocation")
            location_str: str | None = location_el.get_text(strip=True) if location_el else None

            salary_el = raw.select_one(".salary-snippet")
            salary_raw_str: str | None = salary_el.get_text(strip=True) if salary_el else None

            snippet_el = raw.select_one(".job-snippet")
            description: str | None = (
                snippet_el.get_text(separator=" ", strip=True) if snippet_el else None
            )

            return Job(
                title=title,
                url=url,
                source=self.source,
                location=location_str or None,
                salary_raw=salary_raw_str,
                salary_min=None,   # salary_min/max parsed by _normalize
                salary_max=None,
                description=description,
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse Indeed card: {exc}") from exc
