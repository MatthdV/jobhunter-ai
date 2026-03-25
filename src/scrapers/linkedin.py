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

_COOKIES_PATH = Path(__file__).parents[2] / "data" / "linkedin_cookies.json"
_SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={kw}&f_WT=2"
_LI_BASE = "https://www.linkedin.com"

_GEO_IDS: dict[str, str] = {
    "FR": "105015875",
    "US": "103644278",
    "GB": "101165590",
    "DE": "101282230",
    "NL": "102890719",
    "CH": "106693272",
    "ES": "105646813",
    "BE": "100565514",
    "CA": "101174742",
    "SE": "105117694",
}


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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        _COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)

        self._playwright_ctx = await async_playwright().start()
        self._browser = await self._playwright_ctx.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()

        # playwright-stealth v2: apply to context — all pages inherit evasions
        try:
            from playwright_stealth import Stealth
            await Stealth().apply_stealth_async(self._context)
        except ImportError:
            logger.warning("playwright-stealth not installed — LinkedIn may detect automation")

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
        # LinkedIn changed nav.global-nav to #global-nav (no longer <nav> tag)
        nav = await page.query_selector("#global-nav, .global-nav")
        return nav is not None

    def _has_credentials(self) -> bool:
        from src.config.settings import settings
        return bool(settings.linkedin_email) and bool(settings.linkedin_password)

    async def _run_login(self, page: Page) -> None:
        from src.config.settings import settings
        email = settings.linkedin_email
        password = settings.linkedin_password

        await page.goto("https://www.linkedin.com/login")
        await page.fill("#username", email)
        await page.fill("#password", password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("domcontentloaded")

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
        import asyncio as _aio
        await _aio.sleep(2)  # Let dynamic content render after domcontentloaded
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
        country_code: str = "FR",
    ) -> list[Any]:
        """Fetch jobs from LinkedIn two-pane search: click each card, read detail."""
        import asyncio as _aio

        assert self._context is not None, "_setup() must be called first"

        page = await self._context.new_page()
        raw_items: list[dict[str, Any]] = []

        try:
            await page.goto(_LI_BASE, wait_until="domcontentloaded")
            await self._authenticate(page)

            kw = quote_plus(" ".join(keywords))
            geo = _GEO_IDS.get(country_code, "")
            geo_param = f"&geoId={geo}" if geo else ""
            search_url = _SEARCH_URL.format(kw=kw) + geo_param

            await self._wait()
            await page.goto(search_url, wait_until="domcontentloaded")

            # Wait for job cards to render (SPA content loads after domcontentloaded)
            try:
                await page.wait_for_selector(
                    ".job-card-container", timeout=15000,
                )
            except Exception:
                logger.warning("No job cards found for search: %s", search_url)
                return []

            cards = await page.query_selector_all(".job-card-container")

            for card in cards:
                if len(raw_items) >= limit:
                    break

                job_id = await card.get_attribute("data-job-id")
                if not job_id:
                    continue

                # Click card to load detail in the side pane
                try:
                    await card.click()
                    await _aio.sleep(2)
                except Exception:
                    continue

                detail_html = await page.content()
                detail_soup = BeautifulSoup(detail_html, "lxml")
                job_url = f"{_LI_BASE}/jobs/view/{job_id}/"
                raw_items.append({"url": job_url, "detail_soup": detail_soup})

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
        """Parse a LinkedIn two-pane detail dict into a Job instance.

        Expects raw = {"url": str, "detail_soup": BeautifulSoup}.
        """
        if not isinstance(raw, dict) or "url" not in raw or "detail_soup" not in raw:
            raise ParseError("LinkedInScraper._parse_raw expects {url, detail_soup}")

        try:
            url: str = raw["url"]
            soup: BeautifulSoup = raw["detail_soup"]

            # Title — try new two-pane layout, then legacy selector
            title_el = soup.select_one(
                ".job-details-jobs-unified-top-card__job-title, "
                ".jobs-unified-top-card__job-title, "
                ".jobs-unified-top-card h1"
            )
            title: str = title_el.get_text(strip=True) if title_el else ""

            if not title:
                raise ParseError(f"Missing title in LinkedIn detail pane for {url}")

            # Location — new layout: metadata container; legacy: second bullet
            meta_el = soup.select_one(
                ".job-details-jobs-unified-top-card__primary-description-container, "
                ".jobs-unified-top-card__subtitle-primary-grouping"
            )
            location_str: str | None = None
            if meta_el:
                meta_text = meta_el.get_text(separator="·", strip=True)
                parts = [p.strip() for p in meta_text.split("·")]
                if parts:
                    location_str = parts[0]
            else:
                # Legacy: second bullet
                location_el = soup.select_one(
                    ".jobs-unified-top-card__bullet ~ .jobs-unified-top-card__bullet"
                )
                location_str = location_el.get_text(strip=True) if location_el else None

            # Description — try multiple selectors (new + legacy)
            description_el = soup.select_one(
                ".jobs-description__content, "
                ".jobs-description-content__text, "
                ".jobs-box__html-content"
            )
            description: str | None = (
                description_el.get_text(separator=" ", strip=True)
                if description_el
                else None
            )

            # Salary — new layout: job insight spans; legacy: top-card insight
            salary_raw_str: str | None = None
            for insight in soup.select(
                ".job-details-jobs-unified-top-card__job-insight span, "
                ".jobs-unified-top-card__job-insight span"
            ):
                text = insight.get_text(strip=True)
                if "€" in text or "$" in text or "£" in text or ("k" in text.lower() and any(c.isdigit() for c in text)):
                    salary_raw_str = text
                    break

            # Contract type — legacy: first bullet; new layout: not reliably available
            contract_el = soup.select_one(".jobs-unified-top-card__bullet")
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
