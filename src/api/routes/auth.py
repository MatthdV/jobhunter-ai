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
    create_reset_token,
    decode_reset_token,
    hash_password,
    verify_password,
)
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

# Minimal profile injected for every new user.
# job_sources ensures the scan phase doesn't abort immediately.
# search_terms is intentionally empty — user fills them in Settings.
_DEFAULT_PROFILE_YAML = """\
# Profil jobhunter-ai
# Remplis les champs search_terms pour lancer un scan.

candidate:
  name: ''
  title: ''
  location: ''

job_sources:
  - name: wttj
    enabled: true
    search_terms: []
    location: ''
    countries: [FR]
    work_modes: [remote]
    auto_translate: false
  - name: adzuna
    enabled: true
    search_terms: []
    location: ''
    countries: [FR]
    work_modes: [remote]
    auto_translate: false
  - name: france_travail
    enabled: true
    search_terms: []
    location: ''
    countries: [FR]
    work_modes: [remote]
    auto_translate: false
"""

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
        secure=settings.cookie_secure,  # COOKIE_SECURE=false for plain-HTTP deploys
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


def forgot_password_page(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "forgot_password.html", {"t": TRANSLATIONS["fr"], "current_lang": "fr"}
    )


def reset_password_page(request: Request, token: str = "") -> HTMLResponse:
    """Render the reset form only if the token is valid; else offer a new link."""
    token_valid = False
    error: str | None = None
    if not settings.is_jwt_configured:
        error = "JWT_SECRET non configuré sur cette instance."
    elif decode_reset_token(token, settings.jwt_secret) is not None:
        token_valid = True
    else:
        error = "Lien de réinitialisation invalide ou expiré."
    return _templates.TemplateResponse(
        request,
        "reset_password.html",
        {
            "token": token,
            "token_valid": token_valid,
            "error": error,
            "t": TRANSLATIONS["fr"],
            "current_lang": "fr",
        },
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
    # Registration gate — set REGISTRATION_OPEN=false on Railway after accounts created
    if not settings.registration_open:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Les inscriptions sont fermées. Contacte l'administrateur.", "t": TRANSLATIONS["fr"], "current_lang": "fr"},
            status_code=403,
        )

    # Basic validation
    if password != password_confirm:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Les mots de passe ne correspondent pas.", "t": TRANSLATIONS["fr"], "current_lang": "fr"},
            status_code=400,
        )
    if len(password) < 8:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Mot de passe trop court (8 caractères minimum).", "t": TRANSLATIONS["fr"], "current_lang": "fr"},
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
                {"error": "Un compte existe déjà avec cet email.", "t": TRANSLATIONS["fr"], "current_lang": "fr"},
                status_code=400,
            )

        user = User(
            email=email,
            hashed_password=hash_password(password),
            profile_yaml=_DEFAULT_PROFILE_YAML,
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
                {"error": "Email ou mot de passe incorrect.", "t": TRANSLATIONS["fr"], "current_lang": "fr"},
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


# ---------------------------------------------------------------------------
# Password reset — token shown on screen (no email dependency)
# ---------------------------------------------------------------------------


@router.post("/forgot-password", response_model=None)
def forgot_password(
    request: Request,
    email: str = Form(...),
) -> HTMLResponse:
    """Generate a reset link for the given email.

    Always renders the same success view whether or not the account exists,
    to avoid account enumeration. The link is shown on screen (concierge beta
    has no email delivery configured).
    """
    if not settings.is_jwt_configured:
        raise HTTPException(status_code=503, detail="JWT_SECRET not configured on this instance.")

    reset_link: str | None = None
    with get_session() as session:
        user = session.query(User).filter(User.email == email).first()
        if user is not None:
            token = create_reset_token(user.id, settings.jwt_secret)
            _proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            _base = str(request.base_url).rstrip("/")
            if _base.startswith("http://") and _proto == "https":
                _base = "https://" + _base[len("http://"):]
            reset_link = f"{_base}/reset-password?token={token}"

    # When the account doesn't exist, present a generic copy without a link.
    context = {"t": TRANSLATIONS["fr"], "current_lang": "fr"}
    if reset_link:
        context["reset_link"] = reset_link
    else:
        context["reset_link"] = ""
        context["error"] = (
            "Si un compte existe pour cet email, un lien a été généré. "
            "Vérifie l'adresse saisie."
        )
    return _templates.TemplateResponse(request, "forgot_password.html", context)


@router.post("/reset-password", response_model=None)
def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    """Validate the reset token and set the new password."""
    if not settings.is_jwt_configured:
        raise HTTPException(status_code=503, detail="JWT_SECRET not configured on this instance.")

    def _err(msg: str) -> HTMLResponse:
        return _templates.TemplateResponse(
            request,
            "reset_password.html",
            {"token": token, "token_valid": True, "error": msg,
             "t": TRANSLATIONS["fr"], "current_lang": "fr"},
            status_code=400,
        )

    user_id = decode_reset_token(token, settings.jwt_secret)
    if user_id is None:
        return _templates.TemplateResponse(
            request,
            "reset_password.html",
            {"token": token, "token_valid": False,
             "error": "Lien de réinitialisation invalide ou expiré.",
             "t": TRANSLATIONS["fr"], "current_lang": "fr"},
            status_code=400,
        )
    if password != password_confirm:
        return _err("Les mots de passe ne correspondent pas.")
    if len(password) < 8:
        return _err("Mot de passe trop court (8 caractères minimum).")

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return _err("Compte introuvable.")
        user.hashed_password = hash_password(password)  # type: ignore[assignment]

    logger.info("Password reset for user id=%d", user_id)
    return RedirectResponse(url="/login", status_code=303)
