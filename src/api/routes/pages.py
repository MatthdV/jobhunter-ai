"""HTML page routes (Jinja2 templates)."""

import logging
from pathlib import Path

from types import SimpleNamespace

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import json

from src.api.background import tracker
from src.api.deps import require_user_redirect
from src.api.i18n import get_t, get_ui_lang
from src.api.security import (
    create_oauth_state_token,
    decode_oauth_state_token,
    decrypt_keys,
    encrypt_keys,
)
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import (
    Application,
    ApplicationStatus,
    Company,
    Job,
    JobStatus,
    MatchResult,
    Recruiter,
    User,
)
from datetime import date, datetime, timezone
from datetime import time as _time

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def _onboarding_state(user: User) -> dict[str, bool]:
    """Return which onboarding steps the user has completed.

    Used to show/hide the setup checklist banner on the dashboard.
    Steps: profile filled, LLM API key configured, search terms defined.
    """
    profile: dict = yaml.safe_load(user.profile_yaml or "") or {}
    candidate = profile.get("candidate", {})
    profile_done = bool(candidate.get("name") or candidate.get("title"))

    key_done = False
    if user.encrypted_keys and settings.fernet_key:
        from src.api.security import decrypt_keys
        keys = decrypt_keys(user.encrypted_keys, settings.fernet_key)
        key_done = any(
            keys.get(k)
            for k in (
                "anthropic_api_key",
                "openai_api_key",
                "mistral_api_key",
                "deepseek_api_key",
                "openrouter_api_key",
            )
        )
    # Fallback: a shared server key on Railway counts as configured
    if not key_done:
        key_done = bool(
            settings.anthropic_api_key
            or settings.openai_api_key
            or settings.mistral_api_key
            or settings.deepseek_api_key
            or settings.openrouter_api_key
        )

    defaults = profile.get("search_defaults", {}) or {}
    sources_done = bool(defaults.get("search_terms")) or any(
        s.get("search_terms")
        for s in profile.get("job_sources", [])
        if s.get("enabled", True)
    )

    return {"profile": profile_done, "api_key": key_done, "search_terms": sources_done}


_CHANNEL_BASE_STATUSES = [
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.REPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
]
_CHANNEL_REPLY_STATUSES = [
    ApplicationStatus.REPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
]


def channel_stats(session, user_id: int) -> list[dict]:
    """Response-rate stats per outreach channel.

    Channels: poster (Recruiter.source == linkedin_poster), recruiter_email
    (hunter / brave_llm), portal (no recruiter linked). Portal replies are not
    observable by the system (no gmail_thread_id) → na=True, rate stays None.
    """
    from sqlalchemy import func

    rows = (
        session.query(Application.status, Recruiter.source, func.count(Application.id))
        .outerjoin(Recruiter, Application.recruiter_id == Recruiter.id)
        .filter(
            Application.user_id == user_id,
            Application.status.in_(_CHANNEL_BASE_STATUSES),
        )
        .group_by(Application.status, Recruiter.source)
        .all()
    )

    buckets: dict[str, dict] = {
        key: {"key": key, "sent": 0, "replies": 0}
        for key in ("poster", "recruiter_email", "portal")
    }
    for status, source, count in rows:
        if source is None:
            key = "portal"
        elif source == "linkedin_poster":
            key = "poster"
        else:
            key = "recruiter_email"
        buckets[key]["sent"] += count
        if status in _CHANNEL_REPLY_STATUSES:
            buckets[key]["replies"] += count

    # LinkedIn DMs are sent manually (copy/paste) — replies happen on LinkedIn,
    # outside the system, so only the sent count is observable (na like portal).
    dm_sent = (
        session.query(func.count(Recruiter.id))
        .filter(Recruiter.user_id == user_id, Recruiter.dm_sent_at.isnot(None))
        .scalar()
        or 0
    )
    buckets["linkedin_dm"] = {"key": "linkedin_dm", "sent": dm_sent, "replies": 0}

    channels = []
    for key in ("poster", "recruiter_email", "linkedin_dm", "portal"):
        b = buckets[key]
        na = key in ("portal", "linkedin_dm")
        rate = None
        if not na and b["sent"] > 0:
            rate = round(b["replies"] * 100 / b["sent"])
        channels.append({**b, "rate": rate, "na": na})
    return channels


def _build_stats(user_id: int) -> dict:
    """Build stats dict for template context, filtered to *user_id*."""
    today_start = datetime.combine(date.today(), _time.min)
    with get_session() as session:
        total_scanned = session.query(Job).filter(Job.user_id == user_id).count()
        total_matched = (
            session.query(Job)
            .filter(
                Job.user_id == user_id,
                Job.status.in_(
                    [JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED, JobStatus.REPLIED]
                ),
            )
            .count()
        )
        # "Applied" = ever submitted — a reply must not remove it from the funnel
        total_applied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status.in_(_CHANNEL_BASE_STATUSES),
            )
            .count()
        )
        total_replied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status.in_(
                    [ApplicationStatus.REPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER]
                ),
            )
            .count()
        )
        today_scanned = (
            session.query(Job)
            .filter(Job.user_id == user_id, Job.scraped_at >= today_start)
            .count()
        )
        today_matched = (
            session.query(Job)
            .filter(
                Job.user_id == user_id,
                Job.scraped_at >= today_start,
                Job.status.in_(
                    [JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED, JobStatus.REPLIED]
                ),
            )
            .count()
        )
        today_applied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.submitted_at >= today_start,
                Application.status.in_(_CHANNEL_BASE_STATUSES),
            )
            .count()
        )
        today_replied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.updated_at >= today_start,
                Application.status.in_(
                    [ApplicationStatus.REPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER]
                ),
            )
            .count()
        )
        channels = channel_stats(session, user_id)

    # Use simple namespace-style object so templates can access .today.scanned etc.
    class NS:
        pass

    today_ns = NS()
    today_ns.scanned = today_scanned  # type: ignore[attr-defined]
    today_ns.matched = today_matched  # type: ignore[attr-defined]
    today_ns.applied = today_applied  # type: ignore[attr-defined]
    today_ns.replied = today_replied  # type: ignore[attr-defined]

    total_ns = NS()
    total_ns.scanned = total_scanned  # type: ignore[attr-defined]
    total_ns.matched = total_matched  # type: ignore[attr-defined]
    total_ns.applied = total_applied  # type: ignore[attr-defined]
    total_ns.replied = total_replied  # type: ignore[attr-defined]

    stats_ns = NS()
    stats_ns.today = today_ns  # type: ignore[attr-defined]
    stats_ns.total = total_ns  # type: ignore[attr-defined]
    stats_ns.channels = channels  # type: ignore[attr-defined]
    stats_ns.pipeline_status = {  # type: ignore[attr-defined]
        phase: info for phase, info in tracker.all(user_id=user_id).items()
    }

    return stats_ns  # type: ignore[return-value]


def _serialize_job(job: Job) -> dict:
    """Serialize a Job ORM row into a plain dict for templates."""
    company_dict = None
    if job.company:
        recruiters = job.company.recruiters or []
        best = max(recruiters, key=lambda r: r.confidence or 0.0) if recruiters else None
        company_dict = {
            "id": job.company.id,
            "name": job.company.name,
            "sector": job.company.sector,
            "website": job.company.website,
            "is_target": job.company.is_target,
            "recruiter_count": len(recruiters),
            "best_recruiter_source": best.source if best else None,
        }

    app_dict = None
    if job.application:
        app = job.application
        app_dict = {
            "id": app.id,
            "status": str(app.status),
            "cv_path": app.cv_path,
            "cover_letter": app.cover_letter,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "gmail_thread_id": app.gmail_thread_id,
            "recruiter_id": app.recruiter_id,
            "followup_draft_subject": app.followup_draft_subject,
            "followup_draft_body": app.followup_draft_body,
            "followup_generated_at": (
                app.followup_generated_at.isoformat() if app.followup_generated_at else None
            ),
            "followup_sent_at": (
                app.followup_sent_at.isoformat() if app.followup_sent_at else None
            ),
            "notes": app.notes,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        }

    return {
        "id": job.id,
        "title": job.title,
        "url": job.url,
        "source": job.source,
        "company_id": job.company_id,
        "status": str(job.status),
        "match_score": job.match_score,
        "match_reasoning": job.match_reasoning,
        "description": job.description,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_raw": job.salary_raw,
        "is_remote": job.is_remote,
        "location": job.location,
        "contract_type": job.contract_type,
        "scraped_at": job.scraped_at.isoformat() if job.scraped_at else None,
        "company": company_dict,
        "application": app_dict,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status: str | None = Query(None),
    has_contact: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Main dashboard page — requires auth."""
    uid = current_user.id
    stats = _build_stats(uid)

    with get_session() as session:
        # Per-status counts for filter tab badges
        from sqlalchemy import func
        from sqlalchemy.orm import joinedload, selectinload
        status_rows = (
            session.query(Job.status, func.count(Job.id))
            .filter(Job.user_id == uid)
            .group_by(Job.status)
            .all()
        )
        status_counts: dict[str, int] = {str(s): c for s, c in status_rows}
        status_counts["all"] = sum(status_counts.values())

        q = (
            session.query(Job)
            .options(
                joinedload(Job.company).selectinload(Company.recruiters),
                joinedload(Job.application),
            )
            .filter(Job.user_id == uid)
        )
        if status:
            try:
                q = q.filter(Job.status == JobStatus(status))
            except ValueError:
                pass  # ignore invalid status filter
        if has_contact:
            q = q.filter(
                Job.company_id.in_(
                    session.query(Recruiter.company_id).filter(Recruiter.user_id == uid)
                )
            )

        total = q.count()
        jobs_orm = (
            q.order_by(Job.scraped_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        jobs_list = [_serialize_job(j) for j in jobs_orm]

    jobs_ns = SimpleNamespace(items=jobs_list, total=total)

    t = get_t(current_user)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "stats": stats,
            "jobs": jobs_list,
            "jobs_ns": jobs_ns,
            "jobs_total": total,
            "status_filter": status or "all",
            "has_contact": has_contact,
            "offset": offset,
            "limit": limit,
            "pipeline_status": stats.pipeline_status,
            "status_counts": status_counts,
            "current_user": current_user,
            "t": t,
            "current_lang": get_ui_lang(current_user),
            "onboarding": _onboarding_state(current_user),
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_list_page(
    request: Request,
    status: str | None = Query(None),
    has_contact: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Jobs list page — same as dashboard but can be extended later."""
    return dashboard(
        request=request,
        status=status,
        has_contact=has_contact,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.post("/jobs/{job_id}/status", response_class=HTMLResponse)
def job_set_status(
    request: Request,
    job_id: int,
    status: str = Form(...),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Inline status update — returns a single <tr> row for HTMX swap.

    Called by the ✕ / ✓ buttons in the job table via hx-post + hx-vals.
    Form data (not JSON) so no HTMX extension is required.
    Enforces user_id ownership check.
    """
    with get_session() as session:
        job = (
            session.query(Job)
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        try:
            job.status = JobStatus(status)  # type: ignore[assignment]
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{status}'. Valid: {[s.value for s in JobStatus]}",
            )
        job_dict = _serialize_job(job)

    return templates.TemplateResponse(
        request,
        "partials/_job_row.html",
        {"job": job_dict, "t": get_t(current_user)},
    )


def _serialize_recruiter(rec: Recruiter | None) -> dict | None:
    """Serialize a Recruiter ORM row for the recruiter section templates."""
    if rec is None:
        return None
    return {
        "id": rec.id,
        "name": rec.name,
        "title": rec.title,
        "email": rec.email,
        "linkedin_url": rec.linkedin_url,
        "source": rec.source,
        "confidence": rec.confidence,
        "found_at": rec.found_at.isoformat() if rec.found_at else None,
        "draft_subject": rec.draft_subject,
        "draft_body": rec.draft_body,
        "dm_invite_note": rec.dm_invite_note,
        "dm_message": rec.dm_message,
        "dm_sent_at": rec.dm_sent_at.isoformat()[:10] if rec.dm_sent_at else None,
    }


def _recruiter_keys_configured(user: User) -> bool:
    """True when the user has at least one recruiter-search key (Hunter or Brave)."""
    from src.api.user_settings import get_settings_for_user

    cfg = get_settings_for_user(user)
    return bool(cfg.get("hunter_api_key") or cfg.get("brave_api_key"))


def _recruiter_section_context(session, job: Job, user: User) -> dict:
    """Build template context for partials/_recruiter_section.html.

    Must be called with *job* attached to an open session.
    """
    company = job.company
    recruiter = None
    search_status = None
    searched_at = None
    if company is not None:
        search_status = company.recruiter_search_status
        searched_at = (
            company.recruiter_searched_at.isoformat()[:10]
            if company.recruiter_searched_at
            else None
        )
        if company.recruiters:
            recruiter = max(company.recruiters, key=lambda r: r.confidence or 0.0)
    return {
        "job_id": job.id,
        "has_company": company is not None,
        "search_status": search_status,
        "searched_at": searched_at,
        "recruiter": _serialize_recruiter(recruiter),
        "recruiter_keys_configured": _recruiter_keys_configured(user),
    }


@router.get("/jobs/{job_id}/recruiter-section", response_class=HTMLResponse)
def recruiter_section(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Recruiter section partial — polled by HTMX while a search runs."""
    with get_session() as session:
        job = (
            session.query(Job)
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        ctx = _recruiter_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


@router.post("/jobs/{job_id}/find-recruiter", response_class=HTMLResponse)
def find_recruiter(
    request: Request,
    job_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Kick off a background recruiter search and return the 'searching' partial.

    Idempotent: if a search is already running for this company, no second
    task is scheduled — the searching partial is returned as-is.
    """
    from src.analysis.recruiter_finder import find_and_persist_recruiter

    with get_session() as session:
        job = (
            session.query(Job)
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        if job.company_id is None:
            raise HTTPException(status_code=422, detail="Job has no company")
        if not _recruiter_keys_configured(current_user):
            raise HTTPException(
                status_code=422,
                detail="Configure a Hunter.io or Brave Search API key in Settings first",
            )
        company = session.get(Company, job.company_id)
        already_searching = company.recruiter_search_status == "searching"
        if not already_searching:
            # Set synchronously so the polling partial shows the right state
            # even before the background task starts.
            company.recruiter_search_status = "searching"
            company.recruiter_search_error = None
        ctx = _recruiter_section_context(session, job, current_user)
        ctx["search_status"] = "searching"

    if not already_searching:
        background_tasks.add_task(find_and_persist_recruiter, job_id, current_user.id)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


def _load_job_with_recruiter(session, job_id: int, user_id: int) -> tuple[Job, Recruiter]:
    """Load an owned job + its best recruiter or raise 404/422."""
    job = (
        session.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .one_or_none()
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.company is None or not job.company.recruiters:
        raise HTTPException(status_code=422, detail="No recruiter found for this job yet")
    recruiter = max(job.company.recruiters, key=lambda r: r.confidence or 0.0)
    return job, recruiter


@router.post("/jobs/{job_id}/draft-email", response_class=HTMLResponse)
async def draft_recruiter_email(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Generate (or regenerate) a personalized outreach email draft via LLM."""
    from src.analysis.recruiter_finder import _build_llm_client
    from src.api.user_settings import get_settings_for_user
    from src.communications.outreach_writer import draft_outreach
    from src.config.profile import get_profile_for_user

    with get_session() as session:
        job, recruiter = _load_job_with_recruiter(session, job_id, current_user.id)
        job_title, job_description = job.title, job.description
        company_name = job.company.name
        recruiter_id = recruiter.id
        recruiter_name, recruiter_title = recruiter.name, recruiter.title

    user_cfg = get_settings_for_user(current_user)
    client = _build_llm_client(user_cfg)
    if client is None:
        raise HTTPException(
            status_code=422,
            detail="LLM provider not configured — set your API key in Settings",
        )
    profile = get_profile_for_user(current_user)

    try:
        subject, body = await draft_outreach(
            job_title, job_description, company_name,
            recruiter_name, recruiter_title, profile, client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    with get_session() as session:
        rec = session.get(Recruiter, recruiter_id)
        if rec is not None:
            rec.draft_subject = subject
            rec.draft_body = body
        job = session.get(Job, job_id)
        ctx = _recruiter_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


@router.post("/jobs/{job_id}/draft-linkedin-dm", response_class=HTMLResponse)
async def draft_linkedin_dm_route(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Generate (or regenerate) a LinkedIn DM draft (invite note + message).

    Sending stays manual: the user copies the texts into LinkedIn themselves.
    """
    from src.analysis.recruiter_finder import _build_llm_client
    from src.api.user_settings import get_settings_for_user
    from src.communications.outreach_writer import draft_linkedin_dm
    from src.config.profile import get_profile_for_user

    with get_session() as session:
        job, recruiter = _load_job_with_recruiter(session, job_id, current_user.id)
        job_title, job_description = job.title, job.description
        company_name = job.company.name
        recruiter_id = recruiter.id
        recruiter_name, recruiter_title = recruiter.name, recruiter.title

    user_cfg = get_settings_for_user(current_user)
    client = _build_llm_client(user_cfg)
    if client is None:
        raise HTTPException(
            status_code=422,
            detail="LLM provider not configured — set your API key in Settings",
        )
    profile = get_profile_for_user(current_user)

    try:
        invite_note, message = await draft_linkedin_dm(
            job_title, job_description, company_name,
            recruiter_name, recruiter_title, profile, client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    with get_session() as session:
        rec = session.get(Recruiter, recruiter_id)
        if rec is not None:
            rec.dm_invite_note = invite_note
            rec.dm_message = message
        job = session.get(Job, job_id)
        ctx = _recruiter_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


@router.post("/jobs/{job_id}/mark-dm-sent", response_class=HTMLResponse)
def mark_dm_sent(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Record that the user sent the LinkedIn DM manually (outcome tracking)."""
    from datetime import timezone as _tz

    with get_session() as session:
        job, recruiter = _load_job_with_recruiter(session, job_id, current_user.id)
        rec = session.get(Recruiter, recruiter.id)
        rec.dm_sent_at = datetime.now(_tz.utc)
        ctx = _recruiter_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


@router.post("/jobs/{job_id}/send-recruiter-email", response_class=HTMLResponse)
async def send_recruiter_email(
    request: Request,
    job_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Send the (user-edited) outreach email and link it to the Application.

    Respects user.dry_run: in dry-run mode nothing is sent, the draft is
    persisted and a clear message is raised instead.
    """
    from src.api.user_settings import get_settings_for_user

    subject = subject.strip()
    body = body.strip()
    if not subject or not body:
        raise HTTPException(status_code=422, detail="Subject and body are required")

    with get_session() as session:
        job, recruiter = _load_job_with_recruiter(session, job_id, current_user.id)
        if not recruiter.email:
            raise HTTPException(
                status_code=422,
                detail="Recruiter has no email — contact them via LinkedIn instead",
            )
        # Persist edits so nothing is lost regardless of the outcome
        recruiter.draft_subject = subject
        recruiter.draft_body = body
        recruiter_id, recruiter_email = recruiter.id, recruiter.email
        cv_path = job.application.cv_path if job.application else None

    user_cfg = get_settings_for_user(current_user)
    if not (
        user_cfg.get("gmail_client_id")
        and user_cfg.get("gmail_client_secret")
        and user_cfg.get("gmail_refresh_token")
    ):
        raise HTTPException(
            status_code=422,
            detail="Gmail not configured — set Gmail credentials in Settings",
        )
    if current_user.dry_run:
        raise HTTPException(
            status_code=422,
            detail="Dry-run mode is on — draft saved, nothing sent. "
                   "Disable dry-run in Settings to send for real.",
        )

    from src.communications.email_handler import EmailHandler

    email_handler = EmailHandler(user_cfg)
    try:
        gmail_thread_id = await email_handler.send(
            to=recruiter_email,
            subject=subject,
            body=body,
            attachments=[cv_path] if cv_path else None,
        )
    except Exception as exc:
        logger.exception("Recruiter email send failed for job %d", job_id)
        raise HTTPException(status_code=502, detail=f"Email send failed: {exc}")

    with get_session() as session:
        job = session.get(Job, job_id)
        app = job.application
        if app is None:
            app = Application(job_id=job_id, user_id=current_user.id)
            session.add(app)
        app.recruiter_id = recruiter_id
        app.gmail_thread_id = gmail_thread_id
        app.status = ApplicationStatus.SUBMITTED
        app.submitted_at = datetime.now(timezone.utc)
        job.status = JobStatus.APPLIED
        ctx = _recruiter_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_recruiter_section.html", ctx)


def _followup_days_since(submitted_at_iso: str | None) -> int | None:
    """Days elapsed since submission, from an ISO string (None-safe)."""
    if not submitted_at_iso:
        return None
    sub = datetime.fromisoformat(submitted_at_iso)
    if sub.tzinfo is None:
        sub = sub.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - sub).days


def _followup_section_context(session, job: Job, user: User) -> dict:
    """Build template context for partials/_followup_section.html."""
    job_dict = _serialize_job(job)
    app = job_dict.get("application")
    return {
        "job_id": job.id,
        "followup_app": app,
        "followup_days": _followup_days_since(app["submitted_at"]) if app else None,
        "followup_delay_days": user.followup_delay_days or 5,
    }


def _load_job_for_followup(session, job_id: int, user_id: int) -> Job:
    """Load an owned job whose application is eligible for a follow-up, or raise."""
    job = (
        session.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .one_or_none()
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    app = job.application
    if app is None or not app.gmail_thread_id:
        raise HTTPException(
            status_code=422,
            detail="No submitted application with an email thread for this job",
        )
    if app.status != ApplicationStatus.SUBMITTED:
        raise HTTPException(
            status_code=422,
            detail=f"Application is '{app.status}' — follow-ups only apply to submitted applications",
        )
    return job


@router.post("/jobs/{job_id}/draft-followup", response_class=HTMLResponse)
async def draft_followup_email(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Generate (or regenerate) a follow-up email draft via LLM."""
    from src.analysis.recruiter_finder import _build_llm_client
    from src.api.user_settings import get_settings_for_user
    from src.communications.followup_writer import draft_followup
    from src.config.profile import get_profile_for_user

    with get_session() as session:
        job = _load_job_for_followup(session, job_id, current_user.id)
        app = job.application
        job_title = job.title
        company_name = job.company.name if job.company else "(unknown)"
        original_subject = app.recruiter.draft_subject if app.recruiter else None
        original_body = app.recruiter.draft_body if app.recruiter else None
        days_since = _followup_days_since(
            app.submitted_at.isoformat() if app.submitted_at else None
        ) or 0
        app_id = app.id

    user_cfg = get_settings_for_user(current_user)
    client = _build_llm_client(user_cfg)
    if client is None:
        raise HTTPException(
            status_code=422,
            detail="LLM provider not configured — set your API key in Settings",
        )
    profile = get_profile_for_user(current_user)

    try:
        subject, body = await draft_followup(
            job_title, company_name, original_subject, original_body,
            days_since, profile, client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    with get_session() as session:
        app = session.get(Application, app_id)
        if app is not None:
            app.followup_draft_subject = subject
            app.followup_draft_body = body
            app.followup_generated_at = datetime.now(timezone.utc)
        job = session.get(Job, job_id)
        ctx = _followup_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_followup_section.html", ctx)


@router.post("/jobs/{job_id}/send-followup", response_class=HTMLResponse)
async def send_followup_email(
    request: Request,
    job_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Send the (user-edited) follow-up in the existing Gmail thread.

    Respects user.dry_run: in dry-run mode nothing is sent, the draft is
    persisted and a clear message is raised instead.
    """
    from src.api.user_settings import get_settings_for_user

    subject = subject.strip()
    body = body.strip()
    if not subject or not body:
        raise HTTPException(status_code=422, detail="Subject and body are required")

    with get_session() as session:
        job = _load_job_for_followup(session, job_id, current_user.id)
        app = job.application
        if app.followup_sent_at is not None:
            raise HTTPException(
                status_code=422,
                detail="A follow-up was already sent for this application",
            )
        recruiter = app.recruiter
        if recruiter is None or not recruiter.email:
            raise HTTPException(
                status_code=422,
                detail="No recruiter email linked to this application",
            )
        # Persist edits so nothing is lost regardless of the outcome
        app.followup_draft_subject = subject
        app.followup_draft_body = body
        if app.followup_generated_at is None:
            app.followup_generated_at = datetime.now(timezone.utc)
        app_id = app.id
        recruiter_email = recruiter.email
        thread_id = app.gmail_thread_id

    user_cfg = get_settings_for_user(current_user)
    if not (
        user_cfg.get("gmail_client_id")
        and user_cfg.get("gmail_client_secret")
        and user_cfg.get("gmail_refresh_token")
    ):
        raise HTTPException(
            status_code=422,
            detail="Gmail not configured — set Gmail credentials in Settings",
        )
    if current_user.dry_run:
        raise HTTPException(
            status_code=422,
            detail="Dry-run mode is on — follow-up draft saved, nothing sent. "
                   "Disable dry-run in Settings to send for real.",
        )

    from src.communications.email_handler import EmailHandler

    email_handler = EmailHandler(user_cfg)
    try:
        await email_handler.send(
            to=recruiter_email,
            subject=subject,
            body=body,
            reply_to_thread=thread_id,
        )
    except Exception as exc:
        logger.exception("Follow-up send failed for job %d", job_id)
        raise HTTPException(status_code=502, detail=f"Email send failed: {exc}")

    with get_session() as session:
        app = session.get(Application, app_id)
        if app is not None:
            app.followup_sent_at = datetime.now(timezone.utc)
        job = session.get(Job, job_id)
        ctx = _followup_section_context(session, job, current_user)

    ctx["t"] = get_t(current_user)
    return templates.TemplateResponse(request, "partials/_followup_section.html", ctx)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Job detail page — requires auth and ownership."""
    t = get_t(current_user)
    _BLOCK_LABELS: dict[str, str] = {
        "A_role_summary": t["block_A"],
        "B_cv_match": t["block_B"],
        "C_level_strategy": t["block_C"],
        "D_compensation": t["block_D"],
        "E_personalization": t["block_E"],
        "F_interview_prep": t["block_F"],
    }

    with get_session() as session:
        job = (
            session.query(Job)
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        job_dict = _serialize_job(job)
        recruiter_ctx = _recruiter_section_context(session, job, current_user)
        followup_ctx = _followup_section_context(session, job, current_user)

        # Load A-F evaluation blocks from MatchResult
        evaluation_blocks: list[dict] = []
        archetype: str | None = None
        mr = session.query(MatchResult).filter(MatchResult.job_id == job_id).one_or_none()
        if mr and mr.evaluation_json:
            try:
                eval_data = json.loads(mr.evaluation_json)
                archetype = eval_data.get("archetype")
                blocks_raw = eval_data.get("blocks", {})
                for key, label in _BLOCK_LABELS.items():
                    block_info = blocks_raw.get(key, {})
                    score = block_info.get("score", None)
                    evaluation_blocks.append({
                        "key": key,
                        "label": label,
                        "score": score,
                        "details": {k: v for k, v in block_info.items() if k != "score"},
                    })
            except (json.JSONDecodeError, AttributeError):
                pass  # evaluation_blocks stays empty — template handles gracefully

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "job": job_dict,
            "evaluation_blocks": evaluation_blocks,
            "archetype": archetype,
            "current_user": current_user,
            "t": t,
            "current_lang": get_ui_lang(current_user),
            **recruiter_ctx,
            **followup_ctx,
        },
    )


@router.get("/applications/{app_id}/cv")
def download_cv(
    app_id: int,
    current_user: User = Depends(require_user_redirect),
) -> FileResponse:
    """Serve the generated CV PDF for an application the user owns.

    Ownership-checked (never serve another user's file). The data/ dir is not
    mounted as static precisely so downloads go through this auth gate.
    """
    with get_session() as session:
        app = (
            session.query(Application)
            .filter(Application.id == app_id, Application.user_id == current_user.id)
            .one_or_none()
        )
        if app is None or not app.cv_path:
            raise HTTPException(status_code=404, detail="CV introuvable")
        cv_path = Path(app.cv_path)

    if not cv_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier CV introuvable sur le disque")

    return FileResponse(
        str(cv_path),
        media_type="application/pdf",
        filename=cv_path.name,
    )


def _build_settings_context(request: Request, current_user: User, extra: dict | None = None) -> dict:
    """Build the full template context required by settings.html."""
    import yaml as _yaml
    from src.api.user_settings import get_credential_names, get_global_credential_names

    raw_yaml = current_user.profile_yaml or ""
    profile_data: dict = _yaml.safe_load(raw_yaml) or {} if raw_yaml.strip() else {}

    source_configs: dict = {}
    for src in profile_data.get("job_sources", []):
        name = src.get("name")
        if name and name not in source_configs:
            source_configs[name] = {
                "keywords": src.get("search_terms", []),
                "location": src.get("location", ""),
                "work_modes": src.get("work_modes", ["remote"]),
            }

    raw_defaults = profile_data.get("search_defaults", {}) or {}
    search_defaults = {
        "keywords": raw_defaults.get("search_terms", []),
        "location": raw_defaults.get("location", ""),
        "work_modes": raw_defaults.get("work_modes", ["remote"]),
    }

    ctx: dict = {
        "current_user": current_user,
        "profile_data": profile_data,
        "source_configs": source_configs,
        "search_defaults": search_defaults,
        "stored_creds": get_credential_names(current_user),
        "global_creds": get_global_credential_names(),
        "t": get_t(current_user),
        "current_lang": get_ui_lang(current_user),
        "gmail_oauth_ready": _gmail_oauth_ready(),
        "gmail_status": request.query_params.get("gmail", ""),
    }
    if extra:
        ctx.update(extra)
    return ctx


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """User settings page."""
    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(request, current_user),
    )


# ---------------------------------------------------------------------------
# Gmail OAuth connect flow ("Connecter Gmail")
# ---------------------------------------------------------------------------

_GMAIL_SCOPES = ["https://mail.google.com/"]


def _gmail_oauth_ready() -> bool:
    """True if the instance-wide Google OAuth web client is configured."""
    return bool(settings.gmail_oauth_client_id and settings.gmail_oauth_client_secret)


def _gmail_redirect_uri(request: Request) -> str:
    """Callback URI to hand to Google — must exactly match a URI declared in GCP."""
    base = str(request.base_url).rstrip("/")
    if request.url.hostname not in ("localhost", "127.0.0.1") and base.startswith("http://"):
        # Behind the TLS proxy the app sees plain HTTP; Google only knows the https URI.
        base = "https://" + base[len("http://"):]
    return f"{base}/settings/gmail/callback"


def _build_gmail_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.gmail_oauth_client_id,
            "client_secret": settings.gmail_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    # PKCE's code_verifier can't survive across the connect/callback request
    # boundary (each builds a fresh Flow instance) — this client is
    # confidential (holds a client_secret), so PKCE isn't needed anyway.
    return Flow.from_client_config(
        client_config,
        scopes=_GMAIL_SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def _gmail_profile_email(credentials) -> str:
    """Fetch the email address of the account that just granted access."""
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return str(profile.get("emailAddress", ""))
    except Exception:
        logger.exception("Could not fetch connected Gmail address")
        return ""


def _update_user_credentials(user_id: int, updates: dict[str, str]) -> None:
    """Merge *updates* into the user's encrypted credential blob (empty = delete)."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        existing: dict = (
            decrypt_keys(user.encrypted_keys, settings.fernet_key)
            if user.encrypted_keys
            else {}
        )
        for k, v in updates.items():
            if v:
                existing[k] = v
            else:
                existing.pop(k, None)
        user.encrypted_keys = encrypt_keys(existing, settings.fernet_key)  # type: ignore[assignment]


@router.get("/settings/gmail/connect")
def gmail_connect(
    request: Request,
    current_user: User = Depends(require_user_redirect),
) -> RedirectResponse:
    """Redirect the user to Google's consent screen to link their Gmail."""
    if not _gmail_oauth_ready():
        raise HTTPException(
            status_code=503,
            detail="Gmail OAuth client not configured — set GMAIL_OAUTH_CLIENT_ID "
                   "and GMAIL_OAUTH_CLIENT_SECRET in .env",
        )
    if not settings.fernet_key:
        raise HTTPException(
            status_code=503,
            detail="FERNET_KEY not configured — cannot store the refresh token",
        )
    state = create_oauth_state_token(current_user.id, settings.jwt_secret)
    flow = _build_gmail_flow(_gmail_redirect_uri(request))
    # access_type=offline + prompt=consent forces Google to return a refresh token
    # even when the user already granted access before.
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", state=state
    )
    return RedirectResponse(auth_url, status_code=302)


@router.get("/settings/gmail/callback")
def gmail_callback(
    request: Request,
    state: str = Query(""),
    code: str = Query(""),
    error: str = Query(""),
    current_user: User = Depends(require_user_redirect),
):
    """Handle Google's redirect: validate state, exchange code, store the token."""
    if error:
        return RedirectResponse("/settings?gmail=denied", status_code=302)
    state_user_id = decode_oauth_state_token(state, settings.jwt_secret)
    if state_user_id is None or state_user_id != current_user.id:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    flow = _build_gmail_flow(_gmail_redirect_uri(request))
    try:
        flow.fetch_token(code=code)
    except Exception:
        logger.exception("Gmail OAuth code exchange failed for user %d", current_user.id)
        return RedirectResponse("/settings?gmail=error", status_code=302)

    refresh_token = getattr(flow.credentials, "refresh_token", None)
    if not refresh_token:
        logger.error("Google returned no refresh token for user %d", current_user.id)
        return RedirectResponse("/settings?gmail=error", status_code=302)

    connected_email = _gmail_profile_email(flow.credentials)
    _update_user_credentials(
        current_user.id,
        {"gmail_refresh_token": refresh_token, "gmail_user_email": connected_email},
    )
    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is not None:
            user.gmail_connected_email = connected_email or None  # type: ignore[assignment]
            user.gmail_connected_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    return RedirectResponse("/settings?gmail=connected", status_code=302)


@router.post("/settings/gmail/disconnect")
def gmail_disconnect(
    request: Request,
    current_user: User = Depends(require_user_redirect),
) -> RedirectResponse:
    """Revoke the Google token (best effort) and forget it locally."""
    refresh_token = ""
    if current_user.encrypted_keys and settings.fernet_key:
        refresh_token = decrypt_keys(
            current_user.encrypted_keys, settings.fernet_key
        ).get("gmail_refresh_token", "")
    if refresh_token:
        try:
            import httpx

            httpx.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
                timeout=10,
            )
        except Exception:
            logger.warning("Gmail token revoke failed — continuing with local disconnect")
    if settings.fernet_key:
        _update_user_credentials(
            current_user.id, {"gmail_refresh_token": "", "gmail_user_email": ""}
        )
    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is not None:
            user.gmail_connected_email = None  # type: ignore[assignment]
            user.gmail_connected_at = None  # type: ignore[assignment]
    return RedirectResponse("/settings?gmail=disconnected", status_code=303)


@router.post("/settings/search", response_class=HTMLResponse)
def update_search_settings(
    request: Request,
    max_days_old: int = Form(30),
    followup_delay_days: int = Form(5),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Save max_days_old + followup_delay_days preferences."""
    value = max_days_old if max_days_old > 0 else None
    followup_delay = min(max(followup_delay_days, 1), 30)
    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404)
        user.max_days_old = value  # type: ignore[assignment]
        user.followup_delay_days = followup_delay  # type: ignore[assignment]
    import json as _json
    t = get_t(current_user)
    resp = templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(request, current_user, extra={"saved": True}),
    )
    resp.headers["X-Toast"] = _json.dumps({"message": t["toast_saved"], "type": "success"})
    return resp
