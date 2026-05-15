"""FastAPI dependency injectors for authentication."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from src.api.security import decode_access_token
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

logger = logging.getLogger(__name__)

_COOKIE_NAME = "access_token"


def _get_user_from_request(request: Request) -> User | None:
    """Extract and validate JWT cookie; return User or None."""
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    if not settings.is_jwt_configured:
        logger.error("jwt_secret not configured — auth cannot function")
        return None
    user_id = decode_access_token(token, settings.jwt_secret)
    if user_id is None:
        return None
    with get_session() as session:
        user = session.get(User, user_id)
        # Expunge so the object can be used outside the session context
        if user is not None:
            session.expunge(user)
        return user


def get_current_user(request: Request) -> User:
    """Dependency for JSON API routes — raises 401 on missing/invalid token."""
    user = _get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_user_redirect(request: Request) -> User:
    """Dependency for HTML page routes — redirects to /login on missing/invalid token.

    Use this instead of get_current_user in page routes so the browser gets
    a 307 redirect rather than a bare 401 JSON response.
    """
    user = _get_user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/login"},
            detail="Login required",
        )
    return user


def get_current_user_optional(request: Request) -> User | None:
    """Dependency that returns None instead of raising when unauthenticated.

    Useful for routes that are partially public (e.g. health checks).
    """
    return _get_user_from_request(request)
