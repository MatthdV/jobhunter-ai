"""Profile and credential management routes."""

from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.api.security import encrypt_keys
from src.api.user_settings import (
    _CREDENTIAL_FIELDS,
    get_credential_names,
    get_settings_for_user,
)
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

# Default job_source entry added when a source is first enabled via the UI
_DEFAULT_SOURCE_ENTRY: dict[str, object] = {
    "enabled": True,
    "search_terms": [],
    "location": "",
    "countries": ["FR"],
    "work_modes": ["remote"],
    "auto_translate": False,
}

AVAILABLE_SOURCES = ["wttj", "indeed", "linkedin", "adzuna", "france_travail"]


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
# LinkedIn PDF import → profile YAML
# ---------------------------------------------------------------------------

# Sections written from the LinkedIn PDF. Strategy sections (job_sources,
# target_roles, search, filters, archetypes…) are preserved untouched so the
# import never wipes a user's scan config.
_IMPORTED_SECTIONS = ("candidate", "skills", "experiences", "education", "projects")

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/profile/import-linkedin", response_model=ProfileOut)
async def import_linkedin_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> ProfileOut:
    """Build/merge the user's profile from an exported LinkedIn profile PDF.

    Uses the user's own configured LLM. Merges extracted candidate/skills/
    experiences/education/projects into the existing profile_yaml, preserving
    job_sources and other strategy sections. The result is returned for review.
    """
    from src.importers.linkedin_pdf import (
        LinkedInPdfError,
        extract_text,
        profile_from_pdf,
    )
    from src.llm.factory import get_client

    if (file.content_type or "") not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=422, detail="Le fichier doit être un PDF.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="Fichier vide.")
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF trop volumineux (max 10 Mo).")

    # Build an LLM client from the user's configured provider + key.
    # Auto-detect: try the configured provider first, then fall back to any
    # provider that has a key — so users with OpenRouter don't need to manually
    # set llm_provider when the Railway default is "anthropic".
    user_cfg = get_settings_for_user(current_user)
    _preferred = user_cfg.get("llm_provider", settings.llm_provider)
    _providers_to_try = [_preferred] + [
        p for p in ("openrouter", "anthropic", "openai", "mistral", "deepseek")
        if p != _preferred
    ]
    provider, api_key = None, ""
    for _p in _providers_to_try:
        _key = user_cfg.get(f"{_p}_api_key", "")
        if _key:
            provider, api_key = _p, _key
            break
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Aucune clé API LLM configurée. Ajoute ta clé dans les identifiants d'abord.",
        )
    model = user_cfg.get("llm_model") or None
    client = get_client(provider, model=model, api_key=api_key)

    try:
        text = extract_text(pdf_bytes)
        extracted = await profile_from_pdf(text, client)
    except LinkedInPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("LinkedIn PDF import failed for user %d", current_user.id)
        raise HTTPException(status_code=502, detail=f"Échec de l'extraction IA : {exc}") from exc

    # Merge into existing profile, preserving non-imported (strategy) sections.
    existing: dict = {}
    if current_user.profile_yaml:
        try:
            existing = yaml.safe_load(current_user.profile_yaml) or {}
        except yaml.YAMLError:
            existing = {}
    for key in _IMPORTED_SECTIONS:
        if key in extracted and extracted[key] not in (None, "", []):
            existing[key] = extracted[key]

    merged_yaml = yaml.safe_dump(existing, allow_unicode=True, sort_keys=False)

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = merged_yaml  # type: ignore[assignment]

    return ProfileOut(profile_yaml=merged_yaml)


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

    stored = [k for k in _CREDENTIAL_FIELDS if existing.get(k)]
    return CredentialsOut(
        stored_keys=stored,
        available_keys=list(_CREDENTIAL_FIELDS),
    )


# ---------------------------------------------------------------------------
# Source toggle
# ---------------------------------------------------------------------------


class SourceToggleIn(BaseModel):
    source: str   # "wttj" | "indeed" | "linkedin"
    enabled: bool


class SourcesOut(BaseModel):
    active_sources: list[str]


def _get_active_sources(profile: dict) -> list[str]:
    """Return names of enabled sources in profile job_sources."""
    return [
        s["name"] for s in profile.get("job_sources", [])
        if s.get("enabled", True) and s.get("name")
    ]


@router.post("/profile/sources", response_model=SourcesOut)
def toggle_source(
    body: SourceToggleIn,
    current_user: User = Depends(get_current_user),
) -> SourcesOut:
    """Enable or disable a job source in the user's profile YAML.

    Enabling adds a default entry if no entry for that source exists.
    Disabling sets ``enabled: false`` on all entries for that source.
    """
    if body.source not in AVAILABLE_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source '{body.source}'. Valid: {AVAILABLE_SOURCES}",
        )

    raw_yaml = current_user.profile_yaml or ""
    profile: dict = yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}

    sources: list[dict] = list(profile.get("job_sources", []))

    existing = [s for s in sources if s.get("name") == body.source]

    if body.enabled:
        if not existing:
            sources.append({"name": body.source, **_DEFAULT_SOURCE_ENTRY})
        else:
            for s in existing:
                s["enabled"] = True
    else:
        for s in existing:
            s["enabled"] = False

    profile["job_sources"] = sources
    updated_yaml = yaml.dump(profile, allow_unicode=True, sort_keys=False)

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = updated_yaml  # type: ignore[assignment]

    return SourcesOut(active_sources=_get_active_sources(profile))


@router.get("/profile/sources", response_model=SourcesOut)
def get_sources(current_user: User = Depends(get_current_user)) -> SourcesOut:
    """Return list of currently active source names."""
    raw_yaml = current_user.profile_yaml or ""
    profile: dict = yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}
    return SourcesOut(active_sources=_get_active_sources(profile))


# ---------------------------------------------------------------------------
# Candidate profile (structured form → YAML)
# ---------------------------------------------------------------------------


class CandidateProfileIn(BaseModel):
    name: str = ""
    title: str = ""
    experience_years: int | None = None
    location: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    tjm_min: int | None = None
    tjm_max: int | None = None
    skills: list[str] = []
    excluded_keywords: list[str] = []


@router.put("/profile/candidate")
def update_candidate_profile(
    body: CandidateProfileIn,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update candidate.*  salary.*  skills.*  filters.* in profile YAML."""
    raw_yaml = current_user.profile_yaml or ""
    profile: dict = yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}

    candidate = profile.setdefault("candidate", {})
    if body.name:
        candidate["name"] = body.name
    if body.title:
        candidate["title"] = body.title
    if body.experience_years is not None:
        candidate["experience_years"] = body.experience_years
    if body.location:
        candidate["location"] = body.location

    salary = profile.setdefault("salary", {})
    if body.salary_min is not None:
        salary["min_annual"] = body.salary_min
    if body.salary_max is not None:
        salary["max_annual"] = body.salary_max
    if body.tjm_min is not None:
        salary["min_daily_rate"] = body.tjm_min
    if body.tjm_max is not None:
        salary["max_daily_rate"] = body.tjm_max
    if body.salary_min is not None or body.salary_max is not None:
        salary.setdefault("currency", "EUR")

    if body.skills:
        skills = profile.setdefault("skills", {})
        skills["top_3"] = body.skills[:3]
        if len(body.skills) > 3:
            skills["additional"] = body.skills[3:]

    if body.excluded_keywords:
        filters = profile.setdefault("filters", {})
        filters["excluded_keywords"] = body.excluded_keywords

    updated_yaml = yaml.dump(profile, allow_unicode=True, sort_keys=False)
    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = updated_yaml  # type: ignore[assignment]

    return {"ok": True}


# ---------------------------------------------------------------------------
# Per-source config (keywords / location / work_modes)
# ---------------------------------------------------------------------------


class SourceConfigIn(BaseModel):
    source: str
    keywords: list[str] = []
    location: str = ""
    work_modes: list[str] = []


@router.put("/profile/source-config")
def update_source_config(
    body: SourceConfigIn,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update keywords, location, work_modes for a given source in profile YAML."""
    if body.source not in AVAILABLE_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source '{body.source}'. Valid: {AVAILABLE_SOURCES}",
        )

    raw_yaml = current_user.profile_yaml or ""
    profile: dict = yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}

    sources: list[dict] = list(profile.get("job_sources", []))
    existing = [s for s in sources if s.get("name") == body.source]

    if not existing:
        # Source not yet in YAML — create with defaults and apply config
        entry: dict = {"name": body.source, **_DEFAULT_SOURCE_ENTRY}
        sources.append(entry)
        existing = [entry]

    for s in existing:
        if body.keywords:
            s["search_terms"] = body.keywords
        if body.location:
            s["location"] = body.location
        if body.work_modes:
            s["work_modes"] = body.work_modes

    profile["job_sources"] = sources
    updated_yaml = yaml.dump(profile, allow_unicode=True, sort_keys=False)

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = updated_yaml  # type: ignore[assignment]

    return {"ok": True, "source": body.source}


# ---------------------------------------------------------------------------
# UI language preference
# ---------------------------------------------------------------------------

_SUPPORTED_LANGS = {"fr", "en", "es"}


class LangIn(BaseModel):
    language: str


@router.put("/profile/language")
def set_language(
    body: LangIn,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update ui.language in profile YAML."""
    if body.language not in _SUPPORTED_LANGS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported language '{body.language}'. Valid: {sorted(_SUPPORTED_LANGS)}",
        )

    raw_yaml = current_user.profile_yaml or ""
    profile: dict = yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}
    profile.setdefault("ui", {})["language"] = body.language
    updated_yaml = yaml.dump(profile, allow_unicode=True, sort_keys=False)

    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.profile_yaml = updated_yaml  # type: ignore[assignment]

    return {"ok": True, "language": body.language}
