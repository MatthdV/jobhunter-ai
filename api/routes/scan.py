"""Scan endpoint — launches scraping as a background task."""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user
from src.storage.models import User

router = APIRouter(tags=["scan"])

VALID_SOURCES = {"wttj", "indeed", "linkedin"}


class ScanRequest(BaseModel):
    source: str
    limit: int = 20
    keywords: list[str] = []


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_scan(user_id: int, source: str, limit: int, keywords: list[str]) -> None:
    import importlib

    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus

    _SCRAPER_MAP = {
        "wttj": ("src.scrapers.wttj", "WTTJScraper"),
        "indeed": ("src.scrapers.indeed", "IndeedScraper"),
        "linkedin": ("src.scrapers.linkedin", "LinkedInScraper"),
    }
    try:
        module_path, class_name = _SCRAPER_MAP[source]
        module = importlib.import_module(module_path)
        ScraperClass = getattr(module, class_name)
        async with ScraperClass() as scraper:
            jobs_data = await scraper.search(keywords=keywords, limit=limit)
        with get_session() as db:
            for job in jobs_data:
                existing = db.query(Job).filter(
                    Job.url == job.url, Job.user_id == user_id
                ).first()
                if not existing:
                    job.user_id = user_id
                    job.status = JobStatus.NEW
                    db.add(job)
    except Exception:
        pass


@router.post("/scan", response_model=TaskStarted, status_code=202)
def start_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TaskStarted:
    if body.source not in VALID_SOURCES:
        raise HTTPException(status_code=422, detail=f"Invalid source. Valid: {VALID_SOURCES}")
    task_id = str(uuid.uuid4())
    background_tasks.add_task(_run_scan, user.id, body.source, body.limit, body.keywords)
    return TaskStarted(task_id=task_id)
