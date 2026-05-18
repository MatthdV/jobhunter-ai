"""Welcome to the Jungle scraper — Playwright XHR intercept."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Browser, BrowserContext, Page, Response, async_playwright

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_WTTJ_REMOTE_PARAM: dict[str, str] = {
    "remote": "full",
    "hybrid": "partial",
    "on-site": "",
}


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

    _SIGNIN_URL = "https://www.welcometothejungle.com/fr/authenticate/signin"

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._playwright_ctx: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._playwright_ctx = await async_playwright().start()
        self._browser = await self._playwright_ctx.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()
        self._authenticated = False
        email, password = self._get_wttj_credentials()
        if email and password:
            self._authenticated = await self._login(email, password)
        else:
            logger.warning("WTTJ: no credentials configured — search will return 0 results (auth required)")

    async def _teardown(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright_ctx:
            await self._playwright_ctx.stop()

    def _get_wttj_credentials(self) -> tuple[str, str]:
        """Return (email, password) from per-user encrypted store or global settings."""
        from src.config.settings import settings as _settings
        email = _settings.wttj_email
        password = _settings.wttj_password
        if self._user_id is not None:
            try:
                from src.api.user_settings import get_settings_for_user
                from src.storage.database import get_session
                from src.storage.models import User
                with get_session() as session:
                    user = session.get(User, self._user_id)
                    if user:
                        session.expunge(user)
                        u_cfg = get_settings_for_user(user)
                        email = u_cfg.get("wttj_email") or email
                        password = u_cfg.get("wttj_password") or password
            except Exception as exc:
                logger.debug("WTTJ: could not load per-user credentials: %s", exc)
        return email, password

    async def _login(self, email: str, password: str) -> bool:
        """Log into WTTJ; session cookies persist in self._context.

        Returns True on success, False on failure.
        """
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await page.goto(self._SIGNIN_URL)
            # Accept cookie consent if present
            try:
                btn = page.locator("button:has-text('OK pour moi')")
                await btn.wait_for(timeout=4000)
                await btn.click()
            except Exception:
                pass
            await page.fill("input[name='session.email']", email)
            await page.fill("input[name='session.password']", password)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle", timeout=15000)
            post_login_url = page.url
            logger.debug("WTTJ post-login URL: %s", post_login_url)
            if "authenticate" in post_login_url or "signin" in post_login_url:
                logger.warning(
                    "WTTJ: login failed for %s — still on auth page after submit "
                    "(wrong credentials or OAuth-only account)",
                    email,
                )
                return False
            logger.info("WTTJ: authenticated as %s", email)
            return True
        except Exception as exc:
            logger.warning("WTTJ login failed: %s", exc)
            return False
        finally:
            await page.close()

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

        assert self._context is not None, "_setup() must be called first"

        if not getattr(self, "_authenticated", False):
            logger.warning(
                "WTTJ: not authenticated — skipping search (fix credentials in settings)"
            )
            return []

        collected: list[dict[str, Any]] = []
        page = await self._context.new_page()

        query = quote_plus(" ".join(keywords))
        work_mode = (filters.work_modes or ["remote"])[0]
        remote_val = _WTTJ_REMOTE_PARAM.get(work_mode, "full")
        remote_qs = f"&remote={remote_val}" if remote_val else ""
        jobs_url = f"{self._BASE_URL}?query={query}{remote_qs}"

        def _is_jobs_api(response: "Response") -> bool:
            url = response.url
            return (
                "api.welcometothejungle.com" in url and "search/jobs" in url
            ) or (
                "algolia.net" in url and "queries" in url
            ) or (
                "/api/" in url and "jobs" in url and "welcometothejungle" in url
            )

        try:
            await self._wait()
            async with page.expect_response(_is_jobs_api, timeout=25000) as resp_info:
                await page.goto(jobs_url)
                logger.debug("WTTJ: navigated to %s", page.url)
                # Detect silent redirect to signin (session expired or never authenticated)
                if "authenticate" in page.url or "signin" in page.url:
                    logger.warning("WTTJ: redirected to signin — session expired")
            try:
                response = await resp_info.value
                data = await response.json()
                logger.debug("WTTJ: jobs API response from %s", response.url)
                if isinstance(data, dict) and "jobs" in data:
                    collected.extend(data["jobs"])
                elif isinstance(data, dict) and "results" in data:
                    for result in data["results"]:
                        collected.extend(result.get("hits", []))
            except Exception as exc:
                logger.warning(
                    "WTTJ: jobs XHR not captured (timeout or missing) — %s", exc
                )
        except Exception as exc:
            logger.warning("WTTJ page load failed: %s", exc)
        finally:
            await page.close()

        logger.debug("WTTJ: collected %d raw hits for %s", len(collected), keywords)

        # Post-filter by published_at (Unix timestamp) if max_days_old set
        if filters.max_days_old and collected:
            cutoff = time.time() - filters.max_days_old * 86400
            collected = [
                h for h in collected
                if not isinstance(h.get("published_at"), (int, float))
                or h["published_at"] >= cutoff
            ]

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
