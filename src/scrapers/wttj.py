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
        country_code: str = "FR",
    ) -> list[Any]:
        if country_code != "FR":
            logger.warning("WTTJ only supports FR, skipping country=%s", country_code)
            return []

        assert self._browser is not None, "_setup() must be called first"

        collected: list[dict[str, Any]] = []
        page = await self._browser.new_page()

        async def _handle_response(response: Response) -> None:
            url = response.url
            # WTTJ uses Algolia for job search (multi-index query endpoint)
            is_algolia = "algolia.net" in url and "queries" in url
            # Fallback: legacy WTTJ internal API
            is_wttj_api = "/api/" in url and "jobs" in url
            if not (is_algolia or is_wttj_api):
                return
            try:
                data = await response.json()
                # Algolia multi-index response: {"results": [{"hits": [...]}]}
                if isinstance(data, dict) and "results" in data:
                    for result in data["results"]:
                        hits = result.get("hits", [])
                        collected.extend(hits)
                elif isinstance(data, dict) and "jobs" in data:
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

    _CONTRACT_MAP: dict[str, str] = {
        "full_time": "CDI",
        "part_time": "Temps partiel",
        "internship": "Stage",
        "freelance": "Freelance",
        "temporary": "CDD",
        "apprenticeship": "Alternance",
        "vie": "VIE",
    }

    async def _parse_raw(self, raw: Any) -> Job:
        """Parse a WTTJ Algolia hit or legacy API dict into a Job instance.

        Algolia fields (current): name, slug, reference, summary, salary_yearly_minimum,
          salary_yearly_maximum, salary_currency, remote, contract_type (string).
        Legacy fields (fallback): website_url, description, profile, salary (dict).
        """
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        try:
            title: str = raw.get("name") or ""
            if not title:
                raise ParseError("Missing required field 'name'")

            # --- URL ---
            url: str = raw.get("website_url") or ""
            if not url:
                # Algolia: build canonical URL from reference/slug
                ref = raw.get("reference") or raw.get("objectID") or raw.get("slug") or ""
                if not ref:
                    raise ParseError("Cannot build URL: no website_url, reference, or slug")
                url = f"https://www.welcometothejungle.com/fr/jobs/{ref}"

            # --- Salary ---
            salary_min: int | None = None
            salary_max: int | None = None
            salary_raw_str: str | None = None

            # Algolia yearly salary fields
            algolia_min = raw.get("salary_yearly_minimum")
            algolia_max = raw.get("salary_yearly_maximum")
            if algolia_min is not None or algolia_max is not None:
                salary_min = int(algolia_min) if algolia_min is not None else None
                salary_max = int(algolia_max) if algolia_max is not None else None
                salary_raw_str = f"{salary_min}-{salary_max} {raw.get('salary_currency', 'EUR')}/an"
            else:
                # Legacy nested salary dict
                salary_data = raw.get("salary")
                if isinstance(salary_data, dict):
                    raw_min = salary_data.get("min")
                    raw_max = salary_data.get("max")
                    if raw_min is not None:
                        salary_min = int(raw_min)
                    if raw_max is not None:
                        salary_max = int(raw_max)
                    if salary_min is not None or salary_max is not None:
                        salary_raw_str = f"{salary_min}-{salary_max} EUR/an"

            # --- Contract type ---
            ct_raw = raw.get("contract_type")
            if isinstance(ct_raw, dict):
                contract_type: str | None = ct_raw.get("fr") or ct_raw.get("en") or None
            elif isinstance(ct_raw, str):
                contract_type = self._CONTRACT_MAP.get(ct_raw, ct_raw)
            else:
                contract_type = None

            # --- Location ---
            location_data = raw.get("location") or {}
            city = location_data.get("city") or ""
            country = location_data.get("country_code") or ""
            # Algolia: offices list
            if not city:
                offices = raw.get("offices") or []
                if offices and isinstance(offices[0], dict):
                    city = offices[0].get("city") or ""
                    country = offices[0].get("country_code") or country
            location_str: str | None = ", ".join(filter(None, [city, country])) or None

            # --- Remote ---
            remote_val = raw.get("remote")
            if isinstance(remote_val, str):
                is_remote = remote_val == "full"
            elif isinstance(remote_val, bool):
                is_remote = remote_val
            else:
                is_remote = False

            # --- Description ---
            description: str | None = (
                raw.get("summary")
                or " ".join(filter(None, [raw.get("description") or "", raw.get("profile") or ""]))
                or None
            )

            return Job(
                title=title,
                url=url,
                source=self.source,
                description=description,
                location=location_str,
                is_remote=is_remote,
                salary_raw=salary_raw_str,
                salary_min=salary_min,
                salary_max=salary_max,
                contract_type=contract_type,
                country_code="FR",
                salary_currency="EUR",
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse WTTJ job: {exc}") from exc
