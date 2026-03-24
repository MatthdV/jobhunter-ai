"""Jobs list endpoint with filters, pagination, and score sort."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from api.dependencies import get_current_user, get_db
from src.storage.models import Job, User

router = APIRouter(tags=["jobs"])


class JobItem(BaseModel):
    id: int
    title: str
    url: str
    source: str
    location: str | None
    contract_type: str | None
    salary_raw: str | None
    match_score: float | None
    match_reasoning: str | None
    status: str
    is_remote: bool

    model_config = {"from_attributes": True}


class JobsResponse(BaseModel):
    items: list[JobItem]
    total: int
    offset: int
    limit: int


@router.get("/jobs", response_model=JobsResponse)
def list_jobs(
    source: str | None = Query(None),
    status: str | None = Query(None),
    min_score: float | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobsResponse:
    query = db.query(Job).filter(Job.user_id == user.id)
    if source:
        query = query.filter(Job.source == source)
    if status:
        query = query.filter(Job.status == status)
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)
    if q:
        query = query.filter(Job.title.ilike(f"%{q}%") | Job.description.ilike(f"%{q}%"))  # type: ignore[operator]
    total = query.count()
    items = (
        query.order_by(func.coalesce(Job.match_score, -1).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return JobsResponse(items=items, total=total, offset=offset, limit=limit)
