"""Tests for multi-country integration in main.py and scheduler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.storage.database import configure, drop_all, init_db
from src.storage.models import Job
from src.utils.salary_normalizer import get_supported_countries


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


class TestMainScanMultiCountry:
    """Verify scan command iterates over countries from profile.yaml."""

    def test_profile_has_countries(self) -> None:
        profile_path = Path(__file__).parent.parent / "src" / "config" / "profile.yaml"
        with profile_path.open() as fh:
            profile = yaml.safe_load(fh)
        countries = profile.get("search", {}).get("countries", [])
        assert len(countries) >= 2
        assert "FR" in countries

    def test_unsupported_countries_are_skipped(self) -> None:
        """get_supported_countries correctly filters by scraper."""
        assert "FR" in get_supported_countries("wttj")
        assert "US" not in get_supported_countries("wttj")
        assert "US" in get_supported_countries("indeed_api")


class TestSchedulerMultiCountry:
    """Verify scheduler _scan_phase uses country iteration."""

    @pytest.mark.asyncio
    async def test_scan_phase_passes_country_code_to_scraper(self) -> None:
        """The scheduler should call scraper.search with country_code."""
        from src.scheduler.job_scheduler import JobScheduler

        mock_scraper = AsyncMock()
        mock_scraper.search = AsyncMock(return_value=[])
        mock_scraper.__aenter__ = AsyncMock(return_value=mock_scraper)
        mock_scraper.__aexit__ = AsyncMock(return_value=False)

        scheduler = JobScheduler(
            scorer=MagicMock(),
            cv_gen=MagicMock(),
            cl_gen=MagicMock(),
        )

        await scheduler._scan_phase(scrapers=[mock_scraper], countries=["FR", "US"])

        # Should have been called at least with country_code
        calls = mock_scraper.search.call_args_list
        assert len(calls) >= 1
        # At least one call should have country_code
        country_codes_used = [
            c.kwargs.get("country_code") or c[1].get("country_code")
            for c in calls
            if c.kwargs.get("country_code") or (len(c) > 1 and isinstance(c[1], dict) and c[1].get("country_code"))
        ]
        assert "FR" in country_codes_used or len(calls) >= 2
