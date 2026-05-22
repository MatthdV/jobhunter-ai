"""Pipeline phase trigger routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.background import tracker
from src.api.deps import get_current_user
from src.api.schemas import PipelineStartResponse, PipelineStatusResponse
from src.api.user_settings import get_settings_for_user
from src.config.profile import get_profile_for_user
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import Job, JobStatus, User

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Background phase implementations
# ---------------------------------------------------------------------------


_SOURCE_NAME_MAP = {
    "welcome_to_the_jungle": "wttj",
    "wttj": "wttj",
    "indeed": "indeed",
    "indeed_api": "indeed_api",
    "linkedin": "linkedin",
    "adzuna": "adzuna",
    "france_travail": "france_travail",
}

# Default sources injected when a user's profile has no job_sources section.
# search_terms is empty → each source is skipped by the keywords check, so
# no actual scraping runs — but the scan doesn't abort with an error either.
_DEFAULT_JOB_SOURCES: list[dict] = [
    {
        "name": "wttj",
        "enabled": True,
        "search_terms": [],
        "location": "",
        "countries": ["FR"],
        "work_modes": ["remote"],
        "auto_translate": False,
    },
    {
        "name": "adzuna",
        "enabled": True,
        "search_terms": [],
        "location": "",
        "countries": ["FR"],
        "work_modes": ["remote"],
        "auto_translate": False,
    },
    {
        "name": "france_travail",
        "enabled": True,
        "search_terms": [],
        "location": "",
        "countries": ["FR"],
        "work_modes": ["remote"],
        "auto_translate": False,
    },
]


def _load_job_sources_for_user(user: User) -> list[dict]:
    """Read enabled job_sources from the user's profile.

    Falls back to *_DEFAULT_JOB_SOURCES* when the profile is empty or
    has no job_sources section, so the scan phase never hard-aborts for
    users who haven't configured their sources yet.
    """
    try:
        profile = get_profile_for_user(user)
        sources = [s for s in profile.get("job_sources", []) if s.get("enabled", True)]
        if sources:
            return sources
    except Exception as exc:
        logger.warning("Could not load job_sources for user %d: %s", user.id, exc)
    return _DEFAULT_JOB_SOURCES


def _load_user(user_id: int) -> User | None:
    """Load a User from DB by id — used at start of background tasks."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            session.expunge(user)
        return user


async def _run_scan(user_id: int) -> None:
    """Scan phase: launch active scrapers and persist new jobs for *user_id*."""
    try:
        user = _load_user(user_id)
        if user is None:
            tracker.error("scan", f"User {user_id} not found", user_id=user_id)
            return

        job_sources = _load_job_sources_for_user(user)
        if not job_sources:
            tracker.error("scan", "No enabled job_sources in profile", user_id=user_id)
            return

        with get_session() as session:
            existing_urls: set[str] = {
                url for (url,) in session.query(Job.url).filter(Job.user_id == user_id).all()
            }

        new_count = 0
        for source in job_sources:
            source_key = _SOURCE_NAME_MAP.get(source.get("name", ""), "")
            keywords = source.get("search_terms", [])
            location = source.get("location", "")
            countries = source.get("countries", ["FR"])

            # Work modes — one request per mode; default remote for backward compat
            work_modes_raw = source.get("work_modes", ["remote"])
            work_modes = [m for m in work_modes_raw if m in ("remote", "hybrid", "on-site")] or ["remote"]

            # Auto-translate search terms to country language
            all_keywords = list(keywords)
            if source.get("auto_translate", False) and keywords:
                from src.scrapers.translate import detect_language, translate_keywords
                target_lang = detect_language(countries)
                if target_lang != "en":
                    llm_for_translate = None
                    try:
                        from src.llm.client import get_client
                        llm_for_translate = get_client()
                    except Exception:
                        pass
                    all_keywords = await translate_keywords(
                        keywords, target_lang, llm_client=llm_for_translate
                    )

            if not source_key or not keywords:
                logger.warning(
                    "Skipping source %r — missing name or search_terms",
                    source.get("name"),
                )
                continue

            # Validate source_key loads before iterating work_modes
            try:
                if source_key == "wttj":
                    from src.scrapers.wttj import WTTJScraper as _SC  # noqa: F401
                elif source_key == "indeed":
                    from src.scrapers import get_indeed_scraper as _SC  # noqa: F401
                elif source_key == "indeed_api":
                    from src.scrapers.indeed_api import IndeedApiScraper as _SC  # noqa: F401
                elif source_key == "linkedin":
                    from src.scrapers.linkedin import LinkedInScraper as _SC  # noqa: F401
                elif source_key == "adzuna":
                    from src.scrapers.adzuna import AdzunaScraper as _SC  # noqa: F401
                elif source_key == "france_travail":
                    from src.scrapers.france_travail import FranceTravailScraper as _SC  # noqa: F401
                else:
                    logger.warning("Unknown source_key %r — skipping", source_key)
                    continue
            except Exception as exc:
                logger.warning("Could not import scraper for %r: %s", source_key, exc)
                continue

            from src.scrapers.filters import ScraperFilters
            max_days_old = user.max_days_old if hasattr(user, "max_days_old") else 30
            for work_mode in work_modes:
                # Fresh scraper per (source, work_mode): ensures __aenter__/__aexit__
                # are called on a clean object and the browser semaphore slot is
                # never held across iterations.
                try:
                    if source_key == "wttj":
                        from src.scrapers.wttj import WTTJScraper
                        scraper = WTTJScraper(user_id=user_id)
                    elif source_key == "indeed":
                        from src.scrapers import get_indeed_scraper
                        scraper = get_indeed_scraper(user_id=user_id)
                    elif source_key == "indeed_api":
                        from src.scrapers.indeed_api import IndeedApiScraper
                        scraper = IndeedApiScraper(user_id=user_id)
                    elif source_key == "linkedin":
                        from src.scrapers.linkedin import LinkedInScraper
                        scraper = LinkedInScraper(user_id=user_id)
                    elif source_key == "adzuna":
                        from src.scrapers.adzuna import AdzunaScraper
                        scraper = AdzunaScraper(user_id=user_id)
                    else:
                        from src.scrapers.france_travail import FranceTravailScraper
                        scraper = FranceTravailScraper(user_id=user_id)
                except Exception as exc:
                    logger.warning("Could not instantiate scraper for %r: %s", source_key, exc)
                    continue

                mode_filters = ScraperFilters(
                    work_modes=[work_mode],
                    countries=countries,
                    location=location,
                    max_days_old=max_days_old,
                )
                try:
                    async with scraper:
                        jobs = await scraper.search(
                            keywords=all_keywords,
                            location=location,
                            filters=mode_filters,
                            limit=50,
                            seen_urls=existing_urls,
                        )
                    fresh = [j for j in jobs if j.url not in existing_urls]
                    if fresh:
                        with get_session() as session:
                            for job in fresh:
                                job.user_id = user_id  # type: ignore[assignment]
                                session.add(job)
                                existing_urls.add(job.url)
                        new_count += len(fresh)
                except Exception:
                    logger.exception("Scraper %r mode=%r raised an error", source_key, work_mode)

        tracker.done("scan", user_id=user_id, result={"new_jobs": new_count})
    except Exception as exc:
        logger.exception("Scan phase failed for user %d", user_id)
        tracker.error("scan", str(exc), user_id=user_id)


async def _run_match(user_id: int) -> None:
    """Match phase: score all NEW jobs for *user_id* with AI."""
    try:
        user = _load_user(user_id)
        if user is None:
            tracker.error("match", f"User {user_id} not found", user_id=user_id)
            return

        user_cfg = get_settings_for_user(user)
        # Check AI configured for this user
        provider = user_cfg.get("llm_provider", settings.llm_provider)
        key_map = {
            "anthropic": user_cfg.get("anthropic_api_key", ""),
            "openai": user_cfg.get("openai_api_key", ""),
            "mistral": user_cfg.get("mistral_api_key", ""),
            "deepseek": user_cfg.get("deepseek_api_key", ""),
            "openrouter": user_cfg.get("openrouter_api_key", ""),
        }
        if not key_map.get(provider, ""):
            tracker.error(
                "match",
                "AI provider not configured — set the appropriate API key",
                user_id=user_id,
            )
            return

        from src.llm.factory import get_client
        from src.matching.scorer import Scorer

        profile = get_profile_for_user(user)
        scoring_provider = user_cfg.get("llm_scoring_provider") or provider
        scoring_model = user_cfg.get("llm_scoring_model") or user_cfg.get("llm_model") or None
        scoring_key = user_cfg.get(f"{scoring_provider}_api_key") or key_map.get(provider, "")
        scoring_client = get_client(scoring_provider, model=scoring_model, api_key=scoring_key)
        scorer = Scorer(client=scoring_client, profile=profile)

        with get_session() as session:
            new_job_ids = [
                j.id
                for j in session.query(Job)
                .filter(Job.status == JobStatus.NEW, Job.user_id == user_id)
                .all()
            ]

        if not new_job_ids:
            tracker.done(
                "match",
                user_id=user_id,
                result={"matched": 0, "message": "No new jobs to score"},
            )
            return

        with get_session() as session:
            new_jobs = session.query(Job).filter(Job.id.in_(new_job_ids)).all()
            await scorer.score_batch(new_jobs, session)

        with get_session() as session:
            matched_count = (
                session.query(Job)
                .filter(Job.status == JobStatus.MATCHED, Job.user_id == user_id)
                .count()
            )

        tracker.done("match", user_id=user_id, result={"matched": matched_count})
    except Exception as exc:
        logger.exception("Match phase failed for user %d", user_id)
        tracker.error("match", str(exc), user_id=user_id)


async def _run_apply(user_id: int, dry_run: bool = True) -> None:
    """Apply phase: generate CV + cover letter drafts for MATCHED jobs of *user_id*."""
    try:
        user = _load_user(user_id)
        if user is None:
            tracker.error("apply", f"User {user_id} not found", user_id=user_id)
            return

        user_cfg = get_settings_for_user(user)
        provider = user_cfg.get("llm_provider", settings.llm_provider)
        key_map = {
            "anthropic": user_cfg.get("anthropic_api_key", ""),
            "openai": user_cfg.get("openai_api_key", ""),
            "mistral": user_cfg.get("mistral_api_key", ""),
            "deepseek": user_cfg.get("deepseek_api_key", ""),
            "openrouter": user_cfg.get("openrouter_api_key", ""),
        }
        if not key_map.get(provider, ""):
            tracker.error(
                "apply",
                "AI provider not configured — set the appropriate API key",
                user_id=user_id,
            )
            return

        from src.generators.cover_letter import CoverLetterGenerator
        from src.generators.cv_generator import CVGenerator
        from src.llm.factory import get_client
        from src.storage.models import Application, ApplicationStatus

        profile = get_profile_for_user(user)
        apply_model = user_cfg.get("llm_model") or None
        apply_key = key_map.get(provider, "")
        apply_client = get_client(provider, model=apply_model, api_key=apply_key)
        cv_gen = CVGenerator(client=apply_client, profile=profile)
        cl_gen = CoverLetterGenerator(client=apply_client, profile=profile)
        output_dir = Path("data") / "cvs"
        output_dir.mkdir(parents=True, exist_ok=True)

        with get_session() as session:
            matched_jobs = (
                session.query(Job)
                .filter(Job.status == JobStatus.MATCHED, Job.user_id == user_id)
                .all()
            )
            eligible_ids = [j.id for j in matched_jobs if j.application is None]

        created_count = 0
        for job_id in eligible_ids:
            with get_session() as session:
                job = session.get(Job, job_id)
                if job is None:
                    continue
                job_snapshot = {
                    "id": job.id,
                    "title": job.title,
                    "description": job.description,
                    "url": job.url,
                    "source": job.source,
                    "company_name": job.company.name if job.company else None,
                }

            cv_path = await cv_gen.generate(job_snapshot, output_dir)
            letter = await cl_gen.generate(job_snapshot)

            with get_session() as session:
                app = Application(
                    job_id=job_id,
                    user_id=user_id,
                    cv_path=str(cv_path),
                    cover_letter=letter,
                    status=ApplicationStatus.DRAFT,
                )
                session.add(app)
            created_count += 1

        tracker.done("apply", user_id=user_id, result={"drafts_created": created_count, "dry_run": dry_run})
    except Exception as exc:
        logger.exception("Apply phase failed for user %d", user_id)
        tracker.error("apply", str(exc), user_id=user_id)


async def _run_respond(user_id: int) -> None:
    """Respond phase: check Gmail for recruiter replies for *user_id*."""
    try:
        user = _load_user(user_id)
        if user is None:
            tracker.error("respond", f"User {user_id} not found", user_id=user_id)
            return

        user_cfg = get_settings_for_user(user)
        gmail_configured = bool(
            user_cfg.get("gmail_client_id")
            and user_cfg.get("gmail_client_secret")
            and user_cfg.get("gmail_refresh_token")
        )
        if not gmail_configured:
            tracker.error(
                "respond",
                "Gmail not configured — set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN",
                user_id=user_id,
            )
            return

        from src.communications.email_handler import EmailHandler
        from src.communications.recruiter_responder import RecruiterResponder
        from src.storage.models import Application, ApplicationStatus

        email_handler = EmailHandler()
        responder = RecruiterResponder()

        with get_session() as session:
            submitted_apps = (
                session.query(Application)
                .filter(
                    Application.status == ApplicationStatus.SUBMITTED,
                    Application.gmail_thread_id.isnot(None),
                    Application.user_id == user_id,
                )
                .all()
            )
            thread_ids = [a.gmail_thread_id for a in submitted_apps if a.gmail_thread_id]
            app_by_thread = {
                a.gmail_thread_id: a.id for a in submitted_apps if a.gmail_thread_id
            }

        if not thread_ids:
            tracker.done(
                "respond",
                user_id=user_id,
                result={"handled": 0, "message": "No submitted applications with Gmail threads"},
            )
            return

        replies = await email_handler.get_unread_replies(thread_ids)
        handled = 0

        for msg in replies:
            app_id = app_by_thread.get(msg.thread_id)
            if app_id is None:
                continue
            with get_session() as session:
                app = session.get(Application, app_id)
                if app is None:
                    continue
                draft = await responder.handle(msg, app)
                if draft is not None:
                    app.status = ApplicationStatus.REPLIED  # type: ignore[assignment]
            await email_handler.mark_as_read(msg.message_id)
            handled += 1

        tracker.done("respond", user_id=user_id, result={"handled": handled})
    except Exception as exc:
        logger.exception("Respond phase failed for user %d", user_id)
        tracker.error("respond", str(exc), user_id=user_id)


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


async def _atomic_start(phase: str, user_id: int) -> None:
    """Atomically check-and-set RUNNING; raise 409 if already running."""
    started = await tracker.try_start(phase, user_id=user_id)
    if not started:
        raise HTTPException(
            status_code=409,
            detail=f"Phase '{phase}' is already running. Wait for it to complete.",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=PipelineStartResponse)
async def trigger_scan(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> PipelineStartResponse:
    """Launch the scan phase in the background."""
    await _atomic_start("scan", current_user.id)
    background_tasks.add_task(_run_scan, current_user.id)
    return PipelineStartResponse(
        status="started",
        phase="scan",
        message="Scan phase started. Check /api/pipeline/status for progress.",
    )


@router.post("/match", response_model=PipelineStartResponse)
async def trigger_match(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> PipelineStartResponse:
    """Launch the match (AI scoring) phase in the background."""
    await _atomic_start("match", current_user.id)
    user_cfg = get_settings_for_user(current_user)
    if not any(
        user_cfg.get(k)
        for k in ("anthropic_api_key", "openai_api_key", "mistral_api_key",
                  "deepseek_api_key", "openrouter_api_key")
    ):
        raise HTTPException(
            status_code=400,
            detail="AI provider API key not configured. Set it in credentials or .env.",
        )
    background_tasks.add_task(_run_match, current_user.id)
    return PipelineStartResponse(
        status="started",
        phase="match",
        message="Match phase started. Check /api/pipeline/status for progress.",
    )


@router.post("/apply", response_model=PipelineStartResponse)
async def trigger_apply(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    dry_run: bool = Query(True, description="When false, submits applications live"),
) -> PipelineStartResponse:
    """Launch the apply (CV generation) phase in the background."""
    await _atomic_start("apply", current_user.id)
    user_cfg = get_settings_for_user(current_user)
    if not any(
        user_cfg.get(k)
        for k in ("anthropic_api_key", "openai_api_key", "mistral_api_key",
                  "deepseek_api_key", "openrouter_api_key")
    ):
        raise HTTPException(
            status_code=400,
            detail="AI provider API key not configured. Set it in credentials or .env.",
        )
    background_tasks.add_task(_run_apply, current_user.id, dry_run)
    return PipelineStartResponse(
        status="started",
        phase="apply",
        message=f"Apply phase started (dry_run={dry_run}). Check /api/pipeline/status for progress.",
    )


@router.post("/respond", response_model=PipelineStartResponse)
async def trigger_respond(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> PipelineStartResponse:
    """Launch the respond (Gmail reply check) phase in the background."""
    await _atomic_start("respond", current_user.id)
    user_cfg = get_settings_for_user(current_user)
    if not (
        user_cfg.get("gmail_client_id")
        and user_cfg.get("gmail_client_secret")
        and user_cfg.get("gmail_refresh_token")
    ):
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured. Set gmail_client_id, gmail_client_secret, and gmail_refresh_token.",
        )
    background_tasks.add_task(_run_respond, current_user.id)
    return PipelineStartResponse(
        status="started",
        phase="respond",
        message="Respond phase started. Check /api/pipeline/status for progress.",
    )


@router.get("/status", response_model=PipelineStatusResponse)
def pipeline_status(
    current_user: User = Depends(get_current_user),
) -> PipelineStatusResponse:
    """Return current state of all pipeline phases for the authenticated user."""
    return PipelineStatusResponse(phases=tracker.all(user_id=current_user.id))


@router.get("/status-partial", response_class=HTMLResponse)
def pipeline_status_partial(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    """Return pipeline controls HTML for HTMX polling.

    Polled every 3s by #pipeline-status via hx-trigger="every 3s".
    Returns the inner HTML only — the outer div's polling attributes
    are preserved by hx-swap="innerHTML".
    """
    return _templates.TemplateResponse(
        request,
        "partials/pipeline_controls.html",
        {"pipeline_status": tracker.all(user_id=current_user.id)},
    )
