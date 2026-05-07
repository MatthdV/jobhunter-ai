"""Stats route — aggregate counts for the dashboard."""

from datetime import date, datetime
from datetime import time as _time

from fastapi import APIRouter

from src.api.background import tracker
from src.api.schemas import StatsOut, StatsToday, StatsTotal
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

router = APIRouter()


@router.get("", response_model=StatsOut)
def get_stats() -> StatsOut:
    """Return today's and total aggregate stats plus pipeline phase statuses."""
    today_start = datetime.combine(date.today(), _time.min)

    with get_session() as session:
        # --- Total counts ---
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
                    [
                        ApplicationStatus.REPLIED,
                        ApplicationStatus.INTERVIEW,
                        ApplicationStatus.OFFER,
                    ]
                )
            )
            .count()
        )

        # --- Today counts ---
        today_scanned = (
            session.query(Job).filter(Job.scraped_at >= today_start).count()
        )
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
                    [
                        ApplicationStatus.REPLIED,
                        ApplicationStatus.INTERVIEW,
                        ApplicationStatus.OFFER,
                    ]
                ),
            )
            .count()
        )

    return StatsOut(
        today=StatsToday(
            scanned=today_scanned,
            matched=today_matched,
            applied=today_applied,
            replied=today_replied,
        ),
        total=StatsTotal(
            scanned=total_scanned,
            matched=total_matched,
            applied=total_applied,
            replied=total_replied,
        ),
        pipeline_status=tracker.all(),
    )
