"""Per-user settings resolution — merges global .env with user's encrypted credentials."""

from __future__ import annotations

import logging
from typing import Any

from src.api.security import decrypt_keys
from src.config.settings import settings
from src.storage.models import User

logger = logging.getLogger(__name__)

# Credential fields stored per-user in encrypted_keys.
# Global/Railway-only keys (Adzuna, France Travail, Indeed) are NOT here.
_CREDENTIAL_FIELDS = (
    "anthropic_api_key",
    "openai_api_key",
    "mistral_api_key",
    "deepseek_api_key",
    "openrouter_api_key",
    "gmail_client_id",
    "gmail_client_secret",
    "gmail_refresh_token",
    "gmail_user_email",
    "telegram_bot_token",
    "telegram_chat_id",
    "linkedin_email",
    "linkedin_password",
    "wttj_email",
    "wttj_password",
    "hunter_api_key",
    "brave_api_key",
)


def get_settings_for_user(user: User) -> dict[str, Any]:
    """Return effective settings dict for *user*.

    Merge order (later wins):
    1. Global settings from .env
    2. User's encrypted credentials from DB
    3. User model fields (llm_provider, min_match_score, etc.)

    Returns a plain dict — not a Settings instance — so callers can pass
    individual fields to sub-components (Scorer, scrapers, JobScheduler)
    without importing the pydantic model.
    """
    # LLM API keys are user-owned — no global fallback (would bill the server operator).
    # Users must configure their own key in Settings → Credentials.
    # Infrastructure keys (Adzuna, France Travail, Indeed) stay global-only below.
    merged: dict[str, Any] = {
        "anthropic_api_key": "",
        "openai_api_key": "",
        "mistral_api_key": "",
        "deepseek_api_key": "",
        "openrouter_api_key": "",
        "gmail_client_id": "",
        "gmail_client_secret": "",
        "gmail_refresh_token": "",
        "gmail_user_email": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "linkedin_email": "",
        "linkedin_password": "",
        "wttj_email": "",
        "wttj_password": "",
        "hunter_api_key": "",
        "brave_api_key": "",
        # Railway-only keys — never overridden per-user
        "indeed_api_key": settings.indeed_api_key,
        "adzuna_app_id": settings.adzuna_app_id,
        "adzuna_api_key": settings.adzuna_api_key,
        "france_travail_client_id": settings.france_travail_client_id,
        "france_travail_client_secret": settings.france_travail_client_secret,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_scoring_provider": settings.llm_scoring_provider,
        "llm_scoring_model": settings.llm_scoring_model,
        "dry_run": settings.dry_run,
        "min_match_score": settings.min_match_score,
        "max_applications_per_day": settings.max_applications_per_day,
    }

    # Override with user's stored credentials (non-empty values only)
    if user.encrypted_keys and settings.fernet_key:
        user_keys = decrypt_keys(user.encrypted_keys, settings.fernet_key)
        for field in _CREDENTIAL_FIELDS:
            val = user_keys.get(field)
            if val:  # skip empty/None — keep global fallback
                merged[field] = val
    elif user.encrypted_keys and not settings.fernet_key:
        logger.warning(
            "User %d has encrypted_keys but FERNET_KEY is not set — cannot decrypt",
            user.id,
        )

    # User model fields override everything (explicit per-user config)
    if user.llm_provider:
        merged["llm_provider"] = user.llm_provider
    if user.min_match_score is not None:
        merged["min_match_score"] = user.min_match_score
    if user.max_apps_per_day is not None:
        merged["max_applications_per_day"] = user.max_apps_per_day
    merged["dry_run"] = user.dry_run  # always use user's dry_run preference
    if user.followup_delay_days is not None:
        merged["followup_delay_days"] = user.followup_delay_days

    return merged


def get_credential_names(user: User) -> list[str]:
    """Return list of credential field names that the user has stored in DB."""
    if not user.encrypted_keys or not settings.fernet_key:
        return []
    user_keys = decrypt_keys(user.encrypted_keys, settings.fernet_key)
    return [k for k in _CREDENTIAL_FIELDS if user_keys.get(k)]


# Credential fields that are set globally (Railway ENV) and never entered by users.
_GLOBAL_ONLY_FIELDS: dict[str, str] = {
    "adzuna_app_id": "adzuna_app_id",
    "adzuna_api_key": "adzuna_api_key",
    "france_travail_client_id": "france_travail_client_id",
    "france_travail_client_secret": "france_travail_client_secret",
    "indeed_api_key": "indeed_api_key",
}


def get_global_credential_names() -> list[str]:
    """Return credential field names that are configured in global Railway ENV.

    These are never stored in user DB — they come from server-side env vars only.
    """
    return [
        field
        for field, attr in _GLOBAL_ONLY_FIELDS.items()
        if getattr(settings, attr, "")
    ]
