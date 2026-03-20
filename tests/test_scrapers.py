"""Tests for scrapers — Phase 2."""

import pytest

from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.wttj import WTTJScraper


class TestBaseScraper:
    """Contract tests that apply to every scraper implementation."""

    def test_source_attribute_is_set(self) -> None:
        pass  # Phase 2

    def test_implements_abstract_methods(self) -> None:
        pass  # Phase 2


class TestLinkedInScraper:
    @pytest.mark.asyncio
    async def test_scrape_returns_list_of_jobs(self) -> None:
        pass  # Phase 2

    @pytest.mark.asyncio
    async def test_skips_duplicate_urls(self) -> None:
        pass  # Phase 2

    def test_parse_salary_annual(self) -> None:
        pass  # Phase 2

    def test_parse_salary_daily_rate(self) -> None:
        pass  # Phase 2

    def test_parse_salary_returns_none_on_unknown_format(self) -> None:
        pass  # Phase 2


class TestIndeedScraper:
    @pytest.mark.asyncio
    async def test_scrape_returns_list_of_jobs(self) -> None:
        pass  # Phase 2

    def test_parse_salary_fr_format(self) -> None:
        pass  # Phase 2


class TestWTTJScraper:
    @pytest.mark.asyncio
    async def test_scrape_returns_list_of_jobs(self) -> None:
        pass  # Phase 2

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self) -> None:
        pass  # Phase 2
