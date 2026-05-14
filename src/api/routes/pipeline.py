"""Pipeline phase trigger routes."""

import logging

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from src.api.background import TaskStatus, tracker
from src.api.schemas import PipelineStartResponse, PipelineStatusResponse
from src.config.profile import get_profile_path
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import Job, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Background phase implementations
# ---------------------------------------------------------------------------


_SOURCE_NAME_MAP = {
    "welcome_to_the_jungle": "wttj",
    "wttj": "wttj",
    "indeed": "indeed",
    "linkedin": "linkedin",
}


def _load_job_sources() -> list[dict]:
    """Read job_sources from profile.yaml. Returns [] on any error."""
    try:
        with get_profile_path().open() as fh:
            profile = yaml.safe_load(fh) or {}
        return [s for s in profile.get("job_sources", []) if s.get("enabled", True)]
    except Exception as exc:
        logger.warning("Could not load job_sources from profile: %s", exc)
        return []


async def _run_scan() -> None:
    """Scan phase: launch active scrapers and persist new jobs."""
    try:
        job_sources = _load_job_sources()
        if not job_sources:
            tracker.error("scan", "No enabled job_sources in profile.yaml")
            return

        with get_session() as session:
            existing_urls: set[str] = {url for (url,) in session.query(Job.url).all()}

        new_count = 0
        for source in job_sources:
            source_key = _SOURCE_NAME_MAP.get(source.get("name", ""), "")
            keywords = source.get("search_terms", [])
            location = source.get("location", "")

            if not source_key or not keywords:
                logger.warning("Skipping source %r — missing name or search_terms", source.get("name"))
                continue

            scraper = None
            try:
                if source_key == "wttj":
                    from src.scrapers.wttj import WTTJScraper
                    scraper = WTTJScraper()
                elif source_key == "indeed":
                    from src.scrapers import get_indeed_scraper
                    scraper = get_indeed_scraper()
                elif source_key == "linkedin":
                    from src.scrapers.linkedin import LinkedInScraper
                    scraper = LinkedInScraper()
            except Exception as exc:
                logger.warning("Could not load scraper for %r: %s", source_key, exc)
                continue

            try:
                async with scraper:
                    jobs = await scraper.search(
                        keywords=keywords,
                        location=location,
                        limit=50,
                        seen_urls=existing_urls,
                    )
                fresh = [j for j in jobs if j.url not in existing_urls]
                if fresh:
                    with get_session() as session:
                        for job in fresh:
                            session.add(job)
                            existing_urls.add(job.url)
                    new_count += len(fresh)
            except Exception:
                logger.exception("Scraper %r raised an error", source_key)

        tracker.done("scan", result={"new_jobs": new_count})
    except Exception as exc:
        logger.exception("Scan phase failed")
        tracker.error("scan", str(exc))


async def _run_match() -> None:
    """Match phase: score all NEW jobs with AI."""
    try:
        if not settings.is_ai_configured:
            tracker.error("match", "AI provider not configured — set the appropriate API key")
            return

        from src.matching.scorer import Scorer

        scorer = Scorer()

        # Load IDs first, close session, then score async (avoids holding sync
        # session open across await points inside score_batch)
        with get_session() as session:
            new_job_ids = [
                j.id for j in session.query(Job).filter(Job.status == JobStatus.NEW).all()
            ]

        if not new_job_ids:
            tracker.done("match", result={"matched": 0, "message": "No new jobs to score"})
            return

        # Re-open session for scoring (score_batch modifies job.status in-place)
        with get_session() as session:
            new_jobs = session.query(Job).filter(Job.id.in_(new_job_ids)).all()
            await scorer.score_batch(new_jobs, session)

        with get_session() as session:
            matched_count = (
                session.query(Job).filter(Job.status == JobStatus.MATCHED).count()
            )

        tracker.done("match", result={"matched": matched_count})
    except Exception as exc:
        logger.exception("Match phase failed")
        tracker.error("match", str(exc))


async def _run_apply(dry_run: bool = True) -> None:
    """Apply phase: generate CV + cover letter drafts for MATCHED jobs."""
    try:
        if not settings.is_ai_configured:
            tracker.error("apply", "AI provider not configured — set the appropriate API key")
            return

        from pathlib import Path

        from src.generators.cover_letter import CoverLetterGenerator
        from src.generators.cv_generator import CVGenerator
        from src.storage.models import Application, ApplicationStatus

        cv_gen = CVGenerator()
        cl_gen = CoverLetterGenerator()
        output_dir = Path("data") / "cvs"
        output_dir.mkdir(parents=True, exist_ok=True)

        with get_session() as session:
            matched_jobs = (
                session.query(Job)
                .filter(Job.status == JobStatus.MATCHED)
                .all()
            )
            eligible_ids = [j.id for j in matched_jobs if j.application is None]

        created_count = 0
        for job_id in eligible_ids:
            # Extract scalar data inside session — avoid DetachedInstanceError
            with get_session() as session:
                job = session.get(Job, job_id)
                if job is None:
                    continue
                # Eagerly read all attributes the generators need
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
                    cv_path=str(cv_path),
                    cover_letter=letter,
                    status=ApplicationStatus.DRAFT,
                )
                session.add(app)
            created_count += 1

        tracker.done("apply", result={"drafts_created": created_count, "dry_run": dry_run})
    except Exception as exc:
        logger.exception("Apply phase failed")
        tracker.error("apply", str(exc))


async def _run_respond() -> None:
    """Respond phase: check Gmail for recruiter replies."""
    try:
        if not settings.is_gmail_configured:
            tracker.error("respond", "Gmail not configured — set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN")
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
                )
                .all()
            )
            thread_ids = [a.gmail_thread_id for a in submitted_apps if a.gmail_thread_id]
            app_by_thread = {
                a.gmail_thread_id: a.id
                for a in submitted_apps
                if a.gmail_thread_id
            }

        if not thread_ids:
            tracker.done("respond", result={"handled": 0, "message": "No submitted applications with Gmail threads"})
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

        tracker.done("respond", result={"handled": handled})
    except Exception as exc:
        logger.exception("Respond phase failed")
        tracker.error("respond", str(exc))


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _start_phase(name: str) -> None:
    """Raise 409 if phase is already running."""
    if tracker.is_running(name):
        raise HTTPException(
            status_code=409,
            detail=f"Phase '{name}' is already running. Wait for it to complete.",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=PipelineStartResponse)
async def trigger_scan(background_tasks: BackgroundTasks) -> PipelineStartResponse:
    """Launch the scan phase in the background."""
    _start_phase("scan")
    tracker.start("scan")  # mark RUNNING before scheduling — closes the 409 race window
    background_tasks.add_task(_run_scan)
    return PipelineStartResponse(
        status="started",
        phase="scan",
        message="Scan phase started. Check /api/pipeline/status for progress.",
    )


@router.post("/match", response_model=PipelineStartResponse)
async def trigger_match(background_tasks: BackgroundTasks) -> PipelineStartResponse:
    """Launch the match (AI scoring) phase in the background."""
    _start_phase("match")
    if not settings.is_ai_configured:
        raise HTTPException(
            status_code=400,
            detail="AI provider not configured. Set the appropriate API key in .env.",
        )
    tracker.start("match")
    background_tasks.add_task(_run_match)
    return PipelineStartResponse(
        status="started",
        phase="match",
        message="Match phase started. Check /api/pipeline/status for progress.",
    )


@router.post("/apply", response_model=PipelineStartResponse)
async def trigger_apply(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(True, description="When false, submits applications live"),
) -> PipelineStartResponse:
    """Launch the apply (CV generation) phase in the background."""
    _start_phase("apply")
    if not settings.is_ai_configured:
        raise HTTPException(
            status_code=400,
            detail="AI provider not configured. Set the appropriate API key in .env.",
        )
    tracker.start("apply")
    background_tasks.add_task(_run_apply, dry_run)
    return PipelineStartResponse(
        status="started",
        phase="apply",
        message=f"Apply phase started (dry_run={dry_run}). Check /api/pipeline/status for progress.",
    )


@router.post("/respond", response_model=PipelineStartResponse)
async def trigger_respond(background_tasks: BackgroundTasks) -> PipelineStartResponse:
    """Launch the respond (Gmail reply check) phase in the background."""
    _start_phase("respond")
    if not settings.is_gmail_configured:
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN in .env.",
        )
    tracker.start("respond")
    background_tasks.add_task(_run_respond)
    return PipelineStartResponse(
        status="started",
        phase="respond",
        message="Respond phase started. Check /api/pipeline/status for progress.",
    )


@router.get("/status", response_model=PipelineStatusResponse)
def pipeline_status() -> PipelineStatusResponse:
    """Return current state of all pipeline phases."""
    return PipelineStatusResponse(phases=tracker.all())
