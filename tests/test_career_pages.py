"""Tests for CareerPageScraper — Greenhouse & Ashby API parsing + title filters."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.scrapers.career_pages import CareerPageScraper

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(fixture_name: str, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response from a fixture JSON file."""
    fixture_path = FIXTURES / fixture_name
    content = fixture_path.read_bytes()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# Greenhouse API parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_greenhouse_api_parsing():
    """Mock Greenhouse HTTP response → filtered list of job dicts."""
    scraper = CareerPageScraper()
    scraper._client = AsyncMock(spec=httpx.AsyncClient)
    scraper._client.get = AsyncMock(
        return_value=_mock_response("greenhouse_anthropic.json"),
    )

    filters = {
        "positive": ["automation", "engineer", "AI", "platform", "architect", "operations"],
        "negative": ["junior", "intern", "internship", "stage"],
    }
    jobs = await scraper._scan_greenhouse("anthropic", filters)

    # Fixture has 5 jobs: 2 should be filtered out (Junior Research Intern)
    # "Junior Research Intern" → negative match on both "junior" and "intern"
    # Remaining: Senior AI Platform Engineer, Automation Engineer, Solutions Architect, Operations Manager
    assert len(jobs) == 4
    titles = {j["title"] for j in jobs}
    assert "Junior Research Intern" not in titles
    assert "Senior AI Platform Engineer" in titles
    assert "Automation Engineer — DevOps Tools" in titles


# ---------------------------------------------------------------------------
# Ashby API parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ashby_api_parsing():
    """Mock Ashby GraphQL response → filtered list of job dicts."""
    scraper = CareerPageScraper()
    scraper._client = AsyncMock(spec=httpx.AsyncClient)
    scraper._client.post = AsyncMock(
        return_value=_mock_response("ashby_linear.json"),
    )

    filters = {
        "positive": ["engineer", "platform"],
        "negative": ["junior", "intern"],
    }
    jobs = await scraper._scan_ashby("linear", filters)

    # Fixture has 3 postings:
    # "Senior Platform Engineer" → matches positive
    # "Junior Frontend Intern" → blocked by negative
    # "Staff Engineer — Infrastructure" → matches positive
    assert len(jobs) == 2
    titles = {j["title"] for j in jobs}
    assert "Junior Frontend Intern" not in titles
    assert "Senior Platform Engineer" in titles
    assert "Staff Engineer — Infrastructure" in titles


# ---------------------------------------------------------------------------
# Title filter unit tests
# ---------------------------------------------------------------------------


def test_title_filter_positive():
    """Title containing a positive keyword passes."""
    filters = {"positive": ["AI", "engineer"], "negative": []}
    assert CareerPageScraper._apply_title_filter("Senior AI Engineer", filters) is True


def test_title_filter_negative():
    """Title containing a negative keyword is rejected even if positive matches."""
    filters = {"positive": ["AI", "engineer"], "negative": ["junior"]}
    assert CareerPageScraper._apply_title_filter("Junior AI Engineer", filters) is False


def test_title_filter_no_positive_match():
    """Title with no positive keyword match is rejected."""
    filters = {"positive": ["AI", "automation"], "negative": []}
    assert CareerPageScraper._apply_title_filter("Office Manager", filters) is False


def test_title_filter_empty_positive_accepts_all():
    """Empty positive list means accept all (only negative can reject)."""
    filters = {"positive": [], "negative": ["intern"]}
    assert CareerPageScraper._apply_title_filter("Senior Manager", filters) is True


def test_title_filter_case_insensitive():
    """Filtering is case-insensitive."""
    filters = {"positive": ["AI"], "negative": ["JUNIOR"]}
    assert CareerPageScraper._apply_title_filter("ai platform lead", filters) is True
    assert CareerPageScraper._apply_title_filter("Junior AI Engineer", filters) is False


# ---------------------------------------------------------------------------
# Deduplication across portals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_across_portals():
    """Same URL from two sources produces only 1 Job."""
    duplicate_url = "https://boards.greenhouse.io/anthropic/jobs/100001"

    scraper = CareerPageScraper()
    scraper._client = AsyncMock(spec=httpx.AsyncClient)
    scraper._client.get = AsyncMock(
        return_value=_mock_response("greenhouse_anthropic.json"),
    )

    # Pre-populate seen_urls with one URL from the fixture
    seen = {duplicate_url}

    # Patch load_portals to return only one greenhouse portal
    portals = {
        "anthropic": {
            "platform": "greenhouse",
            "slug": "anthropic",
            "title_filter": {
                "positive": ["engineer", "AI", "platform", "automation", "architect", "operations"],
                "negative": ["junior", "intern"],
            },
        },
    }
    with patch("src.scrapers.career_pages.load_portals", return_value=portals), \
         patch("src.scrapers.career_pages.load_default_title_filter", return_value={"positive": [], "negative": []}):
        jobs = await scraper.scan_all_portals(seen_urls=seen)

    # The duplicate URL should be excluded → 3 instead of 4
    urls = [j.url for j in jobs]
    assert duplicate_url not in urls
    assert len(jobs) == 3


# ---------------------------------------------------------------------------
# Integration: scan_all_portals with mixed platforms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_all_portals_integration():
    """Mock 3 portals (2 greenhouse + 1 ashby) → combined jobs list."""
    scraper = CareerPageScraper()
    scraper._client = AsyncMock(spec=httpx.AsyncClient)

    greenhouse_resp = _mock_response("greenhouse_anthropic.json")
    ashby_resp = _mock_response("ashby_linear.json")

    # greenhouse.get returns same fixture for both greenhouse portals
    scraper._client.get = AsyncMock(return_value=greenhouse_resp)
    scraper._client.post = AsyncMock(return_value=ashby_resp)

    portals = {
        "anthropic": {
            "platform": "greenhouse",
            "slug": "anthropic",
            "title_filter": {
                "positive": ["automation", "engineer", "AI", "platform", "architect", "operations"],
                "negative": ["junior", "intern"],
            },
        },
        "notion": {
            "platform": "greenhouse",
            "slug": "notion",
            "title_filter": {
                "positive": ["engineer", "platform", "AI", "automation"],
                "negative": ["junior", "intern"],
            },
        },
        "linear": {
            "platform": "ashby",
            "slug": "linear",
            "title_filter": {
                "positive": ["engineer", "platform"],
                "negative": ["junior", "intern"],
            },
        },
    }
    with patch("src.scrapers.career_pages.load_portals", return_value=portals), \
         patch("src.scrapers.career_pages.load_default_title_filter", return_value={"positive": [], "negative": []}):
        jobs = await scraper.scan_all_portals()

    # anthropic: 4 pass filter, notion: same fixture → 4 pass but all deduped by URL, linear: 2 pass
    # Total: 4 (anthropic) + 0 (notion, same URLs) + 2 (linear) = 6
    assert len(jobs) == 6
    sources = {j.source for j in jobs}
    assert sources == {"career_page"}
