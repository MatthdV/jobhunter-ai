"""Bundesagentur für Arbeit (Germany) scraper — official public API (httpx, no Playwright).

Auth: public X-API-Key header (no registration required).
Search: GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs
Detail: GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{base64(refnr)}
Docs: https://jobsuche.api.bund.dev/

No credentials needed. The API key "jobboerse-jobsuche" is the public key for this API.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
_API_KEY = "jobboerse-jobsuche"

_CONTRACT_MAP: dict[str, str] = {
    "UNBEFRISTET": "CDI",
    "BEFRISTET": "CDD",
    "KEINE_ANGABE": None,  # type: ignore[dict-item]
}


class ArbeitsagenturScraper(BaseScraper):
    """Scrape German job offers via the Bundesagentur für Arbeit public API.

    No credentials required — uses the public API key.
    Covers only DE (Germany).

    Usage::

        async with ArbeitsagenturScraper() as scraper:
            jobs = await scraper.search(keywords=["software engineer"], limit=50, country_code="DE")
    """

    source = "arbeitsagentur"
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5
    MAX_RPH = 120

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"X-API-Key": _API_KEY},
        )

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # _fetch_raw
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "DE",
    ) -> list[Any]:
        if country_code.upper() != "DE":
            logger.warning("ArbeitsagenturScraper only supports DE, skipping country=%s", country_code)
            return []

        assert self._client is not None, "_setup() must be called first"

        params: dict[str, Any] = {
            "was": " ".join(keywords),
            "size": min(limit, 100),
            "page": 1,
        }
        if location:
            params["wo"] = location
        if filters.max_days_old:
            params["veroeffentlichtseit"] = filters.max_days_old

        work_mode = (filters.work_modes or ["remote"])[0]
        if work_mode == "remote":
            params["homeoffice"] = "nv_true"
        elif work_mode == "hybrid":
            params["homeoffice"] = "prozentual"

        await self._wait()
        response = await self._client.get(f"{_BASE_URL}/pc/v4/jobs", params=params)

        if response.status_code == 429:
            raise RateLimitError("Arbeitsagentur API rate limited (HTTP 429)")
        if response.status_code in (401, 403):
            raise ParseError(f"Arbeitsagentur API auth error (HTTP {response.status_code})")
        response.raise_for_status()

        data = response.json()
        results: list[dict[str, Any]] = data.get("stellenangebote") or []
        logger.debug("Arbeitsagentur: %d results for %s", len(results), keywords)
        return results[:limit]

    # ------------------------------------------------------------------
    # _parse_raw — fetches job detail for description + salary
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Fetch job detail and map to a Job instance.

        raw is a search result dict containing at minimum 'refnr', 'titel',
        'arbeitgeber', and 'arbeitsort'.
        """
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        assert self._client is not None, "_setup() must be called first"

        try:
            refnr: str = raw.get("refnr") or ""
            title: str = raw.get("titel") or ""
            if not title:
                raise ParseError("Missing required field 'titel'")

            company: str = raw.get("arbeitgeber") or ""
            arbeitsort = raw.get("arbeitsort") or {}
            city: str = arbeitsort.get("ort") or ""

            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

            # Fetch detail for description and salary
            description: str | None = None
            salary_min: int | None = None
            salary_max: int | None = None
            salary_raw_str: str | None = None
            contract_type: str | None = None
            is_remote = False

            if refnr:
                try:
                    await self._wait()
                    encoded = base64.b64encode(refnr.encode()).decode()
                    detail_resp = await self._client.get(
                        f"{_BASE_URL}/pc/v4/jobdetails/{encoded}"
                    )
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        description = detail.get("stellenangebotsBeschreibung") or None
                        raw_min = detail.get("gehaltsspanneVon")
                        raw_max = detail.get("gehaltsspanneBis")
                        if raw_min is not None:
                            salary_min = int(raw_min)
                        if raw_max is not None:
                            salary_max = int(raw_max)
                        if salary_min is not None or salary_max is not None:
                            salary_raw_str = f"{salary_min}-{salary_max} EUR/an"
                        vertragsdauer = detail.get("vertragsdauer") or ""
                        contract_type = _CONTRACT_MAP.get(vertragsdauer, vertragsdauer) or None

                        # Remote detection from description text
                        if description:
                            desc_lower = description.lower()
                            if any(kw in desc_lower for kw in ("homeoffice", "home office", "remote", "telearbeit", "fernarbeit")):
                                is_remote = True
                except Exception as exc:
                    logger.debug("Arbeitsagentur: could not fetch detail for %s: %s", refnr, exc)

            location_str: str | None = ", ".join(filter(None, [city, "DE"])) or None

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
                country_code="DE",
                salary_currency="EUR",
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse Arbeitsagentur job: {exc}") from exc
