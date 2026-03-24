"""Applications list and generation endpoints."""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from src.storage.models import Application, User

router = APIRouter(tags=["applications"])


class ApplicationItem(BaseModel):
    id: int
    job_id: int
    status: str
    cover_letter: str | None
    cv_path: str | None

    model_config = {"from_attributes": True}


class ApplicationsResponse(BaseModel):
    items: list[ApplicationItem]
    total: int


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_generate(application_id: int, user_id: int, encrypted_keys: str | None) -> None:
    from api.auth.service import decrypt_api_key
    from src.config.settings import settings
    from src.generators.cover_letter import CoverLetterGenerator
    from src.llm.factory import get_client
    from src.storage.database import get_session
    from src.storage.models import Application

    if not encrypted_keys or not settings.fernet_key:
        return
    with get_session() as db:
        app = db.query(Application).filter(
            Application.id == application_id, Application.user_id == user_id
        ).first()
        if not app or not app.job:
            return
        user = app.user
        if not user:
            return
        api_key = decrypt_api_key(settings.fernet_key, encrypted_keys, user.llm_provider or "anthropic")
        if not api_key:
            return
        llm = get_client(user.llm_provider or "anthropic", api_key=api_key)
        generator = CoverLetterGenerator(llm_client=llm)
        cover_letter = await generator.generate(job=app.job, profile_yaml=user.profile_yaml or "")
        app.cover_letter = cover_letter
        db.add(app)


@router.get("/applications", response_model=ApplicationsResponse)
def list_applications(
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationsResponse:
    query = db.query(Application).filter(Application.user_id == user.id)
    if status:
        query = query.filter(Application.status == status)
    total = query.count()
    items = query.order_by(Application.created_at.desc()).all()
    return ApplicationsResponse(items=items, total=total)


@router.post("/applications/{application_id}/generate", response_model=TaskStarted, status_code=202)
def generate_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskStarted:
    app = db.query(Application).filter(
        Application.id == application_id, Application.user_id == user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    task_id = str(uuid.uuid4())
    background_tasks.add_task(_run_generate, application_id, user.id, user.encrypted_keys)
    return TaskStarted(task_id=task_id)
