"""Abstract base class for all job board scrapers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

# French standard: 365 - 104 weekends - 11 bank holidays - ~30 leave days
WORKING_DAYS_PER_YEAR: int = 220

_REMOTE_KEYWORDS = ("remote", "télétravail", "distanciel")


class BaseScraper(ABC):
    """Fat base class that owns rate limiting, retry, deduplication,
    Playwright lifecycle, normalization, and salary parsing.

    Concrete scrapers must implement:
        - _fetch_raw(): fetch a batch of raw items (dicts, BS4 Tags, …)
        - _parse_raw(): convert one raw item to a Job instance

    Usage::

        async with WTTJScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    #: Overridden in each concrete scraper.
    source: str

    # Per-source rate-limit constants — override in subclasses.
    MIN_DELAY: float = 1.0
    MAX_DELAY: float = 2.5
    MAX_RPH: int = 120

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._token_bucket = _TokenBucket(capacity=self.MAX_RPH, rate=self.MAX_RPH / 3600)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        keywords: list[str],
        location: str = "remote",
        filters: ScraperFilters | None = None,
        limit: int = 50,
        seen_urls: set[str] | None = None,
    ) -> list[Job]:
        """Search for job offers matching *keywords*.

        Returns normalised, deduplicated Job instances. Never persists to DB.

        Args:
            keywords: Search terms.
            location: Only "remote" is supported in Phase 1.
            filters: Post-parse filters. Uses ScraperFilters defaults if None.
            limit: Maximum number of Job instances to return.
            seen_urls: URLs already persisted to DB, provided by the caller
                (JobScheduler) for cross-session deduplication.
        """
        effective_filters = filters or ScraperFilters()
        db_seen: set[str] = seen_urls or set()
        batch_seen: set[str] = set()
        results: list[Job] = []

        raw_items = await self._fetch_raw(keywords, location, effective_filters, limit)

        for raw in raw_items:
            if len(results) >= limit:
                break
            job = await self._parse_raw(raw)
            if job.url in db_seen or job.url in batch_seen:
                continue
            batch_seen.add(job.url)
            normalised = self._normalize(job, effective_filters)
            if normalised is not None:
                results.append(normalised)

        return results

    # ------------------------------------------------------------------
    # Abstract methods — implemented per scraper
    # ------------------------------------------------------------------

    @abstractmethod
    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
    ) -> list[Any]:
        """Fetch raw items from the job board.

        Returns a list of items whose type depends on the scraper:
        - WTTJ: list[dict[str, Any]]
        - Indeed: list[bs4.Tag]
        - LinkedIn: list[dict[str, Any]]
        """
        ...

    @abstractmethod
    async def _parse_raw(self, raw: Any) -> Job:
        """Convert one raw item into an unsaved Job instance."""
        ...

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, job: Job, filters: ScraperFilters | None = None) -> Job | None:
        """Apply shared normalization and post-parse filtering.

        Returns None if the job should be silently dropped (excluded keyword match).
        """
        effective_filters = filters or ScraperFilters()

        # Title: strip + title case
        job.title = job.title.strip().title()

        # Source
        job.source = self.source

        # Timestamp — never use deprecated utcnow()
        job.scraped_at = datetime.now(timezone.utc)

        # is_remote detection
        haystack = " ".join(
            filter(
                None,
                [job.title or "", job.location or "", job.description or ""],
            )
        ).lower()
        job.is_remote = any(kw in haystack for kw in _REMOTE_KEYWORDS)

        # Salary parsing — only when not already set (WTTJ provides structured values)
        if job.salary_min is None and job.salary_max is None and job.salary_raw:
            job.salary_min, job.salary_max = self._parse_salary(job.salary_raw)

        # Excluded keyword filter (case-insensitive, title + description)
        search_text = f"{job.title} {job.description or ''}".lower()
        for keyword in effective_filters.excluded_keywords:
            if keyword.lower() in search_text:
                return None

        return job

    # ------------------------------------------------------------------
    # Salary parsing
    # ------------------------------------------------------------------

    def _parse_salary(self, salary_str: str) -> tuple[int | None, int | None]:
        """Parse a free-text salary string into (min_eur_year, max_eur_year).

        Handles:
        - "80 000 € - 100 000 €/an"   → (80000, 100000)
        - "80k-100k €/an"             → (80000, 100000)
        - "700€/jour"                 → (154000, 154000)
        - "Selon profil" / ""         → (None, None)
        """
        if not salary_str:
            return (None, None)

        text = salary_str.replace("\u202f", "").replace("\xa0", "").replace(" ", "")

        # Daily rate pattern — must test before annual range to avoid misparse
        daily_match = re.search(r"(\d[\d,.]*)€?/jour", text, re.IGNORECASE)
        if daily_match:
            raw = daily_match.group(1).replace(",", ".").replace(".", "")
            try:
                daily = int(raw)
            except ValueError:
                return (None, None)
            annual = daily * WORKING_DAYS_PER_YEAR
            return (annual, annual)

        # k-notation normalisation: "80k" → "80000"
        def _expand_k(m: re.Match[str]) -> str:
            return str(int(float(m.group(1).replace(",", ".")) * 1000))

        text = re.sub(r"(\d+[,.]?\d*)k", _expand_k, text, flags=re.IGNORECASE)

        # Annual range: two numbers
        range_match = re.search(r"(\d{4,6})[^\d]+(\d{4,6})", text)
        if range_match:
            try:
                return (int(range_match.group(1)), int(range_match.group(2)))
            except ValueError:
                return (None, None)

        # Single annual amount
        single_match = re.search(r"(\d{4,6})€?/an", text, re.IGNORECASE)
        if single_match:
            try:
                val = int(single_match.group(1))
                return (val, val)
            except ValueError:
                return (None, None)

        return (None, None)

    # ------------------------------------------------------------------
    # Rate limiting helpers (used by concrete scrapers)
    # ------------------------------------------------------------------

    async def _wait(self) -> None:
        """Block until a rate-limit token is available, then sleep a random delay."""
        import asyncio
        import random

        await self._token_bucket.acquire()
        delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
        await asyncio.sleep(delay)

    async def _with_retry(self, coro_fn: Any, max_attempts: int = 3) -> Any:
        """Execute coro_fn() with exponential backoff retry.

        coro_fn must be a CALLABLE that returns a coroutine (not a bare coroutine).
        Each retry calls coro_fn() again to get a fresh coroutine — Python coroutines
        can only be awaited once, so passing a bare coroutine would fail on retry.

        Retries on RateLimitError and generic exceptions.
        Raises ParseError immediately on HTTP 403 / 404.
        After max_attempts failures, logs WARNING and returns None.
        """
        import asyncio
        import logging

        from src.scrapers.exceptions import ParseError, RateLimitError

        logger = logging.getLogger(self.__class__.__name__)
        backoff = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                return await coro_fn()
            except ParseError:
                raise
            except RateLimitError:
                if attempt == max_attempts:
                    logger.warning("Rate limited after %d attempts — skipping", max_attempts)
                    return None
                await asyncio.sleep(backoff)
                backoff *= 2
            except Exception as exc:
                if attempt == max_attempts:
                    logger.warning("Failed after %d attempts: %s — skipping", max_attempts, exc)
                    return None
                await asyncio.sleep(backoff)
                backoff *= 2

        return None

    # ------------------------------------------------------------------
    # Lifecycle — override in concrete scrapers as needed
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialise browser / HTTP session. Called by __aenter__."""

    async def _teardown(self) -> None:
        """Release resources. Called by __aexit__."""

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseScraper":
        await self._setup()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._teardown()


# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Sliding-window token bucket. Thread-safe for asyncio single-threaded use."""

    def __init__(self, capacity: int, rate: float) -> None:
        """Args:
            capacity: Maximum number of tokens (= MAX_RPH).
            rate: Tokens added per second (= MAX_RPH / 3600).
        """
        import time

        self._capacity = float(capacity)
        self._rate = rate          # tokens / second
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        import asyncio
        import time

        while True:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Time until next token available
            wait_time = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait_time)
