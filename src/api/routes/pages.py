"""HTML page routes (Jinja2 templates)."""

import logging
from pathlib import Path

from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import json

from src.api.background import tracker
from src.api.deps import require_user_redirect
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus, MatchResult, User
from datetime import date, datetime
from datetime import time as _time

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


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
        {"job": job_dict},
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_user_redirect),
) -> HTMLResponse:
    """Job detail page — requires auth and ownership."""
    _BLOCK_LABELS: dict[str, str] = {
        "A_role_summary": "A — Rôle & catégorie",
        "B_cv_match": "B — Fit CV / offre",
        "C_level_strategy": "C — Niveau / stratégie",
        "D_compensation": "D — Compensation",
        "E_personalization": "E — Personnalisation",
        "F_interview_prep": "F — Préparation entretien",
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
        },
    )
