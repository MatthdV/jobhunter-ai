"""LinkedIn Jobs scraper — guest API (httpx, no login, no Playwright).

LinkedIn exposes public job search and detail endpoints used by logged-out
browsers and crawlers. No account, cookies, or Playwright required.

Search:  GET /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...
Detail:  GET /jobs-guest/jobs/api/jobPosting/{job_id}
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_BASE = "https://www.linkedin.com"
_SEARCH_URL = _BASE + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL_URL = _BASE + "/jobs-guest/jobs/api/jobPosting/{job_id}"
_JOB_PAGE_URL = _BASE + "/jobs/view/{job_id}/"

_WORK_TYPE: dict[str, str] = {
    "remote": "2",
    "hybrid": "3",
    "on-site": "1",
}

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
    "AU": "101452733",
    "SG": "102454443",
    "IT": "103350119",
    "PL": "105072130",
    "AT": "103883259",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.linkedin.com/jobs/search/",
}


class LinkedInScraper(BaseScraper):
    """Scrape LinkedIn Jobs via the public guest API — no login required.

    Uses LinkedIn's undocumented guest endpoints (same data Google's crawler
    indexes). No Playwright, no cookies, no account risk.

    Rate limits: 3-6s between requests, max ~120 req/h.

    Usage::

        async with LinkedInScraper() as scraper:
            jobs = await scraper.search(
                keywords=["automation engineer"], limit=25, country_code="FR"
            )
    """

    source = "linkedin"
    MIN_DELAY = 3.0
    MAX_DELAY = 6.0
    MAX_RPH = 120

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # _fetch_raw — returns list of job_id strings
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        assert self._client is not None, "_setup() must be called first"

        work_mode = (filters.work_modes or ["remote"])[0]
        geo_id = _GEO_IDS.get(country_code.upper(), "")
        kw = " ".join(keywords)

        job_ids: list[str] = []
        start = 0
        page_size = 25

        while len(job_ids) < limit:
            params: dict[str, str] = {
                "keywords": kw,
                "start": str(start),
                "count": str(min(page_size, limit - len(job_ids))),
                "f_WT": _WORK_TYPE.get(work_mode, "2"),
            }
            if geo_id:
                params["geoId"] = geo_id
            elif location:
                params["location"] = location
            if filters.max_days_old:
                params["f_TPR"] = f"r{filters.max_days_old * 86400}"

            await self._wait()
            try:
                resp = await self._client.get(_SEARCH_URL, params=params)
            except httpx.HTTPError as exc:
                logger.warning("LinkedIn search request failed: %s", exc)
                break

            if resp.status_code == 429:
                raise RateLimitError("LinkedIn guest API rate limited (HTTP 429)")
            if resp.status_code != 200:
                logger.warning("LinkedIn search returned HTTP %d", resp.status_code)
                break

            ids = _parse_job_ids(resp.text)
            if not ids:
                break  # no more results

            job_ids.extend(ids)
            if len(ids) < page_size:
                break  # last page
            start += page_size

        logger.debug("LinkedIn: %d job IDs for %r in %s", len(job_ids), kw, country_code)
        return job_ids[:limit]

    # ------------------------------------------------------------------
    # _parse_raw — fetches detail for each job_id
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Fetch job detail page for *raw* (job_id str) and parse into Job."""
        if not isinstance(raw, str):
            raise ParseError(f"Expected job_id str, got {type(raw).__name__}")

        assert self._client is not None, "_setup() must be called first"

        job_id = raw
        url = _JOB_PAGE_URL.format(job_id=job_id)

        try:
            await self._wait()
            resp = await self._client.get(_DETAIL_URL.format(job_id=job_id))
        except httpx.HTTPError as exc:
            raise ParseError(f"LinkedIn detail fetch failed for {job_id}: {exc}") from exc

        if resp.status_code == 404:
            raise ParseError(f"LinkedIn job {job_id} not found (404)")
        if resp.status_code != 200:
            raise ParseError(f"LinkedIn detail HTTP {resp.status_code} for {job_id}")

        try:
            soup = BeautifulSoup(resp.text, "lxml")

            title_el = soup.select_one(".top-card-layout__title, .topcard__title")
            if not title_el:
                raise ParseError(f"No title found for LinkedIn job {job_id}")
            title: str = title_el.get_text(strip=True)

            company_el = soup.select_one(
                ".topcard__org-name-link, "
                ".top-card-layout__second-subline a, "
                ".topcard__flavor--black-link"
            )
            company: str | None = company_el.get_text(strip=True) if company_el else None

            location_el = soup.select_one(".topcard__flavor--bullet")
            location_str: str | None = location_el.get_text(strip=True) if location_el else None

            desc_el = soup.select_one(".description__text")
            description: str | None = (
                desc_el.get_text(separator=" ", strip=True) if desc_el else None
            )

            contract_type: str | None = None
            is_remote = False
            for item in soup.select(".description__job-criteria-item"):
                hdr_el = item.select_one(".description__job-criteria-subheader")
                val_el = item.select_one(".description__job-criteria-text--criteria")
                if not hdr_el or not val_el:
                    continue
                hdr = hdr_el.get_text(strip=True).lower()
                val = val_el.get_text(strip=True)
                if "employment type" in hdr or "type de contrat" in hdr:
                    contract_type = val
                if "remote" in val.lower() or "télétravail" in val.lower():
                    is_remote = True

            if location_str and "remote" in location_str.lower():
                is_remote = True
            if description and any(
                kw in description.lower()
                for kw in ("full remote", "fully remote", "100% remote", "télétravail complet")
            ):
                is_remote = True

            job = Job(
                title=title,
                url=url,
                source=self.source,
                location=location_str,
                description=description,
                contract_type=contract_type,
                is_remote=is_remote,
            )
            # Transient attributes (not columns) — resolved into Company /
            # Recruiter rows by the scan persistence step.
            job.company_name = company  # type: ignore[attr-defined]

            # "Message the recruiter" block: the guest API exposes the job
            # poster (name, title, profile URL) for many postings — a direct,
            # high-confidence recruiter contact.
            poster = soup.select_one(".message-the-recruiter")
            if poster is not None:
                name_el = poster.select_one(".base-main-card__title")
                title_el2 = poster.select_one(".base-main-card__subtitle")
                link_el = poster.select_one("a.base-card__full-link[href]")
                if name_el is not None:
                    job.poster_name = name_el.get_text(strip=True)  # type: ignore[attr-defined]
                    job.poster_title = (  # type: ignore[attr-defined]
                        title_el2.get_text(strip=True) if title_el2 else None
                    )
                    job.poster_linkedin_url = (  # type: ignore[attr-defined]
                        link_el["href"].split("?")[0] if link_el else None
                    )

            return job

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse LinkedIn job {job_id}: {exc}") from exc


def _parse_job_ids(html: str) -> list[str]:
    """Extract job IDs from LinkedIn guest search HTML response."""
    soup = BeautifulSoup(html, "lxml")
    ids: list[str] = []
    for el in soup.find_all(attrs={"data-entity-urn": True}):
        urn: str = el["data-entity-urn"]
        m = re.search(r":jobPosting:(\d+)", urn)
        if m:
            ids.append(m.group(1))
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]  # type: ignore[func-returns-value]
