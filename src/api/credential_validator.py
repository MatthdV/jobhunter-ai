"""Best-effort live validation of user credentials at save time.

Each validator makes one cheap authenticated call to the provider and maps the
result to a status string:
  "ok"          — the key authenticated successfully
  "invalid"     — the provider rejected the key (401/403)
  "unreachable" — network error / timeout / provider 5xx (key not judged)
  "untested"    — no cheap check exists for this field (stored as-is)
Validation never blocks the save — the caller stores the keys regardless and
returns the statuses for display.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 12.0


def _status_from_code(code: int) -> str:
    if 200 <= code < 300:
        return "ok"
    if code in (401, 403):
        return "invalid"
    if code == 429:  # rate-limited = key exists and is active
        return "ok"
    return "unreachable"


async def _check_get(client: httpx.AsyncClient, url: str,
                     headers: dict | None = None, params: dict | None = None) -> str:
    try:
        resp = await client.get(url, headers=headers, params=params)
        return _status_from_code(resp.status_code)
    except Exception as exc:
        logger.warning("Credential check failed for %s: %s", url, exc)
        return "unreachable"


async def _check_anthropic(client: httpx.AsyncClient, key: str) -> str:
    # GET /v1/models — cheap, no tokens billed
    return await _check_get(
        client,
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )


async def _check_openai(client: httpx.AsyncClient, key: str) -> str:
    return await _check_get(client, "https://api.openai.com/v1/models",
                            headers={"Authorization": f"Bearer {key}"})


async def _check_mistral(client: httpx.AsyncClient, key: str) -> str:
    return await _check_get(client, "https://api.mistral.ai/v1/models",
                            headers={"Authorization": f"Bearer {key}"})


async def _check_deepseek(client: httpx.AsyncClient, key: str) -> str:
    return await _check_get(client, "https://api.deepseek.com/models",
                            headers={"Authorization": f"Bearer {key}"})


async def _check_openrouter(client: httpx.AsyncClient, key: str) -> str:
    # /api/v1/key returns the key's own metadata — authenticates without billing
    return await _check_get(client, "https://openrouter.ai/api/v1/key",
                            headers={"Authorization": f"Bearer {key}"})


async def _check_hunter(client: httpx.AsyncClient, key: str) -> str:
    return await _check_get(client, "https://api.hunter.io/v2/account",
                            params={"api_key": key})


async def _check_brave(client: httpx.AsyncClient, key: str) -> str:
    return await _check_get(client, "https://api.search.brave.com/res/v1/web/search",
                            params={"q": "ping", "count": 1},
                            headers={"X-Subscription-Token": key})


async def _check_telegram(client: httpx.AsyncClient, token: str) -> str:
    return await _check_get(client, f"https://api.telegram.org/bot{token}/getMe")


_CHECKERS = {
    "anthropic_api_key": _check_anthropic,
    "openai_api_key": _check_openai,
    "mistral_api_key": _check_mistral,
    "deepseek_api_key": _check_deepseek,
    "openrouter_api_key": _check_openrouter,
    "hunter_api_key": _check_hunter,
    "brave_api_key": _check_brave,
    "telegram_bot_token": _check_telegram,
}


async def validate_credentials(credentials: dict[str, str]) -> dict[str, str]:
    """Validate the provided non-empty credentials concurrently.

    Returns {field_name: status} for every non-empty field in *credentials*.
    Fields without a checker (Gmail OAuth trio, WTTJ/LinkedIn passwords…)
    are reported as "untested".
    """
    to_check = {k: v for k, v in credentials.items() if v}
    if not to_check:
        return {}

    results: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tasks = {}
        for field, value in to_check.items():
            checker = _CHECKERS.get(field)
            if checker is None:
                results[field] = "untested"
            else:
                tasks[field] = checker(client, value)
        if tasks:
            statuses = await asyncio.gather(*tasks.values())
            results.update(dict(zip(tasks.keys(), statuses)))
    return results
