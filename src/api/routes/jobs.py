"""Job CRUD routes — JSON API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import joinedload

from src.api.deps import get_current_user
from src.api.schemas import JobListOut, JobOut, JobPatchIn
from src.storage.database import get_session
from src.storage.models import Application, Company, Job, JobStatus, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_to_out(job: Job) -> JobOut:
    """Convert a Job ORM object to JobOut schema.

    Must be called while the job is still attached to an open session so that
    relationship attributes (company, application) are accessible without
    triggering lazy-load queries (use joinedload in the calling query).
    """
    company_data = None
    if job.company:
        company_data = {
            "id": job.company.id,
            "name": job.company.name,
            "sector": job.company.sector,
            "size": job.company.size,
            "website": job.company.website,
            "is_target": job.company.is_target,
        }
    app_data = None
    if job.application:
        app_data = {
            "id": job.application.id,
            "status": job.application.status,
            "cv_path": job.application.cv_path,
            "cover_letter": job.application.cover_letter,
            "submitted_at": job.application.submitted_at,
            "gmail_thread_id": job.application.gmail_thread_id,
            "notes": job.application.notes,
            "created_at": job.application.created_at,
        }
    return JobOut(
        id=job.id,
        title=job.title,
        url=job.url,
        source=job.source,
        status=job.status,
        match_score=job.match_score,
        match_reasoning=job.match_reasoning,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_raw=job.salary_raw,
        is_remote=job.is_remote,
        location=job.location,
        contract_type=job.contract_type,
        scraped_at=job.scraped_at,
        company=company_data,
        application=app_data,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=JobListOut)
def list_jobs(
    status: str | None = Query(None, description="Filter by JobStatus value"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> JobListOut:
    """Return a paginated list of jobs for the authenticated user."""
    with get_session() as session:
        q = session.query(Job).options(
            joinedload(Job.company),
            joinedload(Job.application),
        ).filter(Job.user_id == current_user.id)
        if status:
            try:
                status_enum = JobStatus(status)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid status '{status}'. Valid values: {[s.value for s in JobStatus]}",
                )
            q = q.filter(Job.status == status_enum)

        total = q.count()
        jobs = (
            q.order_by(Job.scraped_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = [_job_to_out(job) for job in jobs]

    return JobListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
) -> JobOut:
    """Return full detail for a single job (must belong to authenticated user)."""
    with get_session() as session:
        job = (
            session.query(Job)
            .options(joinedload(Job.company), joinedload(Job.application))
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return _job_to_out(job)


@router.patch("/{job_id}", response_model=JobOut)
def patch_job(
    job_id: int,
    patch: JobPatchIn,
    current_user: User = Depends(get_current_user),
) -> JobOut:
    """Update mutable fields of a job (must belong to authenticated user)."""
    with get_session() as session:
        job = (
            session.query(Job)
            .options(joinedload(Job.company), joinedload(Job.application))
            .filter(Job.id == job_id, Job.user_id == current_user.id)
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if patch.status is not None:
            try:
                job.status = JobStatus(patch.status)  # type: ignore[assignment]
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid status '{patch.status}'. Valid values: {[s.value for s in JobStatus]}",
                )

        return _job_to_out(job)
