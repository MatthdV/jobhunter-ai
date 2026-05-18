"""Per-user settings resolution — merges global .env with user's encrypted credentials."""

from __future__ import annotations

import logging
from typing import Any

from src.api.security import decrypt_keys
from src.config.settings import settings
from src.storage.models import User

logger = logging.getLogger(__name__)

# All credential fields stored in User.encrypted_keys
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
    "indeed_api_key",
    "france_travail_client_id",
    "france_travail_client_secret",
    "adzuna_app_id",
    "adzuna_app_key",
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
    # Start from global .env
    merged: dict[str, Any] = {
        "anthropic_api_key": settings.anthropic_api_key,
        "openai_api_key": settings.openai_api_key,
        "mistral_api_key": settings.mistral_api_key,
        "deepseek_api_key": settings.deepseek_api_key,
        "openrouter_api_key": settings.openrouter_api_key,
        "gmail_client_id": settings.gmail_client_id,
        "gmail_client_secret": settings.gmail_client_secret,
        "gmail_refresh_token": settings.gmail_refresh_token,
        "gmail_user_email": settings.gmail_user_email,
        "telegram_bot_token": settings.telegram_bot_token,
        "telegram_chat_id": settings.telegram_chat_id,
        "linkedin_email": settings.linkedin_email,
        "linkedin_password": settings.linkedin_password,
        "wttj_email": settings.wttj_email,
        "wttj_password": settings.wttj_password,
        "indeed_api_key": settings.indeed_api_key,
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

    return merged


def get_credential_names(user: User) -> list[str]:
    """Return list of credential field names that the user has stored.

    Does not return values — only which keys are present.
    """
    if not user.encrypted_keys or not settings.fernet_key:
        return []
    user_keys = decrypt_keys(user.encrypted_keys, settings.fernet_key)
    return [k for k in _CREDENTIAL_FIELDS if user_keys.get(k)]
