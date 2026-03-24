"""Scrapers package — exports all scrapers and factory functions."""

from src.scrapers.indeed import IndeedScraper
from src.scrapers.indeed_api import IndeedApiScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.wttj import WTTJScraper


def get_indeed_scraper() -> IndeedScraper | IndeedApiScraper:
    """Return the configured Indeed scraper instance.

    Reads ``settings.indeed_mode``:
    - ``"api"``        → IndeedApiScraper (default, uses JSearch RapidAPI)
    - ``"playwright"`` → IndeedScraper (Playwright + BeautifulSoup fallback)
    """
    # Instantiate a fresh Settings() so env var overrides in tests are picked up
    from src.config.settings import Settings

    fresh = Settings()  # type: ignore[call-arg]
    if fresh.indeed_mode == "playwright":
        return IndeedScraper()
    return IndeedApiScraper(api_key=fresh.indeed_api_key)


__all__ = [
    "IndeedApiScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "WTTJScraper",
    "get_indeed_scraper",
]
