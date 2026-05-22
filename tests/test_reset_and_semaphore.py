"""Tests for password-reset tokens and the Playwright browser semaphore."""

from __future__ import annotations

import asyncio

import pytest

from src.api.security import (
    create_access_token,
    create_reset_token,
    decode_reset_token,
)


_SECRET = "x" * 40


class TestResetToken:
    def test_round_trip(self):
        token = create_reset_token(42, _SECRET)
        assert decode_reset_token(token, _SECRET) == 42

    def test_access_token_rejected_as_reset(self):
        # An access token must not be usable as a reset token (wrong type claim).
        access = create_access_token(42, _SECRET)
        assert decode_reset_token(access, _SECRET) is None

    def test_garbage_rejected(self):
        assert decode_reset_token("not-a-token", _SECRET) is None

    def test_wrong_secret_rejected(self):
        token = create_reset_token(42, _SECRET)
        assert decode_reset_token(token, "y" * 40) is None


class TestBrowserSemaphore:
    """The gate must serialize browser scrapers but never block HTTP scrapers."""

    def test_http_scraper_does_not_acquire_slot(self):
        from src.scrapers import base

        class _HttpScraper(base.BaseScraper):
            source = "http_test"
            USES_BROWSER = False

            async def _fetch_raw(self, *a, **k):
                return []

            async def _parse_raw(self, raw):  # pragma: no cover - never called
                raise NotImplementedError

        async def _run():
            # Exhaust the semaphore entirely.
            for _ in range(base.settings.max_concurrent_browsers):
                await base._BROWSER_SEMAPHORE.acquire()
            try:
                # An HTTP scraper must still enter/exit without blocking.
                async with _HttpScraper():
                    pass
            finally:
                for _ in range(base.settings.max_concurrent_browsers):
                    base._BROWSER_SEMAPHORE.release()

        # If the HTTP scraper tried to acquire, this would deadlock → timeout.
        asyncio.run(asyncio.wait_for(_run(), timeout=2.0))

    def test_browser_scraper_releases_slot_on_exit(self):
        from src.scrapers import base

        class _BrowserScraper(base.BaseScraper):
            source = "browser_test"
            USES_BROWSER = True

            async def _setup(self):
                pass

            async def _teardown(self):
                pass

            async def _fetch_raw(self, *a, **k):
                return []

            async def _parse_raw(self, raw):  # pragma: no cover
                raise NotImplementedError

        async def _run():
            before = base._BROWSER_SEMAPHORE._value
            async with _BrowserScraper():
                assert base._BROWSER_SEMAPHORE._value == before - 1
            assert base._BROWSER_SEMAPHORE._value == before

        asyncio.run(asyncio.wait_for(_run(), timeout=2.0))

    def test_browser_slot_released_when_setup_fails(self):
        from src.scrapers import base

        class _BoomScraper(base.BaseScraper):
            source = "boom_test"
            USES_BROWSER = True

            async def _setup(self):
                raise RuntimeError("launch failed")

            async def _fetch_raw(self, *a, **k):
                return []

            async def _parse_raw(self, raw):  # pragma: no cover
                raise NotImplementedError

        async def _run():
            before = base._BROWSER_SEMAPHORE._value
            with pytest.raises(RuntimeError):
                async with _BoomScraper():
                    pass
            # Slot must not leak after a failed setup.
            assert base._BROWSER_SEMAPHORE._value == before

        asyncio.run(asyncio.wait_for(_run(), timeout=2.0))
