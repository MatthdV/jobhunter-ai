"""Settings endpoints — profile YAML, API keys, preferences."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth.service import decrypt_api_key, encrypt_api_key
from api.dependencies import get_current_user, get_db
from src.config.settings import settings as app_settings
from src.storage.models import User

router = APIRouter(tags=["settings"])


class SettingsResponse(BaseModel):
    llm_provider: str
    min_match_score: int
    max_apps_per_day: int
    active_sources: str
    dry_run: bool
    profile_yaml: str | None
    has_api_key: bool
    api_key: None = None


class SettingsUpdateRequest(BaseModel):
    llm_provider: str | None = None
    min_match_score: int | None = None
    max_apps_per_day: int | None = None
    active_sources: str | None = None
    dry_run: bool | None = None
    profile_yaml: str | None = None
    api_key: str | None = None


@router.get("/settings", response_model=SettingsResponse)
def get_settings(user: User = Depends(get_current_user)) -> SettingsResponse:
    return SettingsResponse(
        llm_provider=user.llm_provider or "anthropic",
        min_match_score=user.min_match_score or 80,
        max_apps_per_day=user.max_apps_per_day or 10,
        active_sources=user.active_sources or "wttj",
        dry_run=user.dry_run if user.dry_run is not None else True,
        profile_yaml=user.profile_yaml,
        has_api_key=bool(user.encrypted_keys),
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    if body.llm_provider is not None:
        user.llm_provider = body.llm_provider
    if body.min_match_score is not None:
        user.min_match_score = body.min_match_score
    if body.max_apps_per_day is not None:
        user.max_apps_per_day = body.max_apps_per_day
    if body.active_sources is not None:
        user.active_sources = body.active_sources
    if body.dry_run is not None:
        user.dry_run = body.dry_run
    if body.profile_yaml is not None:
        user.profile_yaml = body.profile_yaml
    if body.api_key is not None and app_settings.fernet_key:
        provider = body.llm_provider or user.llm_provider or "anthropic"
        user.encrypted_keys = encrypt_api_key(
            app_settings.fernet_key, provider, body.api_key, user.encrypted_keys
        )
    db.add(user)
    db.commit()
    db.refresh(user)
    return get_settings(user)
