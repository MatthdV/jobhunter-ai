"""Gmail job-alert scraper — reads LinkedIn alert emails, enriches via JSearch."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from src.config.settings import ConfigurationError, settings
from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_ALERT_SENDER = "jobalerts-noreply@linkedin.com"
_JOB_URL_RE = re.compile(r"https://www\.linkedin\.com/(?:comm/)?jobs/view/(\d+)")
_JSEARCH_BASE = "https://jsearch.p.rapidapi.com"
_JSEARCH_HOST = "jsearch.p.rapidapi.com"


class GmailJobAlertScraper(BaseScraper):
    """Read unread LinkedIn job-alert emails from Gmail, enrich via JSearch.

    Flow:
        1. List unread messages from jobalerts-noreply@linkedin.com
        2. Parse HTML body → {title, company, location, url} stubs
        3. For each stub: search JSearch with "title company" → full JD
        4. Return normalised Job instances; mark processed emails as read

    Usage::

        async with GmailJobAlertScraper() as scraper:
            jobs = await scraper.scan_alerts(max_emails=5)
    """

    source = "gmail_alert"
    MIN_DELAY = 1.0
    MAX_DELAY = 2.0
    MAX_RPH = 60

    def __init__(self, headless: bool = True) -> None:
        super().__init__(headless=headless)
        if not settings.is_gmail_configured:
            raise ConfigurationError(
                "Gmail not configured — set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
                "GMAIL_REFRESH_TOKEN in .env"
            )
        if not settings.indeed_api_key:
            raise ConfigurationError(
                "INDEED_API_KEY required for JSearch enrichment in GmailJobAlertScraper"
            )
        self._gmail_service: Any = None
        self._http: Any = None  # httpx.AsyncClient
        self._jsearch_available: bool = True  # set False on first 403/subscription error

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        import httpx

        self._gmail_service = await asyncio.to_thread(self._build_gmail_service)
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _teardown(self) -> None:
        if self._http:
            await self._http.aclose()

    def _build_gmail_service(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(  # type: ignore[no-untyped-call]
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=["https://mail.google.com/"],
        )
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan_alerts(
        self,
        max_emails: int = 10,
        seen_urls: set[str] | None = None,
        country_code: str = "FR",
    ) -> list[Job]:
        """Fetch unread LinkedIn alert emails and return enriched Job instances."""
        db_seen = set(seen_urls) if seen_urls else set()  # copy — don't mutate caller's set
        stubs = await self._fetch_stubs(max_emails)
        jobs: list[Job] = []

        for stub in stubs:
            if stub["url"] in db_seen:
                continue
            job = await self._with_retry(
                lambda s=stub, cc=country_code: self._enrich(s, cc)
            )
            if job is None:
                continue
            normalised = self._normalize(job)
            if normalised is not None:
                normalised.country_code = country_code  # type: ignore[assignment]
                jobs.append(normalised)
                db_seen.add(stub["url"])

        return jobs

    # BaseScraper ABC — scan_alerts() is the intended public API;
    # _fetch_raw/_parse_raw satisfy the abstract contract.

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        return await self._fetch_stubs(max_emails=limit)

    async def _parse_raw(self, raw: Any) -> Job:
        return await self._enrich(raw, country_code="FR")

    # ------------------------------------------------------------------
    # Gmail — fetch + parse
    # ------------------------------------------------------------------

    async def _fetch_stubs(self, max_emails: int) -> list[dict[str, Any]]:
        msg_ids = await asyncio.to_thread(self._list_alert_messages, max_emails)
        stubs: list[dict[str, Any]] = []
        for msg_id in msg_ids:
            raw_msg = await asyncio.to_thread(self._fetch_message, msg_id)
            new_stubs = self._parse_email(raw_msg)
            stubs.extend(new_stubs)
            if new_stubs:
                await asyncio.to_thread(self._mark_read, msg_id)
        return stubs

    def _list_alert_messages(self, max_results: int) -> list[str]:
        result = (
            self._gmail_service.users()
            .messages()
            .list(
                userId="me",
                q=f"from:{_ALERT_SENDER} is:unread",
                maxResults=max_results,
            )
            .execute()
        )
        return [m["id"] for m in result.get("messages", [])]

    def _fetch_message(self, message_id: str) -> dict[str, Any]:
        return (
            self._gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def _mark_read(self, message_id: str) -> None:
        self._gmail_service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def _parse_email(self, raw_msg: dict[str, Any]) -> list[dict[str, Any]]:
        html = self._extract_html(raw_msg)
        if not html:
            return []
        return self._parse_html(html)

    def _extract_html(self, raw_msg: dict[str, Any]) -> str:
        return self._walk_parts(raw_msg.get("payload", {}))

    def _walk_parts(self, payload: dict[str, Any]) -> str:
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            result = self._walk_parts(part)
            if result:
                return result
        return ""

    def _parse_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        stubs: list[dict[str, Any]] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            match = _JOB_URL_RE.search(link["href"])
            if not match:
                continue
            job_id = match.group(1)
            url = f"https://www.linkedin.com/jobs/view/{job_id}"
            if url in seen:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            company, location = self._extract_company_location(link)
            seen.add(url)
            stubs.append(
                {"title": title, "company": company, "location": location, "url": url}
            )

        return stubs

    def _extract_company_location(
        self, link_tag: Any
    ) -> tuple[str | None, str | None]:
        """Walk up ancestors until we find a node whose text contains '·'.

        LinkedIn alert emails use nested tables — company · location lands in
        the <tbody> two levels above the title <tr>, not in the <tr> itself.
        """
        node = link_tag
        for _ in range(15):
            node = node.parent
            if node is None:
                break
            text = node.get_text(separator="|", strip=True)
            if "·" not in text and " · " not in text:
                continue
            # Found the right container — extract "Company · Location" segment
            for seg in text.split("|"):
                seg = seg.strip()
                if "·" in seg or "·" in seg:
                    dot = seg.find("·") if "·" in seg else seg.find("·")
                    company = seg[:dot].strip() or None
                    location = seg[dot + 1:].strip() or None
                    return company, location
            break

        return None, None

    # ------------------------------------------------------------------
    # JSearch enrichment
    # ------------------------------------------------------------------

    async def _enrich(self, stub: dict[str, Any], country_code: str) -> Job:
        assert self._http is not None

        # Short-circuit: subscription dead or previously failed — skip all API calls
        if not self._jsearch_available:
            return self._stub_to_job(stub)

        title = stub.get("title", "")
        company = stub.get("company") or ""
        query = f"{title} {company}".strip()

        await self._wait()
        response = await self._http.get(
            f"{_JSEARCH_BASE}/search",
            params={"query": query, "num_pages": "1", "date_posted": "all"},
            headers={"X-RapidAPI-Key": settings.indeed_api_key, "X-RapidAPI-Host": _JSEARCH_HOST},
        )

        if response.status_code == 429:
            raise RateLimitError("JSearch rate limited (HTTP 429)")
        if response.status_code == 403:
            logger.warning(
                "JSearch returned 403 (not subscribed). "
                "Disabling enrichment for this run — jobs saved as stubs. "
                "Renew subscription at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"
            )
            self._jsearch_available = False
            return self._stub_to_job(stub)
        if response.status_code == 200:
            data = response.json().get("data", [])
            best = self._best_match(data, stub)
            if best:
                return self._result_to_job(best, stub)

        return self._stub_to_job(stub)

    def _best_match(
        self, results: list[dict[str, Any]], stub: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not results:
            return None
        stub_title = stub.get("title", "").lower()
        stub_company = (stub.get("company") or "").lower()
        for r in results:
            r_title = (r.get("job_title") or "").lower()
            r_company = (r.get("employer_name") or "").lower()
            title_hit = any(w in r_title for w in stub_title.split() if len(w) > 3)
            company_hit = bool(stub_company) and stub_company[:6] in r_company
            if title_hit or company_hit:
                return r
        return results[0]

    def _result_to_job(self, result: dict[str, Any], stub: dict[str, Any]) -> Job:
        raw_min = result.get("job_min_salary")
        raw_max = result.get("job_max_salary")
        city = result.get("job_city") or stub.get("location")
        country = result.get("job_country")
        location_parts = [p for p in [city, country] if p]
        return Job(
            title=result.get("job_title") or stub["title"],
            url=stub["url"],
            source=self.source,
            location=", ".join(location_parts) or stub.get("location"),
            description=result.get("job_description"),
            salary_min=int(raw_min) if raw_min is not None else None,
            salary_max=int(raw_max) if raw_max is not None else None,
            salary_raw=None,
            contract_type=None,
        )

    def _stub_to_job(self, stub: dict[str, Any]) -> Job:
        return Job(
            title=stub["title"],
            url=stub["url"],
            source=self.source,
            location=stub.get("location"),
            description=None,
            salary_min=None,
            salary_max=None,
            salary_raw=None,
            contract_type=None,
        )
