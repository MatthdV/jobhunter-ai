"""Tests for GmailJobAlertScraper."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ConfigurationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
  <table>
    <tr>
      <td>
        <a href="https://www.linkedin.com/comm/jobs/view/3900000001?trk=alert">
          Automation Engineer
        </a>
        <div>Acme Corp</div>
        <div>· Remote, France</div>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://www.linkedin.com/jobs/view/3900000002?trk=alert">
          RevOps Consultant
        </a>
        <div>BigCo</div>
        <div>· Paris, France</div>
      </td>
    </tr>
  </table>
</body></html>
"""

_JSEARCH_RESPONSE = {
    "data": [
        {
            "job_id": "ext_abc123",
            "job_title": "Automation Engineer",
            "employer_name": "Acme Corp",
            "job_city": "Remote",
            "job_country": "France",
            "job_description": "We are looking for an Automation Engineer...",
            "job_min_salary": 70000,
            "job_max_salary": 90000,
            "job_apply_link": "https://www.linkedin.com/jobs/view/3900000001",
        }
    ]
}


def _make_gmail_message(html: str, message_id: str = "msg_001") -> dict:
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    return {
        "id": message_id,
        "payload": {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded},
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Unit tests — HTML parsing
# ---------------------------------------------------------------------------


class TestParseHtml:
    def _make_scraper(self) -> "GmailJobAlertScraper":
        from src.scrapers.gmail_scraper import GmailJobAlertScraper

        with (
            patch("src.scrapers.gmail_scraper.settings") as mock_settings,
        ):
            mock_settings.is_gmail_configured = True
            mock_settings.indeed_api_key = "test_key"
            mock_settings.gmail_refresh_token = "rt"
            mock_settings.gmail_client_id = "cid"
            mock_settings.gmail_client_secret = "cs"
            scraper = GmailJobAlertScraper.__new__(GmailJobAlertScraper)
            scraper._gmail_service = None
            scraper._http = None
            from src.scrapers.base import _TokenBucket
            scraper._token_bucket = _TokenBucket(capacity=60, rate=60 / 3600)
            return scraper

    def test_parse_html_extracts_two_stubs(self) -> None:
        scraper = self._make_scraper()
        stubs = scraper._parse_html(_SAMPLE_HTML)
        assert len(stubs) == 2

    def test_parse_html_extracts_title(self) -> None:
        scraper = self._make_scraper()
        stubs = scraper._parse_html(_SAMPLE_HTML)
        assert stubs[0]["title"] == "Automation Engineer"
        assert stubs[1]["title"] == "RevOps Consultant"

    def test_parse_html_canonical_url(self) -> None:
        scraper = self._make_scraper()
        stubs = scraper._parse_html(_SAMPLE_HTML)
        assert stubs[0]["url"] == "https://www.linkedin.com/jobs/view/3900000001"
        assert stubs[1]["url"] == "https://www.linkedin.com/jobs/view/3900000002"

    def test_parse_html_dedup(self) -> None:
        html = _SAMPLE_HTML + """
        <a href="https://www.linkedin.com/jobs/view/3900000001?trk=dup">
          Automation Engineer
        </a>"""
        scraper = self._make_scraper()
        stubs = scraper._parse_html(html)
        urls = [s["url"] for s in stubs]
        assert len(set(urls)) == len(urls)

    def test_parse_html_skips_non_job_links(self) -> None:
        html = '<a href="https://www.linkedin.com/feed/">Feed</a>'
        scraper = self._make_scraper()
        stubs = scraper._parse_html(html)
        assert stubs == []

    def test_extract_html_walks_mime_parts(self) -> None:
        scraper = self._make_scraper()
        raw_msg = _make_gmail_message("<html><body>hello</body></html>")
        result = scraper._extract_html(raw_msg)
        assert "hello" in result


# ---------------------------------------------------------------------------
# Unit tests — JSearch matching
# ---------------------------------------------------------------------------


class TestBestMatch:
    def _make_scraper(self) -> "GmailJobAlertScraper":
        from src.scrapers.gmail_scraper import GmailJobAlertScraper

        scraper = GmailJobAlertScraper.__new__(GmailJobAlertScraper)
        return scraper

    def test_best_match_returns_first_when_title_overlaps(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Automation Engineer", "company": "Acme Corp"}
        result = scraper._best_match(_JSEARCH_RESPONSE["data"], stub)
        assert result is not None
        assert result["job_title"] == "Automation Engineer"

    def test_best_match_returns_first_on_no_overlap(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Completely Different Role", "company": "Other"}
        result = scraper._best_match(_JSEARCH_RESPONSE["data"], stub)
        # Falls back to first result
        assert result is not None

    def test_best_match_returns_none_on_empty(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Automation Engineer", "company": "Acme"}
        assert scraper._best_match([], stub) is None


# ---------------------------------------------------------------------------
# Unit tests — result_to_job
# ---------------------------------------------------------------------------


class TestResultToJob:
    def _make_scraper(self) -> "GmailJobAlertScraper":
        from src.scrapers.gmail_scraper import GmailJobAlertScraper

        scraper = GmailJobAlertScraper.__new__(GmailJobAlertScraper)
        return scraper

    def test_result_to_job_keeps_linkedin_url(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Automation Engineer", "url": "https://www.linkedin.com/jobs/view/123"}
        job = scraper._result_to_job(_JSEARCH_RESPONSE["data"][0], stub)
        assert job.url == "https://www.linkedin.com/jobs/view/123"

    def test_result_to_job_maps_salary(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Automation Engineer", "url": "https://www.linkedin.com/jobs/view/123"}
        job = scraper._result_to_job(_JSEARCH_RESPONSE["data"][0], stub)
        assert job.salary_min == 70000
        assert job.salary_max == 90000

    def test_result_to_job_sets_source(self) -> None:
        scraper = self._make_scraper()
        stub = {"title": "Automation Engineer", "url": "https://www.linkedin.com/jobs/view/123"}
        scraper.source = "gmail_alert"
        job = scraper._result_to_job(_JSEARCH_RESPONSE["data"][0], stub)
        assert job.source == "gmail_alert"

    def test_stub_to_job_fallback(self) -> None:
        scraper = self._make_scraper()
        stub = {
            "title": "RevOps",
            "url": "https://www.linkedin.com/jobs/view/999",
            "location": "Paris",
            "company": "Acme",
        }
        job = scraper._stub_to_job(stub)
        assert job.title == "RevOps"
        assert job.description is None
        assert job.location == "Paris"


# ---------------------------------------------------------------------------
# Init — ConfigurationError
# ---------------------------------------------------------------------------


class TestInit:
    def test_raises_if_gmail_not_configured(self) -> None:
        from src.scrapers.gmail_scraper import GmailJobAlertScraper

        with patch("src.scrapers.gmail_scraper.settings") as mock_settings:
            mock_settings.is_gmail_configured = False
            mock_settings.indeed_api_key = "key"
            with pytest.raises(ConfigurationError, match="Gmail not configured"):
                GmailJobAlertScraper()

    def test_raises_if_jsearch_key_missing(self) -> None:
        from src.scrapers.gmail_scraper import GmailJobAlertScraper

        with patch("src.scrapers.gmail_scraper.settings") as mock_settings:
            mock_settings.is_gmail_configured = True
            mock_settings.indeed_api_key = ""
            with pytest.raises(ConfigurationError, match="INDEED_API_KEY"):
                GmailJobAlertScraper()
