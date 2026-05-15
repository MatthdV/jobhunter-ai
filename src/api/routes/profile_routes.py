"""Profile and credential management routes."""

from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.api.security import encrypt_keys
from src.api.user_settings import _CREDENTIAL_FIELDS, get_credential_names
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Profile YAML
# ---------------------------------------------------------------------------


class ProfileOut(BaseModel):
    profile_yaml: str | None


class ProfileIn(BaseModel):
    profile_yaml: str


@router.get("/profile", response_model=ProfileOut)
def get_profile(current_user: User = Depends(get_current_user)) -> ProfileOut:
    """Return the current user's raw profile YAML."""
    return ProfileOut(profile_yaml=current_user.profile_yaml)


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    body: ProfileIn,
    current_user: User = Depends(get_current_user),
) -> ProfileOut:
    """Update the current user's profile YAML.

    Validates that the YAML parses correctly before storing.
    """
    try:
        yaml.safe_load(body.profile_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = body.profile_yaml  # type: ignore[assignment]

    return ProfileOut(profile_yaml=body.profile_yaml)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class CredentialsOut(BaseModel):
    """Which credential fields the user has stored (names only, not values)."""
    stored_keys: list[str]
    available_keys: list[str]  # all possible credential fields


class CredentialsIn(BaseModel):
    """Partial dict of credential values to store (only provided keys updated)."""
    credentials: dict[str, str]


@router.get("/credentials", response_model=CredentialsOut)
def get_credentials(current_user: User = Depends(get_current_user)) -> CredentialsOut:
    """Return which credential keys the user has stored (not their values)."""
    stored = get_credential_names(current_user)
    return CredentialsOut(
        stored_keys=stored,
        available_keys=list(_CREDENTIAL_FIELDS),
    )


@router.put("/credentials", response_model=CredentialsOut)
def update_credentials(
    body: CredentialsIn,
    current_user: User = Depends(get_current_user),
) -> CredentialsOut:
    """Store encrypted credential values for the current user.

    Only the provided keys are updated; existing keys not in the request
    are preserved. Requires FERNET_KEY to be set on the instance.
    """
    if not settings.fernet_key:
        raise HTTPException(
            status_code=503,
            detail="FERNET_KEY not configured on this instance — cannot store credentials.",
        )

    # Validate field names
    unknown = [k for k in body.credentials if k not in _CREDENTIAL_FIELDS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown credential fields: {unknown}. Valid: {list(_CREDENTIAL_FIELDS)}",
        )

    from src.api.security import decrypt_keys

    # Load existing credentials and merge
    existing: dict[str, str] = {}
    if current_user.encrypted_keys:
        existing = decrypt_keys(current_user.encrypted_keys, settings.fernet_key)

    # Merge: only update provided, non-empty keys
    for k, v in body.credentials.items():
        if v:
            existing[k] = v
        else:
            existing.pop(k, None)  # empty string = delete key

    encrypted_blob = encrypt_keys(existing, settings.fernet_key)

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.encrypted_keys = encrypted_blob  # type: ignore[assignment]

    # Reload stored keys for response
    from src.api.user_settings import get_credential_names as _get_names
    # Need fresh user object with updated encrypted_keys
    with get_session() as session:
        fresh_user = session.get(User, current_user.id)
        if fresh_user:
            session.expunge(fresh_user)

    stored = [k for k in _CREDENTIAL_FIELDS if existing.get(k)]
    return CredentialsOut(
        stored_keys=stored,
        available_keys=list(_CREDENTIAL_FIELDS),
    )
