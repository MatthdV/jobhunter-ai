"""HTML page routes (Jinja2 templates)."""

import logging
from pathlib import Path

from types import SimpleNamespace

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import json

from src.api.background import tracker
from src.api.deps import require_user_redirect
from src.api.i18n import get_t, get_ui_lang
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus, MatchResult, User
from datetime import date, datetime
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

    sources_done = any(
        s.get("search_terms")
        for s in profile.get("job_sources", [])
        if s.get("enabled", True)
    )

    return {"profile": profile_done, "api_key": key_done, "search_terms": sources_done}


def _build_stats(user_id: int) -> dict:
    """Build stats dict for template context, filtered to *user_id*."""
    today_start = datetime.combine(date.today(), _time.min)
    with get_session() as session:
        total_scanned = session.query(Job).filter(Job.user_id == user_id).count()
        total_matched = (
            session.query(Job)
            .filter(
                Job.user_id == user_id,
                Job.status.in_([JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED]),
            )
            .count()
        )
        total_applied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.SUBMITTED,
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
                Job.status.in_([JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED]),
            )
            .count()
        )
        today_applied = (
            session.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.submitted_at >= today_start,
                Application.status == ApplicationStatus.SUBMITTED,
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
    stats_ns.pipeline_status = {  # type: ignore[attr-defined]
        phase: info for phase, info in tracker.all(user_id=user_id).items()
    }

    return stats_ns  # type: ignore[return-value]


def _serialize_job(job: Job) -> dict:
    """Serialize a Job ORM row into a plain dict for templates."""
    company_dict = None
    if job.company:
        company_dict = {
            "id": job.company.id,
            "name": job.company.name,
            "sector": job.company.sector,
            "website": job.company.website,
            "is_target": job.company.is_target,
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
            "notes": app.notes,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        }

    return {
        "id": job.id,
        "title": job.title,
        "url": job.url,
        "source": job.source,
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
        status_rows = (
            session.query(Job.status, func.count(Job.id))
            .filter(Job.user_id == uid)
            .group_by(Job.status)
            .all()
        )
        status_counts: dict[str, int] = {str(s): c for s, c in status_rows}
        status_counts["all"] = sum(status_counts.values())

        q = session.query(Job).filter(Job.user_id == uid)
        if status:
            try:
                q = q.filter(Job.status == JobStatus(status))
            except ValueError:
                pass  # ignore invalid status filter

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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Jobs list page — same as dashboard but can be extended later."""
    return dashboard(
        request=request,
        status=status,
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

    ctx: dict = {
        "current_user": current_user,
        "profile_data": profile_data,
        "source_configs": source_configs,
        "stored_creds": get_credential_names(current_user),
        "global_creds": get_global_credential_names(),
        "t": get_t(current_user),
        "current_lang": get_ui_lang(current_user),
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


@router.post("/settings/search", response_class=HTMLResponse)
def update_search_settings(
    request: Request,
    max_days_old: int = Form(30),
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Save max_days_old preference."""
    value = max_days_old if max_days_old > 0 else None
    with get_session() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404)
        user.max_days_old = value  # type: ignore[assignment]
    import json as _json
    t = get_t(current_user)
    resp = templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(request, current_user, extra={"saved": True}),
    )
    resp.headers["X-Toast"] = _json.dumps({"message": t["toast_saved"], "type": "success"})
    return resp
