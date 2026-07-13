"""Tests for src/api/credential_validator.py."""

import pytest

from src.api import credential_validator as cv
from src.api.credential_validator import validate_credentials


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Maps URL substrings to status codes."""

    routes: dict[str, int] = {}
    raises: bool = False

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        if _FakeAsyncClient.raises:
            raise ConnectionError("network down")
        for fragment, code in _FakeAsyncClient.routes.items():
            if fragment in url:
                return _FakeResponse(code)
        return _FakeResponse(200)


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    _FakeAsyncClient.routes = {}
    _FakeAsyncClient.raises = False
    monkeypatch.setattr(cv.httpx, "AsyncClient", _FakeAsyncClient)


async def test_valid_keys_report_ok():
    result = await validate_credentials(
        {"anthropic_api_key": "sk-ant-x", "hunter_api_key": "hk"}
    )
    assert result == {"anthropic_api_key": "ok", "hunter_api_key": "ok"}


async def test_rejected_key_reports_invalid():
    _FakeAsyncClient.routes = {"api.anthropic.com": 401}
    result = await validate_credentials({"anthropic_api_key": "bad"})
    assert result == {"anthropic_api_key": "invalid"}


async def test_rate_limited_key_counts_as_ok():
    _FakeAsyncClient.routes = {"api.search.brave.com": 429}
    result = await validate_credentials({"brave_api_key": "k"})
    assert result == {"brave_api_key": "ok"}


async def test_provider_5xx_reports_unreachable():
    _FakeAsyncClient.routes = {"openrouter.ai": 503}
    result = await validate_credentials({"openrouter_api_key": "k"})
    assert result == {"openrouter_api_key": "unreachable"}


async def test_network_error_reports_unreachable():
    _FakeAsyncClient.raises = True
    result = await validate_credentials({"anthropic_api_key": "k"})
    assert result == {"anthropic_api_key": "unreachable"}


async def test_fields_without_checker_report_untested():
    result = await validate_credentials(
        {"gmail_client_id": "x", "wttj_password": "y"}
    )
    assert result == {"gmail_client_id": "untested", "wttj_password": "untested"}


async def test_empty_values_are_skipped():
    result = await validate_credentials({"anthropic_api_key": ""})
    assert result == {}
