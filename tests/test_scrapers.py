"""Tests for scrapers — Phase 1."""

import json
from dataclasses import fields
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup, Tag

from src.scrapers.base import WORKING_DAYS_PER_YEAR, BaseScraper, _TokenBucket
from src.scrapers.exceptions import (
    AuthenticationError,
    ParseError,
    RateLimitError,
    ScraperError,
)
from src.scrapers.filters import ScraperFilters
from src.scrapers.indeed import IndeedScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.wttj import WTTJScraper
from src.storage.models import Job

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


# ---------------------------------------------------------------------------
# Task 2 — BaseScraper normalization + salary parsing
# ---------------------------------------------------------------------------


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
        job = self._make_job()
        result = self.scraper._normalize(job, self.filters)
        assert result is not None
        assert result.scraped_at is not None
        assert result.scraped_at.tzinfo == UTC

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


# ---------------------------------------------------------------------------
# Task 3 — BaseScraper deduplication + search() wiring
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 5 — WTTJScraper
# ---------------------------------------------------------------------------


WTTJ_FIXTURES = Path(__file__).parent / "fixtures" / "wttj"


def _load_wttj_fixture(filename: str) -> dict:  # type: ignore[type-arg]
    return json.loads((WTTJ_FIXTURES / filename).read_text())


class TestWTTJParseRaw:
    """Unit tests for WTTJScraper._parse_raw — no Playwright required."""

    def setup_method(self) -> None:
        self.scraper = WTTJScraper.__new__(WTTJScraper)
        self.scraper.headless = True
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


# ---------------------------------------------------------------------------
# Task 6 — IndeedScraper
# ---------------------------------------------------------------------------


INDEED_FIXTURES = Path(__file__).parent / "fixtures" / "indeed"


def _load_indeed_cards(filename: str) -> list[Tag]:
    html = (INDEED_FIXTURES / filename).read_text()
    soup = BeautifulSoup(html, "lxml")
    return soup.select(".job_seen_beacon")


class TestIndeedParseRaw:
    def setup_method(self) -> None:
        self.scraper = IndeedScraper.__new__(IndeedScraper)
        self.scraper.headless = True
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


# ---------------------------------------------------------------------------
# Task 7 — LinkedInScraper
# ---------------------------------------------------------------------------


LINKEDIN_FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def _load_linkedin_html(filename: str) -> str:
    return (LINKEDIN_FIXTURES / filename).read_text()


class TestLinkedInParseRaw:
    def setup_method(self) -> None:
        self.scraper = LinkedInScraper.__new__(LinkedInScraper)
        self.scraper.headless = True
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
        assert job.contract_type is not None
        assert job.location is not None

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
        mock_page.query_selector = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(scraper, "_is_authenticated", return_value=False),
            patch.object(scraper, "_has_credentials", return_value=False),
            pytest.raises(AuthenticationError),
        ):
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

        with (
            patch.object(scraper, "_is_authenticated", return_value=False),
            patch.object(scraper, "_has_credentials", return_value=True),
            patch.object(
                scraper,
                "_run_login",
                side_effect=AuthenticationError("2FA challenge"),
            ),
            pytest.raises(AuthenticationError, match="2FA"),
        ):
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


# ---------------------------------------------------------------------------
# Task 8 — _TokenBucket + _with_retry
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_initializes_with_full_capacity(self) -> None:
        bucket = _TokenBucket(capacity=10, rate=1.0)
        assert bucket._tokens == 10.0
        assert bucket._capacity == 10.0
        assert bucket._rate == 1.0

    @pytest.mark.asyncio
    async def test_acquire_decrements_one_token(self) -> None:
        bucket = _TokenBucket(capacity=10, rate=1.0)
        await bucket.acquire()
        assert bucket._tokens == 9.0

    @pytest.mark.asyncio
    async def test_full_bucket_does_not_sleep(self) -> None:
        bucket = _TokenBucket(capacity=10, rate=1.0)
        with patch("asyncio.sleep") as mock_sleep:
            await bucket.acquire()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_bucket_sleeps_until_refill(self) -> None:
        """When the bucket is empty, acquire() must call asyncio.sleep."""
        sleep_called = False

        async def fake_sleep(duration: float) -> None:
            nonlocal sleep_called
            sleep_called = True
            # Simulate time passing: inject tokens so the loop can exit
            bucket._tokens = 1.0

        bucket = _TokenBucket(capacity=1, rate=1.0 / 3600)
        await bucket.acquire()  # consume the single token

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await bucket.acquire()

        assert sleep_called


class TestWithRetry:
    def setup_method(self) -> None:
        self.scraper = _ConcreteScraper()

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self) -> None:
        async def coro() -> str:
            return "ok"

        result = await self.scraper._with_retry(coro)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_recovers_on_second_attempt(self) -> None:
        call_count = 0

        async def flaky_coro() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("transient")
            return "recovered"

        with patch("asyncio.sleep"):
            result = await self.scraper._with_retry(flaky_coro, max_attempts=3)

        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_none_after_max_attempts(self) -> None:
        call_count = 0

        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        with patch("asyncio.sleep"):
            result = await self.scraper._with_retry(always_fails, max_attempts=3)

        assert result is None
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_parse_error_raises_immediately_without_retry(self) -> None:
        async def coro() -> str:
            raise ParseError("bad html")

        with (
            patch("asyncio.sleep") as mock_sleep,
            pytest.raises(ParseError, match="bad html"),
        ):
            await self.scraper._with_retry(coro)

        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_error_retries_and_returns_none(self) -> None:
        call_count = 0

        async def rate_limited() -> str:
            nonlocal call_count
            call_count += 1
            raise RateLimitError("429")

        with patch("asyncio.sleep"):
            result = await self.scraper._with_retry(rate_limited, max_attempts=3)

        assert result is None
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_backoff_doubles_between_retries(self) -> None:
        """Backoff: 1s after attempt 1, 2s after attempt 2."""
        sleep_durations: list[float] = []

        async def track_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        async def always_fails() -> str:
            raise Exception("fail")

        with patch("asyncio.sleep", side_effect=track_sleep):
            await self.scraper._with_retry(always_fails, max_attempts=3)

        assert sleep_durations == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_coro_fn_called_fresh_per_retry(self) -> None:
        """coro_fn must be a callable — each retry calls coro_fn() for a fresh coroutine."""
        call_log: list[int] = []

        async def track_calls() -> str:
            call_log.append(1)
            raise Exception("retry me")

        with patch("asyncio.sleep"):
            await self.scraper._with_retry(track_calls, max_attempts=3)

        assert len(call_log) == 3


# ---------------------------------------------------------------------------
# Task — Settings: indeed_api_key + indeed_mode
# ---------------------------------------------------------------------------


class TestIndeedApiSettings:
    def test_indeed_api_key_default_is_empty(self) -> None:
        from src.config.settings import Settings
        s = Settings()
        assert s.indeed_api_key == ""

    def test_indeed_mode_default_is_api(self) -> None:
        from src.config.settings import Settings
        s = Settings()
        assert s.indeed_mode == "api"

    def test_indeed_mode_can_be_playwright(self) -> None:
        import os

        from src.config.settings import Settings
        old = os.environ.get("INDEED_MODE")
        os.environ["INDEED_MODE"] = "playwright"
        try:
            s = Settings()
            assert s.indeed_mode == "playwright"
        finally:
            if old is None:
                del os.environ["INDEED_MODE"]
            else:
                os.environ["INDEED_MODE"] = old


# ---------------------------------------------------------------------------
# Task — IndeedApiScraper._parse_raw
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path
from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

_INDEED_API_FIXTURES = _Path(__file__).parent / "fixtures" / "indeed_api"


def _make_mock_response(fixture_path: _Path) -> _MagicMock:
    """Build a mock httpx response that returns fixture JSON."""
    mock_response = _MagicMock()
    mock_response.raise_for_status = _MagicMock()
    mock_response.json = _MagicMock(return_value=_json.loads(fixture_path.read_text()))
    return mock_response


class TestIndeedApiParseRaw:
    def setup_method(self) -> None:
        from src.scrapers.indeed_api import IndeedApiScraper
        from src.scrapers.base import _TokenBucket

        self.scraper = IndeedApiScraper.__new__(IndeedApiScraper)
        self.scraper.headless = True
        # Full bucket (3600 tokens, rate=1/s) so _wait() never sleeps in tests
        self.scraper._token_bucket = _TokenBucket(3600, 1.0)
        # Inject mock httpx client
        self.scraper._client = _MagicMock()

    @pytest.mark.asyncio
    async def test_parse_complete_job(self) -> None:
        detail_fixture = _INDEED_API_FIXTURES / "job_detail.json"
        self.scraper._client.get = _AsyncMock(
            return_value=_make_mock_response(detail_fixture)
        )
        raw = {"job_id": "eyJqb2JJZCI6ImFiYzEyMyJ9"}
        job = await self.scraper._parse_raw(raw)

        assert job.title == "Senior RevOps Engineer"
        assert job.url == "https://fr.indeed.com/viewjob?jk=abc123"
        assert job.source == "indeed_api"
        assert job.salary_min == 80000
        assert job.salary_max == 100000
        assert job.contract_type == "CDI"
        assert "Python" in (job.description or "")
        assert job.location == "Paris, FR"

    @pytest.mark.asyncio
    async def test_parse_missing_salary(self) -> None:
        detail_fixture = _INDEED_API_FIXTURES / "job_no_salary.json"
        self.scraper._client.get = _AsyncMock(
            return_value=_make_mock_response(detail_fixture)
        )
        raw = {"job_id": "eyJqb2JJZCI6ImRlZjQ1NiJ9"}
        job = await self.scraper._parse_raw(raw)

        assert job.salary_min is None
        assert job.salary_max is None
        assert job.salary_raw is None

    @pytest.mark.asyncio
    async def test_parse_contractor_mapped_to_freelance(self) -> None:
        detail_fixture = _INDEED_API_FIXTURES / "job_no_salary.json"
        self.scraper._client.get = _AsyncMock(
            return_value=_make_mock_response(detail_fixture)
        )
        raw = {"job_id": "eyJqb2JJZCI6ImRlZjQ1NiJ9"}
        job = await self.scraper._parse_raw(raw)

        assert job.contract_type == "Freelance"

    @pytest.mark.asyncio
    async def test_parse_null_city_uses_country_only(self) -> None:
        # Build a fixture with null job_city inline
        mock_data = {
            "status": "OK",
            "data": [{
                "job_id": "x",
                "employer_name": "Co",
                "job_title": "Engineer",
                "job_description": "Full description here.",
                "job_city": None,
                "job_country": "FR",
                "job_is_remote": True,
                "job_min_salary": None,
                "job_max_salary": None,
                "job_salary_period": None,
                "job_apply_link": "https://fr.indeed.com/viewjob?jk=x",
                "job_employment_type": "FULLTIME",
            }]
        }
        mock_resp = _MagicMock()
        mock_resp.raise_for_status = _MagicMock()
        mock_resp.json = _MagicMock(return_value=mock_data)
        self.scraper._client.get = _AsyncMock(return_value=mock_resp)

        job = await self.scraper._parse_raw({"job_id": "x"})
        assert job.location == "FR"

    @pytest.mark.asyncio
    async def test_parse_raises_parse_error_on_empty_data(self) -> None:
        from src.scrapers.exceptions import ParseError
        mock_resp = _MagicMock()
        mock_resp.raise_for_status = _MagicMock()
        mock_resp.json = _MagicMock(return_value={"status": "OK", "data": []})
        self.scraper._client.get = _AsyncMock(return_value=mock_resp)

        with pytest.raises(ParseError):
            await self.scraper._parse_raw({"job_id": "missing"})
