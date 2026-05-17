"""Authentication routes — register, login, logout."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.api.i18n import TRANSLATIONS
from src.api.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_COOKIE_NAME = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 24  # 24 hours in seconds


def _set_auth_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True in production with HTTPS
    )


# ---------------------------------------------------------------------------
# GET routes (login / register pages) — included in app.py directly
# ---------------------------------------------------------------------------


def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "login.html", {"error": error, "t": TRANSLATIONS["fr"], "current_lang": "fr"}
    )


def register_page(request: Request, error: str | None = None) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "register.html", {"error": error, "t": TRANSLATIONS["fr"], "current_lang": "fr"}
    )


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------


@router.post("/register", response_model=None)
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    """Create a new user account and set auth cookie."""
    # Basic validation
    if password != password_confirm:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Les mots de passe ne correspondent pas."},
            status_code=400,
        )
    if len(password) < 8:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Mot de passe trop court (8 caractères minimum)."},
            status_code=400,
        )

    if not settings.is_jwt_configured:
        raise HTTPException(
            status_code=503,
            detail="JWT_SECRET not configured on this instance.",
        )

    with get_session() as session:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            return _templates.TemplateResponse(
                request,
                "register.html",
                {"error": "Un compte existe déjà avec cet email."},
                status_code=400,
            )

        user = User(
            email=email,
            hashed_password=hash_password(password),
        )
        session.add(user)
        session.flush()
        user_id = user.id

    token = create_access_token(user_id, settings.jwt_secret)
    response = RedirectResponse(url="/", status_code=303)
    _set_auth_cookie(response, token)
    logger.info("New user registered: %s (id=%d)", email, user_id)
    return response


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


@router.post("/login", response_model=None)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    """Authenticate and set JWT HTTPOnly cookie."""
    if not settings.is_jwt_configured:
        raise HTTPException(
            status_code=503,
            detail="JWT_SECRET not configured on this instance.",
        )

    with get_session() as session:
        user = session.query(User).filter(User.email == email).first()
        if user is None or not verify_password(password, user.hashed_password):
            return _templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Email ou mot de passe incorrect."},
                status_code=401,
            )
        user_id = user.id

    token = create_access_token(user_id, settings.jwt_secret)
    response = RedirectResponse(url="/", status_code=303)
    _set_auth_cookie(response, token)
    logger.info("User logged in: %s (id=%d)", email, user_id)
    return response


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


@router.post("/logout", response_model=None)
def logout() -> RedirectResponse:
    """Clear auth cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=_COOKIE_NAME)
    return response
