# Phase 1 — Scraping Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.


**Goal:** Replace all `NotImplementedError` stubs with a fully working, TDD-verified scraper pipeline for WTTJ, Indeed, and LinkedIn.

**Date:** 2026-03-20
**Spec ref:** `docs/superpowers/specs/2026-03-20-phase1-scraping-design.md`

---

## Architecture Summary

A **fat base class** (`BaseScraper`) owns all shared infrastructure. Concrete scrapers implement only two methods: `_fetch_raw()` and `_parse_raw()`. The public entry point is `search()` (renamed from the stub's `scrape()`).

```
BaseScraper
├── _TokenBucket               — token bucket rate limiter (per instance)
├── _wait()                    — random delay + token acquisition
├── _with_retry(coro_fn)       — exponential backoff: 1s → 2s → 4s, max 3 attempts (callable, not bare coroutine)
├── _parse_salary(s)           — shared regex, returns (min, max) in EUR/year
├── _normalize(job)            — title case, scraped_at, is_remote, excluded kw filter
├── search(...)                — dedup + loop over _fetch_raw → _parse_raw → _normalize
├── _setup() / _teardown()     — Playwright lifecycle (non-abstract, default no-op)
├── _fetch_raw(...)            — ABSTRACT — returns list[Any]
└── _parse_raw(raw)            — ABSTRACT — returns Job

WTTJScraper     → XHR intercept via page.on("response")
IndeedScraper   → page.content() + BeautifulSoup CSS selectors
LinkedInScraper → playwright-stealth + cookie persistence + login fallback
```

**Constant:** `WORKING_DAYS_PER_YEAR = 220` (defined once in `base.py`, imported by tests)

---

## Tech Stack

| Concern | Library |
|---|---|
| Browser automation | `playwright` (already in pyproject.toml) |
| Stealth (LinkedIn) | `playwright-stealth` (add to pyproject.toml) |
| HTML parsing | `beautifulsoup4` + `lxml` (already in pyproject.toml) |
| Tests | `pytest` + `pytest-asyncio` (asyncio_mode = "auto") + `pytest-mock` |
| Type checking | `mypy` strict |
| Lint | `ruff` |

`playwright-stealth` must be added to `pyproject.toml` dependencies before Task 7.

---

## File Map

| File | Action | Task |
|---|---|---|
| `src/scrapers/exceptions.py` | CREATE | 1 |
| `src/scrapers/filters.py` | CREATE | 1 |
| `tests/test_scrapers.py` | REWRITE | 1–9 (incremental) |
| `src/scrapers/base.py` | REWRITE | 2–3 |
| `tests/fixtures/wttj/search_results.json` | CREATE | 4 |
| `tests/fixtures/wttj/job_no_salary.json` | CREATE | 4 |
| `tests/fixtures/wttj/job_expired.json` | CREATE | 4 |
| `src/scrapers/wttj.py` | REWRITE | 5 |
| `tests/fixtures/indeed/search_results.html` | CREATE | 6 |
| `tests/fixtures/indeed/job_daily_rate.html` | CREATE | 6 |
| `tests/fixtures/indeed/job_no_location.html` | CREATE | 6 |
| `src/scrapers/indeed.py` | REWRITE | 6 |
| `tests/fixtures/linkedin/search_results.html` | CREATE | 7 |
| `tests/fixtures/linkedin/job_detail.html` | CREATE | 7 |
| `src/scrapers/linkedin.py` | REWRITE | 7 |
| `pyproject.toml` | MODIFY (add playwright-stealth) | 7 |

---

## Task 1 — Exceptions + ScraperFilters

### Objective
Create `src/scrapers/exceptions.py` and `src/scrapers/filters.py`. Write and pass tests for both. These are pure data structures — no Playwright involved.

### Step 1.1 — Write failing tests

Add to `tests/test_scrapers.py`:

```python
"""Tests for scrapers — Phase 1."""

from dataclasses import fields

import pytest

from src.scrapers.exceptions import (
    AuthenticationError,
    ParseError,
    RateLimitError,
    ScraperError,
)
from src.scrapers.filters import ScraperFilters


# ---------------------------------------------------------------------------
# Task 1 — Exceptions
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_scraper_error_is_base(self) -> None:
        assert issubclass(RateLimitError, ScraperError)
        assert issubclass(AuthenticationError, ScraperError)
        assert issubclass(ParseError, ScraperError)

    def test_exceptions_are_exception_subclasses(self) -> None:
        assert issubclass(ScraperError, Exception)

    def test_exceptions_accept_message(self) -> None:
        err = RateLimitError("HTTP 429")
        assert str(err) == "HTTP 429"

        err2 = AuthenticationError("cookies expired")
        assert str(err2) == "cookies expired"

        err3 = ParseError("unexpected structure")
        assert str(err3) == "unexpected structure"


# ---------------------------------------------------------------------------
# Task 1 — ScraperFilters
# ---------------------------------------------------------------------------

class TestScraperFilters:
    def test_default_values(self) -> None:
        f = ScraperFilters()
        assert f.remote_only is True
        assert "CDI" in f.contract_types
        assert "Freelance" in f.contract_types
        assert "Contract" in f.contract_types
        assert f.min_salary is None

    def test_default_excluded_keywords(self) -> None:
        f = ScraperFilters()
        assert "junior" in f.excluded_keywords
        assert "stage" in f.excluded_keywords
        assert "internship" in f.excluded_keywords
        assert "stagiaire" in f.excluded_keywords
        assert "alternance" in f.excluded_keywords

    def test_contract_types_are_independent_instances(self) -> None:
        f1 = ScraperFilters()
        f2 = ScraperFilters()
        f1.contract_types.append("CDD")
        assert "CDD" not in f2.contract_types

    def test_custom_values(self) -> None:
        f = ScraperFilters(remote_only=False, min_salary=80000)
        assert f.remote_only is False
        assert f.min_salary == 80000

    def test_is_dataclass(self) -> None:
        field_names = {f.name for f in fields(ScraperFilters)}
        assert field_names == {"remote_only", "contract_types", "min_salary", "excluded_keywords"}
```

Run — expect collection errors (modules don't exist yet):

```bash
pytest tests/test_scrapers.py::TestExceptions tests/test_scrapers.py::TestScraperFilters -v
```

Expected output:
```
ERROR tests/test_scrapers.py - ModuleNotFoundError: No module named 'src.scrapers.exceptions'
```

### Step 1.2 — Implement `src/scrapers/exceptions.py`

```python
"""Custom exceptions for the scraper layer."""


class ScraperError(Exception):
    """Base class for all scraper errors."""


class RateLimitError(ScraperError):
    """Raised when the target site returns HTTP 429 or equivalent throttle signal."""


class AuthenticationError(ScraperError):
    """Raised when LinkedIn authentication fails, cookies are expired with no credentials,
    or a 2FA / CAPTCHA challenge is encountered."""


class ParseError(ScraperError):
    """Raised when expected markup or JSON structure is absent or malformed."""
```

### Step 1.3 — Implement `src/scrapers/filters.py`

```python
"""ScraperFilters dataclass — controls post-parse filtering."""

from dataclasses import dataclass, field


@dataclass
class ScraperFilters:
    """Parameters that control which jobs are kept after parsing.

    Attributes:
        remote_only: When True, only remote jobs are returned.
        contract_types: Accepted contract types (synced with profile.yaml).
        min_salary: Minimum annual salary in EUR. None = no filter.
        excluded_keywords: Jobs whose title or description contains any of these
            strings (case-insensitive) are silently dropped.
    """

    remote_only: bool = True
    contract_types: list[str] = field(
        default_factory=lambda: ["CDI", "Freelance", "Contract"]
    )
    min_salary: int | None = None
    excluded_keywords: list[str] = field(
        default_factory=lambda: ["junior", "stage", "internship", "stagiaire", "alternance"]
    )
```

### Step 1.4 — Run tests, expect green

```bash
pytest tests/test_scrapers.py::TestExceptions tests/test_scrapers.py::TestScraperFilters -v
```

Expected output:
```
tests/test_scrapers.py::TestExceptions::test_scraper_error_is_base PASSED
tests/test_scrapers.py::TestExceptions::test_exceptions_are_exception_subclasses PASSED
tests/test_scrapers.py::TestExceptions::test_exceptions_accept_message PASSED
tests/test_scrapers.py::TestScraperFilters::test_default_values PASSED
tests/test_scrapers.py::TestScraperFilters::test_default_excluded_keywords PASSED
tests/test_scrapers.py::TestScraperFilters::test_contract_types_are_independent_instances PASSED
tests/test_scrapers.py::TestScraperFilters::test_custom_values PASSED
tests/test_scrapers.py::TestScraperFilters::test_is_dataclass PASSED
8 passed in 0.XXs
```

### Step 1.5 — Commit

```
git add src/scrapers/exceptions.py src/scrapers/filters.py tests/test_scrapers.py
git commit -m "feat(scrapers): add ScraperFilters dataclass and exception hierarchy"
```

---

## Task 2 — BaseScraper: normalization + salary parsing

### Objective
Rewrite `src/scrapers/base.py`. Add `_parse_salary` (concrete, not abstract), `_normalize`, `WORKING_DAYS_PER_YEAR`, and the abstract `_fetch_raw`. Remove the old abstract `_parse_salary` from subclasses (it moves to `BaseScraper`). Tests cover all salary patterns and normalization rules.

### Step 2.1 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 2 — BaseScraper normalization + salary parsing
# ---------------------------------------------------------------------------

from src.scrapers.base import BaseScraper, WORKING_DAYS_PER_YEAR
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job


class _ConcreteScraper(BaseScraper):
    """Minimal concrete implementation for unit testing BaseScraper logic."""

    source = "test"
    MIN_DELAY = 0.0
    MAX_DELAY = 0.0
    MAX_RPH = 3600

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters | None,
        limit: int,
    ) -> list[object]:
        return []

    async def _parse_raw(self, raw: object) -> Job:
        raise NotImplementedError


class TestWorkingDaysConstant:
    def test_value(self) -> None:
        assert WORKING_DAYS_PER_YEAR == 220


class TestParseSalary:
    def setup_method(self) -> None:
        self.scraper = _ConcreteScraper()

    def test_annual_range_french_format(self) -> None:
        assert self.scraper._parse_salary("80 000 € - 100 000 €/an") == (80000, 100000)

    def test_annual_range_compact(self) -> None:
        assert self.scraper._parse_salary("80000-100000€/an") == (80000, 100000)

    def test_daily_rate(self) -> None:
        # 700 * 220 = 154000
        assert self.scraper._parse_salary("700€/jour") == (154000, 154000)

    def test_daily_rate_with_spaces(self) -> None:
        assert self.scraper._parse_salary("700 €/jour") == (154000, 154000)

    def test_single_annual_amount(self) -> None:
        assert self.scraper._parse_salary("80 000 €/an") == (80000, 80000)

    def test_selon_profil_returns_none(self) -> None:
        assert self.scraper._parse_salary("Selon profil") == (None, None)

    def test_empty_string_returns_none(self) -> None:
        assert self.scraper._parse_salary("") == (None, None)

    def test_k_notation(self) -> None:
        assert self.scraper._parse_salary("80k-100k €/an") == (80000, 100000)


class TestNormalize:
    def setup_method(self) -> None:
        self.scraper = _ConcreteScraper()
        self.filters = ScraperFilters()

    def _make_job(self, **kwargs: object) -> Job:
        defaults: dict[str, object] = {
            "title": "Senior Automation Engineer",
            "url": "https://example.com/job/1",
            "source": "test",
            "description": "Great remote position.",
            "location": "Remote",
            "salary_raw": None,
            "salary_min": None,
            "salary_max": None,
            "contract_type": "CDI",
        }
        defaults.update(kwargs)
        return Job(**defaults)  # type: ignore[arg-type]

    def test_title_is_title_cased(self) -> None:
        job = self._make_job(title="senior automation engineer")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.title == "Senior Automation Engineer"

    def test_title_is_stripped(self) -> None:
        job = self._make_job(title="  Senior Dev  ")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.title == "Senior Dev"

    def test_scraped_at_is_set(self) -> None:
        from datetime import timezone
        job = self._make_job()
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.scraped_at is not None
        assert result.scraped_at.tzinfo == timezone.utc

    def test_source_set_from_class_attribute(self) -> None:
        job = self._make_job(source="")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.source == "test"

    def test_is_remote_detected_in_location(self) -> None:
        job = self._make_job(location="Télétravail complet", description="Standard role.")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.is_remote is True

    def test_is_remote_detected_in_title(self) -> None:
        job = self._make_job(title="Remote Senior Engineer", location="Paris")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.is_remote is True

    def test_is_remote_detected_in_description(self) -> None:
        job = self._make_job(location="Paris", description="Poste en distanciel.")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.is_remote is True

    def test_is_remote_false_when_not_mentioned(self) -> None:
        job = self._make_job(location="Paris", description="On-site position.")
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.is_remote is False

    def test_excluded_keyword_in_title_returns_none(self) -> None:
        job = self._make_job(title="Junior Python Developer")
        result = self.scraper._normalize(job, self.filters)
        assert result is None

    def test_excluded_keyword_in_description_returns_none(self) -> None:
        job = self._make_job(description="This is a stage position.")
        result = self.scraper._normalize(job, self.filters)
        assert result is None

    def test_excluded_keyword_case_insensitive(self) -> None:
        job = self._make_job(title="JUNIOR Developer")
        result = self.scraper._normalize(job, self.filters)
        assert result is None

    def test_salary_parsed_when_raw_present_and_min_max_none(self) -> None:
        job = self._make_job(salary_raw="80 000 € - 100 000 €/an", salary_min=None, salary_max=None)
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.salary_min == 80000
        assert result.salary_max == 100000

    def test_salary_not_overwritten_when_already_set(self) -> None:
        # WTTJ provides structured salary — _normalize must not overwrite it
        job = self._make_job(salary_raw="80k-100k", salary_min=80000, salary_max=100000)
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.salary_min == 80000
        assert result.salary_max == 100000

    def test_no_filters_does_not_crash(self) -> None:
        job = self._make_job()
        result = self.scraper._normalize(job, filters=None)
        assert result is not None
```

Run — expect import errors from missing attributes:

```bash
pytest tests/test_scrapers.py::TestWorkingDaysConstant tests/test_scrapers.py::TestParseSalary tests/test_scrapers.py::TestNormalize -v
```

Expected output:
```
ERROR tests/test_scrapers.py - ImportError: cannot import name 'WORKING_DAYS_PER_YEAR' from 'src.scrapers.base'
```

### Step 2.2 — Rewrite `src/scrapers/base.py`

```python
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
```

### Step 2.3 — Run tests, expect green

```bash
pytest tests/test_scrapers.py::TestWorkingDaysConstant tests/test_scrapers.py::TestParseSalary tests/test_scrapers.py::TestNormalize -v
```

Expected output:
```
tests/test_scrapers.py::TestWorkingDaysConstant::test_value PASSED
tests/test_scrapers.py::TestParseSalary::test_annual_range_french_format PASSED
tests/test_scrapers.py::TestParseSalary::test_annual_range_compact PASSED
tests/test_scrapers.py::TestParseSalary::test_daily_rate PASSED
tests/test_scrapers.py::TestParseSalary::test_daily_rate_with_spaces PASSED
tests/test_scrapers.py::TestParseSalary::test_single_annual_amount PASSED
tests/test_scrapers.py::TestParseSalary::test_selon_profil_returns_none PASSED
tests/test_scrapers.py::TestParseSalary::test_empty_string_returns_none PASSED
tests/test_scrapers.py::TestParseSalary::test_k_notation PASSED
tests/test_scrapers.py::TestNormalize::test_title_is_title_cased PASSED
... (all 15 normalize tests) PASSED
24 passed in 0.XXs
```

### Step 2.4 — Commit

```
git add src/scrapers/base.py tests/test_scrapers.py
git commit -m "feat(scrapers): implement BaseScraper normalization and salary parsing"
```

---

## Task 3 — BaseScraper: deduplication + search() wiring

### Objective
Test and validate that `search()` correctly deduplicates within a batch and against `seen_urls`, and that `None` results from `_normalize` are dropped. These tests use `_ConcreteScraper` (already defined in test file) with a controlled `_fetch_raw` override.

### Step 3.1 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 3 — BaseScraper deduplication + search() wiring
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch


class _DupScraper(_ConcreteScraper):
    """Scraper that returns a controlled set of raw items for dedup testing."""

    def __init__(self, raw_items: list[Job]) -> None:
        super().__init__()
        self._raw_items = raw_items

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters | None,
        limit: int,
    ) -> list[object]:
        return list(self._raw_items)  # type: ignore[return-value]

    async def _parse_raw(self, raw: object) -> Job:
        assert isinstance(raw, Job)
        return raw


def _job(url: str, title: str = "Senior Dev", description: str = "Good remote job.") -> Job:
    return Job(
        title=title,
        url=url,
        source="test",
        description=description,
        location="Remote",
    )


class TestSearchDeduplication:
    @pytest.mark.asyncio
    async def test_in_batch_dedup_drops_second_occurrence(self) -> None:
        j = _job("https://example.com/job/1")
        scraper = _DupScraper([j, j])
        results = await scraper.search(keywords=["dev"])
        urls = [r.url for r in results]
        assert urls.count("https://example.com/job/1") == 1

    @pytest.mark.asyncio
    async def test_seen_urls_param_drops_known_url(self) -> None:
        j = _job("https://example.com/job/99")
        scraper = _DupScraper([j])
        results = await scraper.search(
            keywords=["dev"],
            seen_urls={"https://example.com/job/99"},
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_normalize_none_dropped(self) -> None:
        j = _job("https://example.com/job/2", title="Junior Developer")  # excluded keyword
        scraper = _DupScraper([j])
        results = await scraper.search(keywords=["dev"])
        assert results == []

    @pytest.mark.asyncio
    async def test_limit_respected(self) -> None:
        jobs = [_job(f"https://example.com/job/{i}") for i in range(10)]
        scraper = _DupScraper(jobs)
        results = await scraper.search(keywords=["dev"], limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_returns_list_of_jobs(self) -> None:
        j = _job("https://example.com/job/100")
        scraper = _DupScraper([j])
        results = await scraper.search(keywords=["dev"])
        assert isinstance(results, list)
        assert all(isinstance(r, Job) for r in results)
```

Run — expect green immediately (search logic was implemented in Task 2):

```bash
pytest tests/test_scrapers.py::TestSearchDeduplication -v
```

Expected output:
```
tests/test_scrapers.py::TestSearchDeduplication::test_in_batch_dedup_drops_second_occurrence PASSED
tests/test_scrapers.py::TestSearchDeduplication::test_seen_urls_param_drops_known_url PASSED
tests/test_scrapers.py::TestSearchDeduplication::test_normalize_none_dropped PASSED
tests/test_scrapers.py::TestSearchDeduplication::test_limit_respected PASSED
tests/test_scrapers.py::TestSearchDeduplication::test_search_returns_list_of_jobs PASSED
5 passed in 0.XXs
```

### Step 3.2 — Commit

```
git add tests/test_scrapers.py
git commit -m "test(scrapers): add deduplication and search() wiring tests"
```

---

## Task 4 — WTTJ Fixtures

### Objective
Create hand-written JSON fixtures that represent real WTTJ XHR API responses. No tests in this task. These fixtures are consumed in Task 5.

### Step 4.1 — Create `tests/fixtures/wttj/search_results.json`

This file simulates the JSON payload captured from `*/api/*jobs*` XHR intercepts. It contains a `jobs` array with 3 complete offers. The structure mirrors the actual WTTJ API response shape.

```json
{
  "jobs": [
    {
      "uuid": "wttj-job-001",
      "name": "Senior Automation Engineer",
      "slug": "senior-automation-engineer",
      "contract_type": {"en": "Full-Time", "fr": "CDI"},
      "salary": {"min": 80000, "max": 100000, "currency": "EUR", "period": "annual"},
      "remote": "fulltime",
      "published_at": "2026-03-15T10:00:00Z",
      "company": {"name": "Acme Corp", "slug": "acme-corp"},
      "location": {"city": "Paris", "country_code": "FR"},
      "description": "We are looking for a Senior Automation Engineer with experience in n8n and Python.",
      "profile": "Strong Python skills required.",
      "website_url": "https://www.welcometothejungle.com/fr/companies/acme-corp/jobs/senior-automation-engineer"
    },
    {
      "uuid": "wttj-job-002",
      "name": "RevOps Lead",
      "slug": "revops-lead",
      "contract_type": {"en": "Full-Time", "fr": "CDI"},
      "salary": {"min": 70000, "max": 90000, "currency": "EUR", "period": "annual"},
      "remote": "fulltime",
      "published_at": "2026-03-14T09:00:00Z",
      "company": {"name": "TechStart", "slug": "techstart"},
      "location": {"city": "Lyon", "country_code": "FR"},
      "description": "RevOps Lead to scale our go-to-market engine. Full remote.",
      "profile": "HubSpot and Salesforce expertise.",
      "website_url": "https://www.welcometothejungle.com/fr/companies/techstart/jobs/revops-lead"
    },
    {
      "uuid": "wttj-job-003",
      "name": "AI Integration Consultant",
      "slug": "ai-integration-consultant",
      "contract_type": {"en": "Freelance", "fr": "Freelance"},
      "salary": {"min": 120000, "max": 150000, "currency": "EUR", "period": "annual"},
      "remote": "fulltime",
      "published_at": "2026-03-13T08:00:00Z",
      "company": {"name": "AI Ventures", "slug": "ai-ventures"},
      "location": {"city": null, "country_code": "FR"},
      "description": "AI integration consultant to help clients automate workflows. Distanciel.",
      "profile": "Claude and OpenAI API experience preferred.",
      "website_url": "https://www.welcometothejungle.com/fr/companies/ai-ventures/jobs/ai-integration-consultant"
    }
  ],
  "meta": {"total": 3, "page": 1, "per_page": 25}
}
```

### Step 4.2 — Create `tests/fixtures/wttj/job_no_salary.json`

```json
{
  "jobs": [
    {
      "uuid": "wttj-job-004",
      "name": "Data Operations Manager",
      "slug": "data-operations-manager",
      "contract_type": {"en": "Full-Time", "fr": "CDI"},
      "salary": null,
      "remote": "fulltime",
      "published_at": "2026-03-12T10:00:00Z",
      "company": {"name": "DataCo", "slug": "dataco"},
      "location": {"city": "Remote", "country_code": "FR"},
      "description": "Manage data operations in a fully remote team.",
      "profile": "Experience with dbt and BigQuery.",
      "website_url": "https://www.welcometothejungle.com/fr/companies/dataco/jobs/data-operations-manager"
    }
  ],
  "meta": {"total": 1, "page": 1, "per_page": 25}
}
```

### Step 4.3 — Create `tests/fixtures/wttj/job_expired.json`

```json
{
  "jobs": [
    {
      "uuid": "wttj-job-005",
      "name": "Automation Engineer",
      "slug": "automation-engineer-old",
      "contract_type": {"en": "Full-Time", "fr": "CDI"},
      "salary": {"min": 60000, "max": 80000, "currency": "EUR", "period": "annual"},
      "remote": "fulltime",
      "published_at": "2025-01-01T10:00:00Z",
      "status": "expired",
      "company": {"name": "OldCo", "slug": "oldco"},
      "location": {"city": "Paris", "country_code": "FR"},
      "description": "Expired listing — should be skipped.",
      "profile": "",
      "website_url": "https://www.welcometothejungle.com/fr/companies/oldco/jobs/automation-engineer-old"
    }
  ],
  "meta": {"total": 1, "page": 1, "per_page": 25}
}
```

### Step 4.4 — Create directory marker

Ensure `tests/fixtures/wttj/`, `tests/fixtures/indeed/`, and `tests/fixtures/linkedin/` directories exist. No tests to run in this task.

### Step 4.5 — Commit

```
git add tests/fixtures/
git commit -m "test(scrapers): add WTTJ fixture JSON files"
```

---

## Task 5 — WTTJScraper Implementation

### Objective
Rewrite `src/scrapers/wttj.py`. Tests mock Playwright's `page.on("response")` mechanism using `AsyncMock`. Zero network calls.

### Step 5.1 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 5 — WTTJScraper
# ---------------------------------------------------------------------------

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.scrapers.wttj import WTTJScraper

WTTJ_FIXTURES = Path(__file__).parent / "fixtures" / "wttj"


def _load_wttj_fixture(filename: str) -> dict:  # type: ignore[type-arg]
    return json.loads((WTTJ_FIXTURES / filename).read_text())


class TestWTTJParseRaw:
    """Unit tests for WTTJScraper._parse_raw — no Playwright required."""

    def setup_method(self) -> None:
        self.scraper = WTTJScraper.__new__(WTTJScraper)
        self.scraper.headless = True
        from src.scrapers.base import _TokenBucket
        self.scraper._token_bucket = _TokenBucket(120, 120 / 3600)

    @pytest.mark.asyncio
    async def test_parse_complete_job(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")
        raw = fixture["jobs"][0]
        job = await self.scraper._parse_raw(raw)
        assert job.title == "Senior Automation Engineer"
        assert job.url == "https://www.welcometothejungle.com/fr/companies/acme-corp/jobs/senior-automation-engineer"
        assert job.source == "wttj"
        assert job.salary_min == 80000
        assert job.salary_max == 100000
        assert job.contract_type == "CDI"
        assert "automation" in job.description.lower()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_parse_missing_salary(self) -> None:
        fixture = _load_wttj_fixture("job_no_salary.json")
        raw = fixture["jobs"][0]
        job = await self.scraper._parse_raw(raw)
        assert job.salary_min is None
        assert job.salary_max is None

    @pytest.mark.asyncio
    async def test_parse_salary_set_directly_not_via_raw_string(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")
        raw = fixture["jobs"][0]
        job = await self.scraper._parse_raw(raw)
        # salary_min/max come from structured JSON, not salary_raw parsing
        assert job.salary_min == 80000
        assert job.salary_max == 100000

    @pytest.mark.asyncio
    async def test_parse_remote_detected(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")
        raw = fixture["jobs"][1]  # RevOps Lead — "Full remote" in description
        job = await self.scraper._parse_raw(raw)
        # is_remote is set by _normalize, not _parse_raw; just assert no crash
        assert job.url is not None

    @pytest.mark.asyncio
    async def test_expired_job_has_no_special_handling_in_parse_raw(self) -> None:
        # _parse_raw must not crash on expired jobs — filtering is done upstream
        fixture = _load_wttj_fixture("job_expired.json")
        raw = fixture["jobs"][0]
        job = await self.scraper._parse_raw(raw)
        assert job.title == "Automation Engineer"


class TestWTTJSearch:
    """Integration tests for WTTJScraper.search() — mocked Playwright."""

    @pytest.mark.asyncio
    async def test_search_returns_list_of_jobs(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return fixture["jobs"]

        scraper = WTTJScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert len(results) == 3
        assert all(isinstance(j, Job) for j in results)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return fixture["jobs"]

        scraper = WTTJScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"], limit=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_excluded_keyword_dropped(self) -> None:
        raw_junior = {
            "uuid": "x",
            "name": "Junior Automation Engineer",
            "contract_type": {"fr": "CDI"},
            "salary": None,
            "remote": "fulltime",
            "company": {"name": "Co"},
            "location": {"city": "Paris"},
            "description": "Junior role.",
            "profile": "",
            "website_url": "https://www.welcometothejungle.com/fr/companies/co/jobs/x",
        }

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [raw_junior]

        scraper = WTTJScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplication_in_batch(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")
        raw = fixture["jobs"][0]

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [raw, raw]  # same item twice

        scraper = WTTJScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_deduplication_seen_urls(self) -> None:
        fixture = _load_wttj_fixture("search_results.json")
        raw = fixture["jobs"][0]
        url = raw["website_url"]

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [raw]

        scraper = WTTJScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"], seen_urls={url})
        assert results == []
```

Run — expect failures from missing implementation:

```bash
pytest tests/test_scrapers.py::TestWTTJParseRaw tests/test_scrapers.py::TestWTTJSearch -v
```

Expected output:
```
FAILED ... - NotImplementedError (from stub _parse_raw / _fetch_raw)
```

### Step 5.2 — Implement `src/scrapers/wttj.py`

```python
"""Welcome to the Jungle scraper — Playwright XHR intercept."""

from __future__ import annotations

import json
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
    ) -> list[Any]:
        assert self._browser is not None, "_setup() must be called first"

        collected: list[dict[str, Any]] = []
        page = await self._browser.new_page()

        async def _handle_response(response: Response) -> None:
            if "/api/" in response.url and "jobs" in response.url:
                try:
                    data = await response.json()
                    if isinstance(data, dict) and "jobs" in data:
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

    async def _parse_raw(self, raw: Any) -> Job:
        """Parse a WTTJ API job dict into a Job instance.

        WTTJ provides structured salary data — salary_min/max are set directly
        from JSON fields. _normalize() will not call _parse_salary() for these jobs.
        """
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        try:
            title: str = raw.get("name") or ""
            url: str = raw.get("website_url") or ""

            if not title or not url:
                raise ParseError("Missing required fields 'name' or 'website_url'")

            salary_data = raw.get("salary")
            salary_min: int | None = None
            salary_max: int | None = None
            salary_raw_str: str | None = None

            if isinstance(salary_data, dict):
                raw_min = salary_data.get("min")
                raw_max = salary_data.get("max")
                if raw_min is not None:
                    salary_min = int(raw_min)
                if raw_max is not None:
                    salary_max = int(raw_max)
                if salary_min is not None or salary_max is not None:
                    salary_raw_str = f"{salary_min}-{salary_max} EUR/an"

            contract_raw = raw.get("contract_type") or {}
            contract_type: str | None = (
                contract_raw.get("fr") or contract_raw.get("en") or None
            )

            location_data = raw.get("location") or {}
            city = location_data.get("city") or ""
            country = location_data.get("country_code") or ""
            location_str = ", ".join(filter(None, [city, country])) or None

            description = " ".join(
                filter(None, [raw.get("description") or "", raw.get("profile") or ""])
            ) or None

            return Job(
                title=title,
                url=url,
                source=self.source,
                description=description,
                location=location_str,
                salary_raw=salary_raw_str,
                salary_min=salary_min,
                salary_max=salary_max,
                contract_type=contract_type,
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse WTTJ job: {exc}") from exc
```

### Step 5.3 — Run tests, expect green

```bash
pytest tests/test_scrapers.py::TestWTTJParseRaw tests/test_scrapers.py::TestWTTJSearch -v
```

Expected output:
```
tests/test_scrapers.py::TestWTTJParseRaw::test_parse_complete_job PASSED
tests/test_scrapers.py::TestWTTJParseRaw::test_parse_missing_salary PASSED
tests/test_scrapers.py::TestWTTJParseRaw::test_parse_salary_set_directly_not_via_raw_string PASSED
tests/test_scrapers.py::TestWTTJParseRaw::test_parse_remote_detected PASSED
tests/test_scrapers.py::TestWTTJParseRaw::test_expired_job_has_no_special_handling_in_parse_raw PASSED
tests/test_scrapers.py::TestWTTJSearch::test_search_returns_list_of_jobs PASSED
tests/test_scrapers.py::TestWTTJSearch::test_search_respects_limit PASSED
tests/test_scrapers.py::TestWTTJSearch::test_excluded_keyword_dropped PASSED
tests/test_scrapers.py::TestWTTJSearch::test_deduplication_in_batch PASSED
tests/test_scrapers.py::TestWTTJSearch::test_deduplication_seen_urls PASSED
10 passed in 0.XXs
```

### Step 5.4 — Commit

```
git add src/scrapers/wttj.py tests/test_scrapers.py
git commit -m "feat(scrapers): implement WTTJScraper with XHR intercept"
```

---

## Task 6 — Indeed Fixtures + IndeedScraper

### Objective
Create HTML fixtures and implement `IndeedScraper`. `_parse_raw` receives a `bs4.Tag` (not a dict). Tests use BeautifulSoup directly — no Playwright required for unit tests.

### Step 6.1 — Create `tests/fixtures/indeed/search_results.html`

This simulates the `page.content()` output containing three `.job_seen_beacon` cards.

```html
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Indeed Jobs</title></head>
<body>
  <div id="mosaic-provider-jobcards">

    <div class="job_seen_beacon">
      <h2 class="jobTitle"><a class="jcs-JobTitle" href="/pagead/clk?job=senior-revops-engineer&from=jasx" data-jk="abc123">
        <span title="Senior RevOps Engineer">Senior RevOps Engineer</span>
      </a></h2>
      <span class="companyName">Acme Corp</span>
      <div class="companyLocation">Remote</div>
      <div class="salary-snippet-container">
        <div class="metadata salary-snippet">
          <span>80 000 € - 100 000 € par an</span>
        </div>
      </div>
      <div class="job-snippet">
        <ul>
          <li>CDI</li>
          <li>Télétravail</li>
        </ul>
      </div>
      <div class="result-footer">
        <a class="jcs-JobTitle" href="/pagead/clk?job=senior-revops-engineer&from=jasx" data-jk="abc123">Senior RevOps Engineer</a>
      </div>
    </div>

    <div class="job_seen_beacon">
      <h2 class="jobTitle"><a class="jcs-JobTitle" href="/pagead/clk?job=automation-lead&from=jasx" data-jk="def456">
        <span title="Automation Lead">Automation Lead</span>
      </a></h2>
      <span class="companyName">TechStart SAS</span>
      <div class="companyLocation">France entière (Télétravail)</div>
      <div class="salary-snippet-container">
        <div class="metadata salary-snippet">
          <span>60 000 € - 80 000 € par an</span>
        </div>
      </div>
      <div class="job-snippet">
        <ul>
          <li>CDI</li>
          <li>Distanciel complet</li>
        </ul>
      </div>
    </div>

    <div class="job_seen_beacon">
      <h2 class="jobTitle"><a class="jcs-JobTitle" href="/pagead/clk?job=ops-consultant&from=jasx" data-jk="ghi789">
        <span title="Ops Consultant Freelance">Ops Consultant Freelance</span>
      </a></h2>
      <span class="companyName">Consulting Inc</span>
      <div class="companyLocation">Remote / Paris</div>
      <div class="salary-snippet-container">
        <div class="metadata salary-snippet">
          <span>500 € - 700 €/jour</span>
        </div>
      </div>
      <div class="job-snippet">
        <ul>
          <li>Freelance</li>
        </ul>
      </div>
    </div>

  </div>
</body>
</html>
```

### Step 6.2 — Create `tests/fixtures/indeed/job_daily_rate.html`

```html
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body>
  <div class="job_seen_beacon">
    <h2 class="jobTitle"><a class="jcs-JobTitle" href="/pagead/clk?job=freelance-dev&from=jasx" data-jk="day001">
      <span title="Senior Freelance Developer">Senior Freelance Developer</span>
    </a></h2>
    <span class="companyName">Freelance Platform</span>
    <div class="companyLocation">Remote</div>
    <div class="salary-snippet-container">
      <div class="metadata salary-snippet">
        <span>700€/jour</span>
      </div>
    </div>
    <div class="job-snippet"><ul><li>Freelance</li></ul></div>
  </div>
</body>
</html>
```

### Step 6.3 — Create `tests/fixtures/indeed/job_no_location.html`

```html
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body>
  <div class="job_seen_beacon">
    <h2 class="jobTitle"><a class="jcs-JobTitle" href="/pagead/clk?job=remote-engineer&from=jasx" data-jk="noloc01">
      <span title="Remote Software Engineer">Remote Software Engineer</span>
    </a></h2>
    <span class="companyName">Invisible Corp</span>
    <div class="salary-snippet-container">
      <div class="metadata salary-snippet">
        <span>Selon profil</span>
      </div>
    </div>
    <div class="job-snippet"><ul><li>CDI</li></ul></div>
  </div>
</body>
</html>
```

### Step 6.4 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 6 — IndeedScraper
# ---------------------------------------------------------------------------

from bs4 import BeautifulSoup, Tag

from src.scrapers.indeed import IndeedScraper

INDEED_FIXTURES = Path(__file__).parent / "fixtures" / "indeed"


def _load_indeed_cards(filename: str) -> list[Tag]:
    html = (INDEED_FIXTURES / filename).read_text()
    soup = BeautifulSoup(html, "lxml")
    return soup.select(".job_seen_beacon")


class TestIndeedParseRaw:
    def setup_method(self) -> None:
        self.scraper = IndeedScraper.__new__(IndeedScraper)
        self.scraper.headless = True
        from src.scrapers.base import _TokenBucket
        self.scraper._token_bucket = _TokenBucket(60, 60 / 3600)

    @pytest.mark.asyncio
    async def test_parse_complete_job(self) -> None:
        cards = _load_indeed_cards("search_results.html")
        job = await self.scraper._parse_raw(cards[0])
        assert job.title == "Senior RevOps Engineer"  # raw title — _normalize not called here
        assert "abc123" in job.url
        assert job.source == "indeed"
        assert job.salary_raw == "80 000 € - 100 000 € par an"

    @pytest.mark.asyncio
    async def test_parse_missing_salary(self) -> None:
        cards = _load_indeed_cards("job_no_location.html")
        job = await self.scraper._parse_raw(cards[0])
        assert job.salary_raw == "Selon profil"
        assert job.salary_min is None
        assert job.salary_max is None

    @pytest.mark.asyncio
    async def test_parse_no_location(self) -> None:
        cards = _load_indeed_cards("job_no_location.html")
        job = await self.scraper._parse_raw(cards[0])
        assert job.location is None or job.location == ""

    @pytest.mark.asyncio
    async def test_parse_daily_rate_salary_raw_preserved(self) -> None:
        # _parse_raw stores salary_raw; _normalize calls _parse_salary
        cards = _load_indeed_cards("job_daily_rate.html")
        job = await self.scraper._parse_raw(cards[0])
        assert "700" in (job.salary_raw or "")

    @pytest.mark.asyncio
    async def test_parse_remote_keyword_in_location(self) -> None:
        cards = _load_indeed_cards("search_results.html")
        job = await self.scraper._parse_raw(cards[1])  # "France entière (Télétravail)"
        assert job.location is not None


class TestIndeedSearch:
    @pytest.mark.asyncio
    async def test_search_returns_list_of_jobs(self) -> None:
        cards = _load_indeed_cards("search_results.html")

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return cards

        scraper = IndeedScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["revops"])
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_excluded_keyword_dropped(self) -> None:
        html = """
        <div class="job_seen_beacon">
          <h2 class="jobTitle"><a data-jk="j1" href="/pagead/clk?job=j1">
            <span title="Junior Developer">Junior Developer</span>
          </a></h2>
          <span class="companyName">Co</span>
          <div class="companyLocation">Remote</div>
          <div class="job-snippet"><ul><li>CDI</li></ul></div>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".job_seen_beacon")

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return cards

        scraper = IndeedScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["dev"])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplication_in_batch(self) -> None:
        cards = _load_indeed_cards("search_results.html")
        card = cards[0]

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [card, card]

        scraper = IndeedScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["revops"])
        assert len(results) == 1
```

Run — expect failures:

```bash
pytest tests/test_scrapers.py::TestIndeedParseRaw tests/test_scrapers.py::TestIndeedSearch -v
```

### Step 6.5 — Implement `src/scrapers/indeed.py`

```python
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

logger = logging.getLogger(__name__)

_INDEED_BASE_URL = "https://fr.indeed.com/jobs"
# Remote filter param for Indeed France
_REMOTE_PARAM = "032b3"


class IndeedScraper(BaseScraper):
    """Scrape Indeed France job listings.

    No authentication required. Renders the page with Playwright then
    parses the HTML with BeautifulSoup.

    Usage::

        async with IndeedScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "indeed"
    MIN_DELAY = 2.0
    MAX_DELAY = 4.0
    MAX_RPH = 60

    def __init__(self, headless: bool = True) -> None:
        super().__init__(headless=headless)
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

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
    ) -> list[Any]:
        assert self._browser is not None, "_setup() must be called first"

        all_cards: list[Tag] = []
        page = await self._browser.new_page()
        query = quote_plus(" ".join(keywords))
        start = 0

        try:
            while len(all_cards) < limit:
                url = f"{_INDEED_BASE_URL}?q={query}&remotejob={_REMOTE_PARAM}&start={start}"
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
            job_key = link_el["data-jk"] if link_el else ""  # type: ignore[index]
            href = link_el.get("href", "") if link_el else ""  # type: ignore[union-attr]
            url = f"https://fr.indeed.com{href}" if href else f"https://fr.indeed.com/viewjob?jk={job_key}"

            if not title or not url:
                raise ParseError("Missing title or URL in Indeed card")

            location_el = raw.select_one(".companyLocation")
            location_str: str | None = location_el.get_text(strip=True) if location_el else None

            salary_el = raw.select_one(".salary-snippet")
            salary_raw_str: str | None = salary_el.get_text(strip=True) if salary_el else None

            snippet_el = raw.select_one(".job-snippet")
            description: str | None = snippet_el.get_text(separator=" ", strip=True) if snippet_el else None

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
```

### Step 6.6 — Run tests, expect green

```bash
pytest tests/test_scrapers.py::TestIndeedParseRaw tests/test_scrapers.py::TestIndeedSearch -v
```

Expected output:
```
tests/test_scrapers.py::TestIndeedParseRaw::test_parse_complete_job PASSED
tests/test_scrapers.py::TestIndeedParseRaw::test_parse_missing_salary PASSED
tests/test_scrapers.py::TestIndeedParseRaw::test_parse_no_location PASSED
tests/test_scrapers.py::TestIndeedParseRaw::test_parse_daily_rate_salary_raw_preserved PASSED
tests/test_scrapers.py::TestIndeedParseRaw::test_parse_remote_keyword_in_location PASSED
tests/test_scrapers.py::TestIndeedSearch::test_search_returns_list_of_jobs PASSED
tests/test_scrapers.py::TestIndeedSearch::test_excluded_keyword_dropped PASSED
tests/test_scrapers.py::TestIndeedSearch::test_deduplication_in_batch PASSED
8 passed in 0.XXs
```

### Step 6.7 — Commit

```
git add src/scrapers/indeed.py tests/test_scrapers.py tests/fixtures/indeed/
git commit -m "feat(scrapers): implement IndeedScraper with BeautifulSoup parsing"
```

---

## Task 7 — LinkedIn Fixtures + LinkedInScraper + Auth

### Objective
Add `playwright-stealth` to `pyproject.toml`, create HTML fixtures, implement `LinkedInScraper` with cookie persistence and graceful auth failures. Tests cover three auth scenarios without network calls.

### Step 7.1 — Update `pyproject.toml`

Add `"playwright-stealth>=0.0.28"` to the `dependencies` list, after the `playwright` entry. Then run:

```bash
pip install -e ".[dev]"
```

### Step 7.2 — Create `tests/fixtures/linkedin/search_results.html`

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>LinkedIn Jobs</title></head>
<body>
  <nav class="global-nav" aria-label="Primary Navigation"></nav>
  <ul class="jobs-search__results-list">
    <li class="jobs-search-results__list-item">
      <div class="base-card">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/1111111111/">
          Senior Automation Engineer
        </a>
        <h3 class="base-search-card__title">Senior Automation Engineer</h3>
        <h4 class="base-search-card__subtitle">Acme Corp</h4>
        <span class="job-search-card__location">Paris, Île-de-France, France (Remote)</span>
      </div>
    </li>
    <li class="jobs-search-results__list-item">
      <div class="base-card">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/2222222222/">
          RevOps Manager
        </a>
        <h3 class="base-search-card__title">RevOps Manager</h3>
        <h4 class="base-search-card__subtitle">TechStart</h4>
        <span class="job-search-card__location">France (Télétravail)</span>
      </div>
    </li>
    <li class="jobs-search-results__list-item">
      <div class="base-card">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3333333333/">
          AI Integration Lead
        </a>
        <h3 class="base-search-card__title">AI Integration Lead</h3>
        <h4 class="base-search-card__subtitle">AI Ventures</h4>
        <span class="job-search-card__location">Remote</span>
      </div>
    </li>
  </ul>
</body>
</html>
```

### Step 7.3 — Create `tests/fixtures/linkedin/job_detail.html`

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body>
  <nav class="global-nav" aria-label="Primary Navigation"></nav>
  <div class="jobs-unified-top-card">
    <h1 class="t-24 t-bold">Senior Automation Engineer</h1>
    <span class="jobs-unified-top-card__bullet">CDI</span>
    <span class="jobs-unified-top-card__bullet">Paris, France · Remote</span>
    <div class="jobs-unified-top-card__job-insight">
      <span>80 000 € - 100 000 €/an</span>
    </div>
  </div>
  <div class="jobs-description">
    <div class="jobs-description__content jobs-description-content">
      <div class="jobs-description-content__text">
        <p>We are seeking an experienced Automation Engineer with strong Python and n8n skills.</p>
        <p>Full remote position. CDI contract.</p>
      </div>
    </div>
  </div>
</body>
</html>
```

### Step 7.4 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 7 — LinkedInScraper
# ---------------------------------------------------------------------------

from bs4 import BeautifulSoup

from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.exceptions import AuthenticationError

LINKEDIN_FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def _load_linkedin_html(filename: str) -> str:
    return (LINKEDIN_FIXTURES / filename).read_text()


class TestLinkedInParseRaw:
    def setup_method(self) -> None:
        self.scraper = LinkedInScraper.__new__(LinkedInScraper)
        self.scraper.headless = True
        from src.scrapers.base import _TokenBucket
        self.scraper._token_bucket = _TokenBucket(30, 30 / 3600)

    @pytest.mark.asyncio
    async def test_parse_complete_job(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        raw = {
            "url": "https://www.linkedin.com/jobs/view/1111111111/",
            "detail_soup": soup,
        }
        job = await self.scraper._parse_raw(raw)
        assert "automation" in job.title.lower() or "Automation" in job.title
        assert job.url == "https://www.linkedin.com/jobs/view/1111111111/"
        assert job.source == "linkedin"
        assert job.salary_raw is not None
        assert "automation" in (job.description or "").lower()

    @pytest.mark.asyncio
    async def test_parse_missing_salary(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        # Remove salary node
        for el in soup.select(".jobs-unified-top-card__job-insight"):
            el.decompose()
        raw = {
            "url": "https://www.linkedin.com/jobs/view/1111111111/",
            "detail_soup": soup,
        }
        job = await self.scraper._parse_raw(raw)
        assert job.salary_raw is None
        assert job.salary_min is None
        assert job.salary_max is None

    @pytest.mark.asyncio
    async def test_parse_remote_detected(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        raw = {
            "url": "https://www.linkedin.com/jobs/view/1111111111/",
            "detail_soup": soup,
        }
        job = await self.scraper._parse_raw(raw)
        # is_remote is set by _normalize; _parse_raw just populates fields
        assert job.location is not None  # should contain "Remote"


class TestLinkedInAuth:
    @pytest.mark.asyncio
    async def test_missing_credentials_raises_authentication_error(self) -> None:
        scraper = LinkedInScraper()
        mock_page = AsyncMock()
        # Simulate not authenticated (nav element absent)
        mock_page.query_selector = AsyncMock(return_value=None)

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(scraper, "_is_authenticated", return_value=False):
                with patch.object(scraper, "_has_credentials", return_value=False):
                    with pytest.raises(AuthenticationError):
                        await scraper._authenticate(mock_page)

    @pytest.mark.asyncio
    async def test_cookie_load_skips_login(self) -> None:
        scraper = LinkedInScraper()
        mock_page = AsyncMock()

        with patch.object(scraper, "_is_authenticated", return_value=True):
            # Should return without raising — cookies valid
            await scraper._authenticate(mock_page)

    @pytest.mark.asyncio
    async def test_2fa_challenge_raises_authentication_error(self) -> None:
        scraper = LinkedInScraper()
        mock_page = AsyncMock()

        with patch.object(scraper, "_is_authenticated", return_value=False):
            with patch.object(scraper, "_has_credentials", return_value=True):
                with patch.object(scraper, "_run_login", side_effect=AuthenticationError("2FA challenge")):
                    with pytest.raises(AuthenticationError, match="2FA"):
                        await scraper._authenticate(mock_page)


class TestLinkedInSearch:
    @pytest.mark.asyncio
    async def test_search_returns_list_of_jobs(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")

        fake_raws = [
            {"url": f"https://www.linkedin.com/jobs/view/{i}/", "detail_soup": soup}
            for i in range(3)
        ]

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return fake_raws

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert len(results) == 3
        assert all(isinstance(j, Job) for j in results)

    @pytest.mark.asyncio
    async def test_excluded_keyword_dropped(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        # Modify title in soup to contain excluded keyword
        title_el = soup.select_one("h1")
        if title_el:
            title_el.string = "Junior Automation Engineer"

        fake_raws = [{"url": "https://www.linkedin.com/jobs/view/99/", "detail_soup": soup}]

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return fake_raws

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplication_in_batch(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        raw = {"url": "https://www.linkedin.com/jobs/view/1111111111/", "detail_soup": soup}

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [raw, raw]

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(keywords=["automation"])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_deduplication_seen_urls(self) -> None:
        html = _load_linkedin_html("job_detail.html")
        soup = BeautifulSoup(html, "lxml")
        raw = {"url": "https://www.linkedin.com/jobs/view/1111111111/", "detail_soup": soup}

        async def _mock_fetch_raw(keywords, location, filters, limit):  # type: ignore[no-untyped-def]
            return [raw]

        scraper = LinkedInScraper()
        with patch.object(scraper, "_fetch_raw", side_effect=_mock_fetch_raw):
            results = await scraper.search(
                keywords=["automation"],
                seen_urls={"https://www.linkedin.com/jobs/view/1111111111/"},
            )
        assert results == []
```

Run — expect failures:

```bash
pytest tests/test_scrapers.py::TestLinkedInParseRaw tests/test_scrapers.py::TestLinkedInAuth tests/test_scrapers.py::TestLinkedInSearch -v
```

### Step 7.5 — Implement `src/scrapers/linkedin.py`

```python
"""LinkedIn Jobs scraper — playwright-stealth + persistent cookies."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
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

            contract_el = soup.select_one(".jobs-unified-top-card__bullet ~ .jobs-unified-top-card__bullet")
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
```

### Step 7.6 — Run tests, expect green

```bash
pytest tests/test_scrapers.py::TestLinkedInParseRaw tests/test_scrapers.py::TestLinkedInAuth tests/test_scrapers.py::TestLinkedInSearch -v
```

Expected output:
```
tests/test_scrapers.py::TestLinkedInParseRaw::test_parse_complete_job PASSED
tests/test_scrapers.py::TestLinkedInParseRaw::test_parse_missing_salary PASSED
tests/test_scrapers.py::TestLinkedInParseRaw::test_parse_remote_detected PASSED
tests/test_scrapers.py::TestLinkedInAuth::test_missing_credentials_raises_authentication_error PASSED
tests/test_scrapers.py::TestLinkedInAuth::test_cookie_load_skips_login PASSED
tests/test_scrapers.py::TestLinkedInAuth::test_2fa_challenge_raises_authentication_error PASSED
tests/test_scrapers.py::TestLinkedInSearch::test_search_returns_list_of_jobs PASSED
tests/test_scrapers.py::TestLinkedInSearch::test_excluded_keyword_dropped PASSED
tests/test_scrapers.py::TestLinkedInSearch::test_deduplication_in_batch PASSED
tests/test_scrapers.py::TestLinkedInSearch::test_deduplication_seen_urls PASSED
10 passed in 0.XXs
```

### Step 7.7 — Commit

```
git add src/scrapers/linkedin.py tests/test_scrapers.py tests/fixtures/linkedin/ pyproject.toml
git commit -m "feat(scrapers): implement LinkedInScraper with stealth and cookie auth"
```

---

## Task 8 — Rate Limiting + Token Bucket Tests

### Objective
Test `_TokenBucket` in isolation and verify `_with_retry` retries correctly on `RateLimitError`. These tests use time mocking — no real sleeps.

### Step 8.1 — Write failing tests

Append to `tests/test_scrapers.py`:

```python
# ---------------------------------------------------------------------------
# Task 8 — Rate limiting + _TokenBucket
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, patch

from src.scrapers.base import _TokenBucket, WORKING_DAYS_PER_YEAR
from src.scrapers.exceptions import ParseError, RateLimitError


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self) -> None:
        bucket = _TokenBucket(capacity=10, rate=1.0)
        assert bucket._tokens == 10.0
        await bucket.acquire()
        assert bucket._tokens == 9.0

    @pytest.mark.asyncio
    async def test_full_bucket_does_not_block(self) -> None:
        bucket = _TokenBucket(capacity=5, rate=1.0)
        # Should complete immediately — bucket has 5 tokens
        for _ in range(5):
            await bucket.acquire()
        assert bucket._tokens == 0.0

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self) -> None:
        import time
        bucket = _TokenBucket(capacity=10, rate=10.0)  # 10 tokens/sec
        bucket._tokens = 0.0
        # Simulate 1 second passing
        bucket._last_refill = time.monotonic() - 1.0
        await bucket.acquire()  # should succeed after refill
        assert bucket._tokens >= 0.0


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_error(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError("429")
            return "ok"

        scraper = _ConcreteScraper()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper._with_retry(flaky)  # pass callable, not flaky()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_immediately_on_parse_error(self) -> None:
        async def broken() -> str:
            raise ParseError("malformed")

        scraper = _ConcreteScraper()
        with pytest.raises(ParseError):
            await scraper._with_retry(broken)  # pass callable, not broken()

    @pytest.mark.asyncio
    async def test_returns_none_after_max_attempts(self) -> None:
        async def always_fails() -> str:
            raise RateLimitError("429")

        scraper = _ConcreteScraper()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper._with_retry(always_fails, max_attempts=3)  # callable
        assert result is None

    @pytest.mark.asyncio
    async def test_exponential_backoff_1_2_4(self) -> None:
        sleep_calls: list[float] = []

        async def record_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        async def always_fails() -> None:
            raise RateLimitError("429")

        scraper = _ConcreteScraper()
        with patch("asyncio.sleep", side_effect=record_sleep):
            await scraper._with_retry(always_fails, max_attempts=3)  # callable

        # Backoff: 1s after attempt 1, 2s after attempt 2, no sleep after last
        assert sleep_calls == [1.0, 2.0]
```

Run — expect green (implementation was done in Task 2):

```bash
pytest tests/test_scrapers.py::TestTokenBucket tests/test_scrapers.py::TestWithRetry -v
```

Expected output:
```
tests/test_scrapers.py::TestTokenBucket::test_acquire_decrements_tokens PASSED
tests/test_scrapers.py::TestTokenBucket::test_full_bucket_does_not_block PASSED
tests/test_scrapers.py::TestTokenBucket::test_tokens_refill_over_time PASSED
tests/test_scrapers.py::TestWithRetry::test_retries_on_rate_limit_error PASSED
tests/test_scrapers.py::TestWithRetry::test_raises_immediately_on_parse_error PASSED
tests/test_scrapers.py::TestWithRetry::test_returns_none_after_max_attempts PASSED
tests/test_scrapers.py::TestWithRetry::test_exponential_backoff_1_2_4 PASSED
7 passed in 0.XXs
```

### Step 8.2 — Commit

```
git add tests/test_scrapers.py
git commit -m "test(scrapers): add rate limiter and retry backoff tests"
```

---

## Task 9 — Full Suite + Type Check + Lint

### Objective
Run the complete test suite, `mypy`, and `ruff`. Fix any issues found. This is the integration gate before Phase 1 is considered done.

### Step 9.1 — Run full test suite

```bash
pytest tests/test_scrapers.py -v --tb=short
```

Expected output (counts will match accumulated tests):
```
tests/test_scrapers.py::TestExceptions::... PASSED (3)
tests/test_scrapers.py::TestScraperFilters::... PASSED (5)
tests/test_scrapers.py::TestWorkingDaysConstant::... PASSED (1)
tests/test_scrapers.py::TestParseSalary::... PASSED (8)
tests/test_scrapers.py::TestNormalize::... PASSED (15)
tests/test_scrapers.py::TestSearchDeduplication::... PASSED (5)
tests/test_scrapers.py::TestWTTJParseRaw::... PASSED (5)
tests/test_scrapers.py::TestWTTJSearch::... PASSED (5)
tests/test_scrapers.py::TestIndeedParseRaw::... PASSED (5)
tests/test_scrapers.py::TestIndeedSearch::... PASSED (3)
tests/test_scrapers.py::TestLinkedInParseRaw::... PASSED (3)
tests/test_scrapers.py::TestLinkedInAuth::... PASSED (3)
tests/test_scrapers.py::TestLinkedInSearch::... PASSED (4)
tests/test_scrapers.py::TestTokenBucket::... PASSED (3)
tests/test_scrapers.py::TestWithRetry::... PASSED (4)
72 passed in X.XXs
```

### Step 9.2 — Type check

```bash
mypy src/scrapers/
```

Expected output:
```
Success: no issues found in 6 source files
```

Likely `mypy` issues to anticipate and fix:
- `_with_retry` receives a coroutine `Any` — annotate the parameter as `Coroutine[Any, Any, T]` and use `TypeVar T`
- `_stealth_fn` callable type — annotate as `Callable[[Page], Awaitable[None]] | None`
- `soup.select_one(...)` returns `Tag | NavigableString | None` — add `isinstance(el, Tag)` guards

### Step 9.3 — Lint

```bash
ruff check src/scrapers/ tests/test_scrapers.py
```

Expected output:
```
All checks passed.
```

Common ruff issues to anticipate:
- `UP007`: `X | Y` union syntax (already used — should pass with `from __future__ import annotations`)
- `B006`: mutable default arguments — already handled via `field(default_factory=...)` in `ScraperFilters`
- `I001`: import order — keep stdlib before third-party before local

### Step 9.4 — Also run existing test files to confirm no regressions

```bash
pytest tests/ -v --tb=short
```

Expected: all pre-existing passing tests remain passing.

### Step 9.5 — Final commit

```
git add src/scrapers/ tests/test_scrapers.py
git commit -m "feat(scrapers): Phase 1 scraping — WTTJ, Indeed, LinkedIn fully implemented"
```

---

## Implementation Sequence Summary

| Task | Files modified | Tests written | Commits |
|---|---|---|---|
| 1 | `exceptions.py` (create), `filters.py` (create) | 8 | 1 |
| 2 | `base.py` (rewrite) | 24 | 1 |
| 3 | `tests/test_scrapers.py` only | 5 | 1 |
| 4 | 3 JSON fixture files | 0 | 1 |
| 5 | `wttj.py` (rewrite) | 10 | 1 |
| 6 | `indeed.py` (rewrite), 3 HTML fixtures | 8 | 1 |
| 7 | `linkedin.py` (rewrite), 2 HTML fixtures, `pyproject.toml` | 10 | 1 |
| 8 | `tests/test_scrapers.py` only | 7 | 1 |
| 9 | Fixes from mypy/ruff | 0 | 1 |

Total: ~72 tests, 9 commits.

---

## Potential Pitfalls

**`_with_retry` coroutine consumption.** Python coroutines can only be awaited once. The `_with_retry(coro)` pattern will fail on retry if `coro` is already consumed. The implementation must accept a callable (factory) rather than a bare coroutine, or re-create the coroutine on each attempt. Recommended signature: `_with_retry(self, fn: Callable[[], Coroutine[Any, Any, T]], max_attempts: int = 3) -> T | None`. The tests in Task 8 must call it as `_with_retry(flaky)` (passing the function, not the coroutine `flaky()`).

**`asyncio_mode = "auto"` vs explicit `@pytest.mark.asyncio`.** `pyproject.toml` already sets `asyncio_mode = "auto"`, so the `@pytest.mark.asyncio` decorator is technically redundant but harmless. Keep it for explicitness.

**`playwright-stealth` availability in CI.** If the package is unavailable, `_setup()` logs a warning and continues without stealth. Tests must not import `playwright_stealth` directly — they patch `scraper._stealth_fn`.

**WTTJ XHR response handler is async within a sync callback.** `page.on("response", handler)` registers a sync callable; if the handler is `async`, Playwright will not await it automatically. The `_handle_response` must be a sync function that schedules coroutine execution, or use `asyncio.ensure_future`. The implementation above uses `async def` — verify Playwright's Python API supports async event handlers (it does in `playwright >= 1.18`).

**`Job` instantiation without a session.** SQLAlchemy ORM instances can be created without a session (transient state). `company_id` is `nullable=True` so scrapers leave it as `None`. The `JobScheduler` handles company resolution and `session.add()`.

---

### Critical Files for Implementation

- `/Users/c_mdevillele/Documents/Documents - L062N6GVX9/jobhunter-ai/src/scrapers/base.py` - Core rewrite: all shared infrastructure lives here, all other scrapers depend on it
- `/Users/c_mdevillele/Documents/Documents - L062N6GVX9/jobhunter-ai/tests/test_scrapers.py` - Full replacement: all 72 tests incrementally added across 9 tasks
- `/Users/c_mdevillele/Documents/Documents - L062N6GVX9/jobhunter-ai/src/scrapers/wttj.py` - First concrete scraper: establishes the XHR intercept pattern for review before Indeed/LinkedIn
- `/Users/c_mdevillele/Documents/Documents - L062N6GVX9/jobhunter-ai/src/storage/models.py` - Reference only: `Job` field names and nullability constraints govern every scraper's `_parse_raw` output
- `/Users/c_mdevillele/Documents/Documents - L062N6GVX9/jobhunter-ai/pyproject.toml` - Requires `playwright-stealth` addition before Task 7 and `pip install -e ".[dev]"` re-run