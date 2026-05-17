"""Scrapers package — exports all scrapers and factory functions."""

from src.scrapers.career_pages import CareerPageScraper
from src.scrapers.gmail_scraper import GmailJobAlertScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.indeed_api import IndeedApiScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.wttj import WTTJScraper


def get_indeed_scraper(user_id: int | None = None) -> IndeedScraper | IndeedApiScraper:
    """Return the configured Indeed scraper instance.

    Reads ``settings.indeed_mode``:
    - ``"api"``        → IndeedApiScraper (default, uses JSearch RapidAPI)
    - ``"playwright"`` → IndeedScraper (Playwright + BeautifulSoup fallback)

    Args:
        user_id: If provided, all scraped Job objects will have this user_id set.
    """
    # Instantiate a fresh Settings() so env var overrides in tests are picked up
    from src.config.settings import Settings

    fresh = Settings()  # type: ignore[call-arg]
    if fresh.indeed_mode == "playwright":
        return IndeedScraper(user_id=user_id)
    # Pass empty api_key — IndeedApiScraper resolves per-user key in __init__
    return IndeedApiScraper(api_key="", user_id=user_id)


__all__ = [
    "CareerPageScraper",
    "GmailJobAlertScraper",
    "IndeedApiScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "WTTJScraper",
    "get_indeed_scraper",
]
