"""HTML page routes (Jinja2 templates)."""

import logging
from pathlib import Path

from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.background import tracker
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus
from datetime import date, datetime
from datetime import time as _time

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def _build_stats() -> dict:
    """Build stats dict for template context."""
    today_start = datetime.combine(date.today(), _time.min)
    with get_session() as session:
        total_scanned = session.query(Job).count()
        total_matched = (
            session.query(Job)
            .filter(Job.status.in_([JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED]))
            .count()
        )
        total_applied = (
            session.query(Application)
            .filter(Application.status == ApplicationStatus.SUBMITTED)
            .count()
        )
        total_replied = (
            session.query(Application)
            .filter(
                Application.status.in_(
                    [ApplicationStatus.REPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER]
                )
            )
            .count()
        )
        today_scanned = session.query(Job).filter(Job.scraped_at >= today_start).count()
        today_matched = (
            session.query(Job)
            .filter(
                Job.scraped_at >= today_start,
                Job.status.in_([JobStatus.MATCHED, JobStatus.PENDING, JobStatus.APPLIED]),
            )
            .count()
        )
        today_applied = (
            session.query(Application)
            .filter(
                Application.submitted_at >= today_start,
                Application.status == ApplicationStatus.SUBMITTED,
            )
            .count()
        )
        today_replied = (
            session.query(Application)
            .filter(
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
        phase: info for phase, info in tracker.all().items()
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
) -> HTMLResponse:
    """Main dashboard page."""
    stats = _build_stats()

    with get_session() as session:
        q = session.query(Job)
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
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_list_page(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> HTMLResponse:
    """Jobs list page — same as dashboard but can be extended later."""
    return dashboard(request=request, status=status, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int) -> HTMLResponse:
    """Job detail page."""
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        job_dict = _serialize_job(job)

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "job": job_dict,
        },
    )
