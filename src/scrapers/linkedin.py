"""LinkedIn Jobs scraper — playwright-stealth + persistent cookies."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import AuthenticationError, ParseError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_COOKIES_PATH = Path("data/linkedin_cookies.json")
_SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={kw}&f_WT=2"
_LI_BASE = "https://www.linkedin.com"


class LinkedInScraper(BaseScraper):
    """Scrape LinkedIn Jobs with stealth Playwright + cookie persistence.

    Authentication flow:
    1. Load cookies from data/linkedin_cookies.json (if present).
    2. Navigate to linkedin.com — check for authenticated nav element.
    3. If not authenticated and credentials available → run login flow.
    4. If not authenticated and credentials missing → raise AuthenticationError.
    5. 2FA / CAPTCHA encountered → raise AuthenticationError (out of scope Phase 1).

    Usage::

        async with LinkedInScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "linkedin"
    MIN_DELAY = 3.0
    MAX_DELAY = 7.0
    MAX_RPH = 30

    def __init__(self, headless: bool = True) -> None:
        super().__init__(headless=headless)
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright_ctx: Any = None
        self._stealth_fn: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        Path("data").mkdir(exist_ok=True)

        self._playwright_ctx = await async_playwright().start()

        try:
            from playwright_stealth import stealth_async  # type: ignore[import]
            self._stealth_fn = stealth_async
        except ImportError:
            logger.warning("playwright-stealth not installed — LinkedIn may detect automation")
            self._stealth_fn = None

        self._browser = await self._playwright_ctx.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()

        if _COOKIES_PATH.exists():
            cookies = json.loads(_COOKIES_PATH.read_text())
            await self._context.add_cookies(cookies)

    async def _teardown(self) -> None:
        if self._context:
            cookies = await self._context.cookies()
            _COOKIES_PATH.parent.mkdir(exist_ok=True)
            _COOKIES_PATH.write_text(json.dumps(cookies))
        if self._browser:
            await self._browser.close()
        if self._playwright_ctx:
            await self._playwright_ctx.stop()

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------

    async def _is_authenticated(self, page: Page) -> bool:
        nav = await page.query_selector("nav.global-nav")
        return nav is not None

    def _has_credentials(self) -> bool:
        return bool(os.getenv("LINKEDIN_EMAIL")) and bool(os.getenv("LINKEDIN_PASSWORD"))

    async def _run_login(self, page: Page) -> None:
        email = os.getenv("LINKEDIN_EMAIL", "")
        password = os.getenv("LINKEDIN_PASSWORD", "")

        await page.goto("https://www.linkedin.com/login")
        await page.fill("#username", email)
        await page.fill("#password", password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Detect 2FA / CAPTCHA challenge pages
        url = page.url
        if "challenge" in url or "checkpoint" in url:
            raise AuthenticationError(
                "2FA challenge or CAPTCHA detected on LinkedIn — resolve manually and re-run"
            )

        if not await self._is_authenticated(page):
            raise AuthenticationError("Login failed — credentials may be incorrect")

    async def _authenticate(self, page: Page) -> None:
        """Ensure the page is authenticated. Raises AuthenticationError if not possible."""
        if await self._is_authenticated(page):
            return

        if not self._has_credentials():
            raise AuthenticationError(
                "LinkedIn cookies expired and no credentials in environment. "
                "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env"
            )

        await self._run_login(page)

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
        assert self._context is not None, "_setup() must be called first"

        page = await self._context.new_page()
        if self._stealth_fn:
            await self._stealth_fn(page)

        raw_items: list[dict[str, Any]] = []

        try:
            await page.goto(_LI_BASE)
            await self._authenticate(page)

            kw = quote_plus(" ".join(keywords))
            search_url = _SEARCH_URL.format(kw=kw)

            await self._wait()
            await page.goto(search_url)
            await page.wait_for_load_state("networkidle")

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".jobs-search-results__list-item .base-card")

            for card in cards:
                link_el = card.select_one("a.base-card__full-link")
                if not link_el:
                    continue
                job_url: str = link_el.get("href", "") or ""  # type: ignore[assignment]
                if not job_url:
                    continue

                # Fetch detail page for full description
                await self._wait()
                detail_page = await self._context.new_page()
                if self._stealth_fn:
                    await self._stealth_fn(detail_page)

                try:
                    await detail_page.goto(job_url)
                    await detail_page.wait_for_load_state("networkidle")
                    detail_html = await detail_page.content()
                    detail_soup = BeautifulSoup(detail_html, "lxml")
                    raw_items.append({"url": job_url, "detail_soup": detail_soup})
                except Exception as exc:
                    logger.warning("Failed to load LinkedIn job detail %s: %s", job_url, exc)
                finally:
                    await detail_page.close()

                if len(raw_items) >= limit:
                    break

        except AuthenticationError:
            raise
        except Exception as exc:
            logger.warning("LinkedIn search failed: %s", exc)
        finally:
            await page.close()

        return raw_items

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Parse a LinkedIn detail page dict into a Job instance.

        Expects raw = {"url": str, "detail_soup": BeautifulSoup}.
        """
        if not isinstance(raw, dict) or "url" not in raw or "detail_soup" not in raw:
            raise ParseError("LinkedInScraper._parse_raw expects {url, detail_soup}")

        try:
            url: str = raw["url"]
            soup: BeautifulSoup = raw["detail_soup"]

            title_el = soup.select_one(".jobs-unified-top-card h1")
            title: str = title_el.get_text(strip=True) if title_el else ""

            if not title:
                raise ParseError(f"Missing title in LinkedIn detail page for {url}")

            location_el = soup.select_one(".jobs-unified-top-card__bullet")
            location_str: str | None = (
                location_el.get_text(strip=True) if location_el else None
            )

            salary_el = soup.select_one(".jobs-unified-top-card__job-insight span")
            salary_raw_str: str | None = None
            if salary_el:
                text = salary_el.get_text(strip=True)
                if "€" in text or "k" in text.lower():
                    salary_raw_str = text

            description_el = soup.select_one(".jobs-description-content__text")
            description: str | None = (
                description_el.get_text(separator=" ", strip=True)
                if description_el
                else None
            )

            contract_el = soup.select_one(
                ".jobs-unified-top-card__bullet ~ .jobs-unified-top-card__bullet"
            )
            contract_type: str | None = (
                contract_el.get_text(strip=True) if contract_el else None
            )

            return Job(
                title=title,
                url=url,
                source=self.source,
                location=location_str,
                salary_raw=salary_raw_str,
                salary_min=None,
                salary_max=None,
                description=description,
                contract_type=contract_type,
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse LinkedIn job: {exc}") from exc
