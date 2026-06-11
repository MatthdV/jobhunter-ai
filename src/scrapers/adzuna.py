"""Adzuna job search scraper — official REST API v1 (httpx, no Playwright).

Auth: app_id + app_key as query params.
Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
Docs: https://developer.adzuna.com/overview

Register at https://developer.adzuna.com/signup (free).
Supported countries: au, at, be, br, ca, de, es, fr, gb, in, it, nl, nz, pl, sg, us, za, ch, se.
Rate limit: not documented; use conservative rate limiting.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config.settings import settings
from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# All countries Adzuna supports — ISO 3166-1 alpha-2 upper → Adzuna lowercase code
# For most countries they are identical when lowercased; explicit map for clarity.
_SUPPORTED_COUNTRIES: frozenset[str] = frozenset({
    "AU", "AT", "BE", "BR", "CA", "DE", "ES", "FR", "GB", "IN",
    "IT", "NL", "NZ", "PL", "SG", "US", "ZA", "CH", "SE",
})


class AdzunaScraper(BaseScraper):
    """Scrape job offers via the Adzuna REST API.

    Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in env/settings.
    Free tier available at https://developer.adzuna.com/signup.

    Usage::

        async with AdzunaScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50, country_code="GB")
    """

    source = "adzuna"
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5
    MAX_RPH = 180

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def _get_credentials(self) -> tuple[str, str]:
        """Return (app_id, app_key) from settings or per-user store."""
        app_id = settings.adzuna_app_id
        app_key = settings.adzuna_api_key
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
                        app_id = u_cfg.get("adzuna_app_id") or app_id
                        app_key = u_cfg.get("adzuna_api_key") or app_key
            except Exception as exc:
                logger.debug("Adzuna: could not load per-user credentials: %s", exc)
        return app_id, app_key

    # ------------------------------------------------------------------
    # _fetch_raw
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "GB",
    ) -> list[Any]:
        country_upper = country_code.upper()
        if country_upper not in _SUPPORTED_COUNTRIES:
            logger.warning("Adzuna: country %s not supported, skipping", country_code)
            return []

        assert self._client is not None, "_setup() must be called first"

        app_id, app_key = self._get_credentials()
        if not app_id or not app_key:
            logger.warning("Adzuna: ADZUNA_APP_ID / ADZUNA_API_KEY not configured")
            return []

        adzuna_country = country_upper.lower()
        query = " ".join(keywords)
        results_per_page = min(limit, 50)

        params: dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "what": query,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }
        if location:
            params["where"] = location
        if filters.max_days_old:
            params["max_days_old"] = filters.max_days_old

        work_mode = (filters.work_modes or ["remote"])[0]
        if work_mode == "remote":
            params["what_and"] = "remote"

        await self._wait()
        response = await self._client.get(
            f"{_BASE_URL}/{adzuna_country}/search/1",
            params=params,
        )

        if response.status_code == 429:
            raise RateLimitError("Adzuna API rate limited (HTTP 429)")
        if response.status_code in (401, 403):
            raise ParseError(f"Adzuna credentials invalid (HTTP {response.status_code})")
        response.raise_for_status()

        data = response.json()
        results: list[dict[str, Any]] = data.get("results", [])
        logger.debug("Adzuna: %d results for %s/%s", len(results), country_upper, keywords)
        return results[:limit]

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Map an Adzuna search result dict to a Job instance."""
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        try:
            title: str = raw.get("title") or ""
            if not title:
                raise ParseError("Missing required field 'title'")

            url: str = raw.get("redirect_url") or ""
            if not url:
                raise ParseError("Missing required field 'redirect_url'")

            # Description — Adzuna provides a snippet, not full description
            description: str | None = raw.get("description") or None

            # Location
            location_data = raw.get("location") or {}
            location_str: str | None = location_data.get("display_name") or None

            # Salary
            raw_min = raw.get("salary_min")
            raw_max = raw.get("salary_max")
            salary_min: int | None = int(raw_min) if raw_min is not None else None
            salary_max: int | None = int(raw_max) if raw_max is not None else None
            salary_raw_str: str | None = None
            if salary_min is not None or salary_max is not None:
                salary_raw_str = f"{salary_min}-{salary_max}"

            # Contract type
            contract_type: str | None = raw.get("contract_type") or raw.get("contract_time") or None

            # Remote detection — Adzuna doesn't have a dedicated remote field;
            # check title/description for "remote" keyword
            is_remote = False
            combined = f"{title} {description or ''}".lower()
            if "remote" in combined or "télétravail" in combined or "full remote" in combined:
                is_remote = True

            # Determine country from the company/location data
            country_code = "GB"  # default; caller sets this via search()

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
                country_code=country_code,
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse Adzuna job: {exc}") from exc
