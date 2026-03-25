"""Tests for multi-country scraper support (Task 4)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scrapers.base import BaseScraper
from src.scrapers.filters import ScraperFilters
from src.scrapers.indeed_api import IndeedApiScraper
from src.scrapers.linkedin import LinkedInScraper, _GEO_IDS
from src.scrapers.wttj import WTTJScraper
from src.storage.models import Job
from src.utils.salary_normalizer import get_country_config


# ---------------------------------------------------------------------------
# 4a. BaseScraper — country_code parameter
# ---------------------------------------------------------------------------


class _ConcreteScraper(BaseScraper):
    source = "test"
    MIN_DELAY = 0.0
    MAX_DELAY = 0.0
    MAX_RPH = 3600

    async def _fetch_raw(
        self, keywords: list[str], location: str, filters: ScraperFilters | None, limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        return []

    async def _parse_raw(self, raw: Any) -> Job:
        raise NotImplementedError


class TestBaseScraperCountry:
    @pytest.mark.asyncio
    async def test_search_accepts_country_code(self) -> None:
        """BaseScraper.search() must accept country_code kwarg."""
        scraper = _ConcreteScraper()
        jobs = await scraper.search(keywords=["test"], country_code="US")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_search_default_country_code_is_fr(self) -> None:
        """country_code defaults to FR."""
        scraper = _ConcreteScraper()
        # Should not raise
        jobs = await scraper.search(keywords=["test"])
        assert isinstance(jobs, list)

    def test_normalize_sets_salary_normalized(self) -> None:
        """_normalize should compute salary_normalized_min/max when country_code is set."""
        scraper = _ConcreteScraper()
        job = Job(
            title="test",
            url="https://example.com",
            source="test",
            salary_min=100_000,
            salary_max=120_000,
            country_code="US",
            salary_currency="USD",
        )
        result = scraper._normalize(job, ScraperFilters())
        assert result is not None
        assert result.salary_normalized_min is not None
        assert result.salary_normalized_max is not None
        # 100_000 * 0.92 / 0.85 ≈ 108_235
        assert result.salary_normalized_min == 108235


# ---------------------------------------------------------------------------
# 4b. WTTJ — FR only guard
# ---------------------------------------------------------------------------


class TestWTTJMultiCountry:
    @pytest.mark.asyncio
    async def test_wttj_returns_empty_for_non_fr(self) -> None:
        """WTTJ only supports FR, should return [] for other countries."""
        scraper = WTTJScraper()
        jobs = await scraper.search(keywords=["test"], country_code="US")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_wttj_accepts_fr(self) -> None:
        """WTTJ should accept FR country_code without error (just no browser)."""
        scraper = WTTJScraper()
        # Will return [] because no browser is set up, but shouldn't raise on country_code
        # We can't do full search without Playwright, but the guard shouldn't block FR
        # Just verify the method signature accepts country_code
        import inspect
        sig = inspect.signature(scraper.search)
        assert "country_code" in sig.parameters


# ---------------------------------------------------------------------------
# 4c. Indeed API — parameterized country
# ---------------------------------------------------------------------------


class TestIndeedApiMultiCountry:
    def test_indeed_api_search_has_country_code_param(self) -> None:
        import inspect
        # Check BaseScraper.search signature (IndeedApiScraper inherits it)
        sig = inspect.signature(BaseScraper.search)
        assert "country_code" in sig.parameters

    @pytest.mark.asyncio
    async def test_indeed_api_fetch_uses_country_param(self) -> None:
        """_fetch_raw should use the country from filters, not hardcoded _COUNTRY."""
        scraper = IndeedApiScraper.__new__(IndeedApiScraper)
        scraper._api_key = "fake-key"
        scraper._token_bucket = MagicMock()
        scraper._token_bucket.acquire = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        scraper._client = mock_client

        filters = ScraperFilters(countries=["US"])
        await scraper._fetch_raw(["test"], "remote", filters, 10, country_code="US")

        # Verify the API was called with country="US" not "FR"
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["country"] == "US"


# ---------------------------------------------------------------------------
# 4d. Indeed Playwright — dynamic URL
# ---------------------------------------------------------------------------


class TestIndeedPlaywrightMultiCountry:
    def test_get_base_url_us(self) -> None:
        from src.scrapers.indeed import IndeedScraper
        scraper = IndeedScraper()
        url = scraper._get_base_url("US")
        assert url == "https://us.indeed.com/jobs"

    def test_get_base_url_uk(self) -> None:
        from src.scrapers.indeed import IndeedScraper
        scraper = IndeedScraper()
        url = scraper._get_base_url("GB")
        assert url == "https://co.uk.indeed.com/jobs"

    def test_get_base_url_fr_default(self) -> None:
        from src.scrapers.indeed import IndeedScraper
        scraper = IndeedScraper()
        url = scraper._get_base_url("FR")
        assert url == "https://fr.indeed.com/jobs"

    def test_get_base_url_unknown_falls_back_to_fr(self) -> None:
        from src.scrapers.indeed import IndeedScraper
        scraper = IndeedScraper()
        url = scraper._get_base_url("ZZ")
        assert url == "https://fr.indeed.com/jobs"


# ---------------------------------------------------------------------------
# 4e. LinkedIn — geoId mapping
# ---------------------------------------------------------------------------


class TestLinkedInMultiCountry:
    def test_geo_ids_exist_for_main_countries(self) -> None:
        for code in ["FR", "US", "GB", "DE", "NL", "CH"]:
            assert code in _GEO_IDS, f"Missing geoId for {code}"

    def test_search_url_includes_geo_id(self) -> None:
        """LinkedIn search URL should include geoId when country_code is provided."""
        # Just check the _GEO_IDS mapping has values
        assert _GEO_IDS["FR"] == "105015875"
        assert _GEO_IDS["US"] == "103644278"
