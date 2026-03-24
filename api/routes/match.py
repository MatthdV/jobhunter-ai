"""Match endpoint — launches LLM scoring as a background task."""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from api.dependencies import get_current_user
from src.storage.models import User

router = APIRouter(tags=["match"])


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_match(user_id: int, llm_provider: str, encrypted_keys: str | None) -> None:
    from api.auth.service import decrypt_api_key
    from src.config.settings import settings
    from src.llm.factory import get_client
    from src.matching.scorer import Scorer
    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus

    if not encrypted_keys or not settings.fernet_key:
        return
    api_key = decrypt_api_key(settings.fernet_key, encrypted_keys, llm_provider)
    if not api_key:
        return

    llm = get_client(llm_provider, api_key=api_key)
    scorer = Scorer(llm_client=llm)

    with get_session() as db:
        jobs = db.query(Job).filter(Job.user_id == user_id, Job.status == JobStatus.NEW).all()
        for job in jobs:
            result = await scorer.score(job)
            job.match_score = result.score
            job.match_reasoning = result.reasoning
            job.status = JobStatus.MATCHED if result.score >= 80 else JobStatus.SKIPPED
            db.add(job)


@router.post("/match", response_model=TaskStarted, status_code=202)
def start_match(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TaskStarted:
    task_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_match, user.id, user.llm_provider or "anthropic", user.encrypted_keys
    )
    return TaskStarted(task_id=task_id)
