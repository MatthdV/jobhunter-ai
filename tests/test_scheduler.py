"""Tests for JobScheduler — Phase 4B (slices 22-27)."""

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import ConfigurationError
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

if TYPE_CHECKING:
    from src.scheduler.job_scheduler import JobScheduler

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_new_job(url: str = "https://example.com/job/1") -> Job:
    return Job(
        title="Automation Engineer",
        url=url,
        source="wttj",
        description="Python automation expert.",
        is_remote=True,
        contract_type="CDI",
        status=JobStatus.NEW,
    )


def make_matched_job(url: str = "https://example.com/job/1") -> Job:
    return Job(
        title="Automation Engineer",
        url=url,
        source="wttj",
        description="Python automation expert.",
        is_remote=True,
        contract_type="CDI",
        status=JobStatus.MATCHED,
        match_score=87.0,
    )


def make_scheduler(**overrides: object) -> "JobScheduler":
    """Build a JobScheduler with all external dependencies mocked."""
    mock_scorer = MagicMock()
    mock_scorer.score_batch = AsyncMock(return_value=[])
    mock_cv_gen = MagicMock()
    mock_cv_gen.generate = AsyncMock(return_value=Path("/tmp/cv.pdf"))
    mock_cl_gen = MagicMock()
    mock_cl_gen.generate = AsyncMock(return_value="cover letter text")
    mock_telegram = MagicMock()
    mock_telegram.notify_new_match = AsyncMock()
    mock_telegram.request_approval = AsyncMock(return_value=True)
    mock_telegram.send_daily_summary = AsyncMock()
    mock_telegram.notify_reply_received = AsyncMock()
    mock_telegram.start_polling = AsyncMock()
    mock_telegram.stop_polling = AsyncMock()

    from src.scheduler.job_scheduler import JobScheduler

    scheduler = JobScheduler(
        scorer=overrides.get("scorer", mock_scorer),
        cv_gen=overrides.get("cv_gen", mock_cv_gen),
        cl_gen=overrides.get("cl_gen", mock_cl_gen),
        telegram=overrides.get("telegram", mock_telegram),
        dry_run=overrides.get("dry_run", True),
        max_applications_per_day=overrides.get("max_applications_per_day", 10),
    )
    return scheduler


# ---------------------------------------------------------------------------
# Slice 22 — __init__ wiring
# ---------------------------------------------------------------------------


class TestJobSchedulerInit:
    def test_init_accepts_injected_components(self) -> None:
        scheduler = make_scheduler()
        assert scheduler is not None

    def test_init_raises_without_scorer(self) -> None:
        """Scheduler cannot operate without a scoring engine."""
        from unittest.mock import patch

        with patch("src.scheduler.job_scheduler.settings") as mock_settings:
            mock_settings.is_ai_configured = False
            mock_settings.dry_run = True
            mock_settings.max_applications_per_day = 10
            mock_settings.is_telegram_configured = False
            with pytest.raises((ConfigurationError, TypeError)):
                from src.scheduler.job_scheduler import JobScheduler
                JobScheduler()  # no injected components, no real config


# ---------------------------------------------------------------------------
# Slice 23 — _scan_phase
# ---------------------------------------------------------------------------


class TestScanPhase:
    async def test_scan_phase_persists_new_jobs(self) -> None:
        scraped_job = make_new_job()
        mock_scraper = AsyncMock()
        mock_scraper.__aenter__ = AsyncMock(return_value=mock_scraper)
        mock_scraper.__aexit__ = AsyncMock(return_value=None)
        mock_scraper.search = AsyncMock(return_value=[scraped_job])

        scheduler = make_scheduler()
        count = await scheduler._scan_phase(scrapers=[mock_scraper])

        assert count == 1
        with get_session() as session:
            jobs = session.query(Job).all()
        assert len(jobs) == 1

    async def test_scan_phase_deduplicates_by_url(self) -> None:
        with get_session() as session:
            existing = make_new_job(url="https://example.com/job/1")
            session.add(existing)

        duplicate = make_new_job(url="https://example.com/job/1")
        mock_scraper = AsyncMock()
        mock_scraper.__aenter__ = AsyncMock(return_value=mock_scraper)
        mock_scraper.__aexit__ = AsyncMock(return_value=None)
        mock_scraper.search = AsyncMock(return_value=[duplicate])

        scheduler = make_scheduler()
        count = await scheduler._scan_phase(scrapers=[mock_scraper])

        assert count == 0
        with get_session() as session:
            assert session.query(Job).count() == 1


# ---------------------------------------------------------------------------
# Slice 24 — _match_phase
# ---------------------------------------------------------------------------


class TestMatchPhase:
    async def test_match_phase_scores_new_jobs(self) -> None:
        with get_session() as session:
            job = make_new_job()
            session.add(job)

        mock_scorer = MagicMock()
        match_result = MagicMock()
        mock_scorer.score_batch = AsyncMock(return_value=[match_result])

        scheduler = make_scheduler(scorer=mock_scorer)
        await scheduler._match_phase()

        mock_scorer.score_batch.assert_called_once()

    async def test_match_phase_notifies_telegram_for_matched(self) -> None:
        with get_session() as session:
            job = make_new_job()
            session.add(job)
            session.flush()

        mock_scorer = MagicMock()

        async def _score_batch(jobs: list, session: object) -> list:
            for j in jobs:
                j.status = JobStatus.MATCHED
                j.match_score = 90.0
            return [MagicMock()]

        mock_scorer.score_batch = _score_batch

        mock_telegram = MagicMock()
        mock_telegram.notify_new_match = AsyncMock()

        scheduler = make_scheduler(scorer=mock_scorer, telegram=mock_telegram)
        count = await scheduler._match_phase()

        mock_telegram.notify_new_match.assert_called_once()
        assert count == 1


# ---------------------------------------------------------------------------
# Slice 25 — _apply_phase
# ---------------------------------------------------------------------------


class TestApplyPhase:
    async def test_apply_phase_creates_application_draft(self) -> None:
        with get_session() as session:
            job = make_matched_job()
            session.add(job)

        scheduler = make_scheduler(dry_run=True)
        await scheduler._apply_phase()

        with get_session() as session:
            apps = session.query(Application).all()
        assert len(apps) == 1

    async def test_apply_phase_requests_telegram_approval(self) -> None:
        with get_session() as session:
            job = make_matched_job()
            session.add(job)

        mock_telegram = MagicMock()
        mock_telegram.notify_new_match = AsyncMock()
        mock_telegram.request_approval = AsyncMock(return_value=True)

        scheduler = make_scheduler(telegram=mock_telegram, dry_run=True)
        await scheduler._apply_phase()

        mock_telegram.request_approval.assert_called_once()

    async def test_apply_phase_sets_submitted_on_approval_when_live(self) -> None:
        with get_session() as session:
            job = make_matched_job()
            session.add(job)

        mock_telegram = MagicMock()
        mock_telegram.request_approval = AsyncMock(return_value=True)

        scheduler = make_scheduler(telegram=mock_telegram, dry_run=False)
        await scheduler._apply_phase()

        with get_session() as session:
            apps = session.query(Application).all()
            assert len(apps) == 1
            assert apps[0].status == ApplicationStatus.SUBMITTED

    async def test_apply_phase_deletes_application_on_rejection(self) -> None:
        """Rejected application is deleted so the job re-enters the queue next cycle."""
        with get_session() as session:
            job = make_matched_job()
            session.add(job)

        mock_telegram = MagicMock()
        mock_telegram.request_approval = AsyncMock(return_value=False)
        mock_telegram.start_polling = AsyncMock()
        mock_telegram.stop_polling = AsyncMock()

        scheduler = make_scheduler(telegram=mock_telegram, dry_run=False)
        await scheduler._apply_phase()

        with get_session() as session:
            # Application must be deleted so the job becomes eligible again
            assert session.query(Application).count() == 0

    async def test_apply_phase_sends_email_and_stores_thread_id(self) -> None:
        """Approved live application calls email_handler.send() and stores gmail_thread_id.

        _apply_phase derives recruiter_id from job.company.recruiters[0] when available,
        so no pre-seeded Application is needed — the job stays eligible.
        """
        from src.storage.models import Company, Recruiter

        with get_session() as session:
            company = Company(name="Acme Corp")
            session.add(company)
            session.flush()
            recruiter = Recruiter(
                name="Alice HR",
                email="alice@acme.com",
                company_id=company.id,
            )
            session.add(recruiter)
            session.flush()
            job = make_matched_job(url="https://example.com/job/email-test")
            job.company_id = company.id
            session.add(job)
            session.flush()
            job_id = job.id

        mock_telegram = MagicMock()
        mock_telegram.request_approval = AsyncMock(return_value=True)
        mock_telegram.start_polling = AsyncMock()
        mock_telegram.stop_polling = AsyncMock()

        mock_email = MagicMock()
        mock_email.send = AsyncMock(return_value="thread_abc123")

        scheduler = make_scheduler(telegram=mock_telegram, dry_run=False)
        scheduler._email_handler = mock_email

        await scheduler._apply_phase()

        mock_email.send.assert_called_once()
        with get_session() as session:
            apps = session.query(Application).filter(Application.job_id == job_id).all()
            assert len(apps) == 1
            app = apps[0]
            assert app.status == ApplicationStatus.SUBMITTED
            assert app.gmail_thread_id == "thread_abc123"
            assert app.submitted_at is not None

    async def test_apply_phase_sets_submitted_at_on_approval(self) -> None:
        """submitted_at is populated when application is approved and live."""
        with get_session() as session:
            job = make_matched_job(url="https://example.com/job/ts-test")
            session.add(job)

        mock_telegram = MagicMock()
        mock_telegram.request_approval = AsyncMock(return_value=True)
        mock_telegram.start_polling = AsyncMock()
        mock_telegram.stop_polling = AsyncMock()

        scheduler = make_scheduler(telegram=mock_telegram, dry_run=False)
        await scheduler._apply_phase()

        with get_session() as session:
            apps = session.query(Application).all()
            submitted = [a for a in apps if a.status == ApplicationStatus.SUBMITTED]
            # When no recruiter email → email send skipped, still SUBMITTED
            for app in submitted:
                assert app.submitted_at is not None

    async def test_apply_phase_respects_daily_cap(self) -> None:
        with get_session() as session:
            for i in range(5):
                session.add(make_matched_job(url=f"https://example.com/job/{i}"))

        scheduler = make_scheduler(max_applications_per_day=2, dry_run=True)
        count = await scheduler._apply_phase()

        assert count <= 2
        with get_session() as session:
            assert session.query(Application).count() <= 2


# ---------------------------------------------------------------------------
# Slice 26 — run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    async def test_run_once_calls_phases_in_order(self) -> None:
        call_order: list[str] = []

        scheduler = make_scheduler()

        async def _scan(**kw: object) -> int:
            call_order.append("scan")
            return 0

        async def _match() -> int:
            call_order.append("match")
            return 0

        async def _apply() -> int:
            call_order.append("apply")
            return 0

        async def _respond() -> int:
            call_order.append("respond")
            return 0

        scheduler._scan_phase = _scan
        scheduler._match_phase = _match
        scheduler._apply_phase = _apply
        scheduler._respond_phase = _respond

        await scheduler.run_once()

        assert call_order == ["scan", "match", "apply", "respond"]

    async def test_run_once_continues_on_phase_error(self) -> None:
        call_order: list[str] = []

        scheduler = make_scheduler()

        async def _scan(**kw: object) -> int:
            call_order.append("scan")
            raise RuntimeError("scan failed")

        async def _match() -> int:
            call_order.append("match")
            return 0

        async def _apply() -> int:
            call_order.append("apply")
            return 0

        async def _respond() -> int:
            call_order.append("respond")
            return 0

        scheduler._scan_phase = _scan
        scheduler._match_phase = _match
        scheduler._apply_phase = _apply
        scheduler._respond_phase = _respond

        await scheduler.run_once()  # must not raise

        assert "match" in call_order
        assert "apply" in call_order


# ---------------------------------------------------------------------------
# Slice 27 — run_loop
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Slice 33 — _respond_phase
# ---------------------------------------------------------------------------


class TestRespondPhase:
    async def test_respond_phase_returns_zero_without_email_handler(self) -> None:
        scheduler = make_scheduler()
        # No email_handler injected → should return 0 without error
        count = await scheduler._respond_phase()
        assert count == 0

    async def test_respond_phase_handles_gmail_replies(self) -> None:
        from src.communications.email_handler import EmailMessage

        with get_session() as session:
            job = make_matched_job(url="https://example.com/job/resp")
            session.add(job)
            session.flush()
            app = Application(
                job_id=job.id,
                cv_path="/tmp/cv.pdf",
                cover_letter="letter",
                status=ApplicationStatus.SUBMITTED,
                gmail_thread_id="thread_test",
            )
            session.add(app)
            session.flush()
            app_id = app.id

        msg = EmailMessage(
            thread_id="thread_test",
            message_id="msg001",
            sender="recruiter@acme.com",
            subject="Re: Application",
            body="We would like to invite you for an interview.",
            received_at=__import__("datetime").datetime(2026, 3, 21, 10, 0, 0),
        )
        mock_email = MagicMock()
        mock_email.get_unread_replies = AsyncMock(return_value=[msg])
        mock_email.mark_as_read = AsyncMock()

        mock_responder = MagicMock()
        mock_responder.handle = AsyncMock(return_value="Draft reply")

        mock_telegram = MagicMock()
        mock_telegram.notify_reply_received = AsyncMock()

        scheduler = make_scheduler(telegram=mock_telegram)
        scheduler._email_handler = mock_email
        scheduler._responder = mock_responder

        count = await scheduler._respond_phase()

        assert count == 1
        mock_email.mark_as_read.assert_called_once_with("msg001")

        with get_session() as session:
            app = session.get(Application, app_id)
            assert app.status == ApplicationStatus.REPLIED

    async def test_respond_phase_does_not_mark_replied_when_handle_returns_none(
        self,
    ) -> None:
        """Scam/rejection/other messages (handle()=None) must NOT set status=REPLIED."""
        from src.communications.email_handler import EmailMessage

        with get_session() as session:
            job = make_matched_job(url="https://example.com/job/scam")
            session.add(job)
            session.flush()
            app = Application(
                job_id=job.id,
                cv_path="/tmp/cv.pdf",
                cover_letter="letter",
                status=ApplicationStatus.SUBMITTED,
                gmail_thread_id="thread_scam",
            )
            session.add(app)
            session.flush()
            app_id = app.id

        scam_msg = EmailMessage(
            thread_id="thread_scam",
            message_id="msg_scam",
            sender="spam@lottery.com",
            subject="You won!",
            body="Send us your bank details to claim your prize.",
            received_at=__import__("datetime").datetime(2026, 3, 21, 10, 0, 0),
        )
        mock_email = MagicMock()
        mock_email.get_unread_replies = AsyncMock(return_value=[scam_msg])
        mock_email.mark_as_read = AsyncMock()

        mock_responder = MagicMock()
        mock_responder.handle = AsyncMock(return_value=None)  # scam → None

        scheduler = make_scheduler()
        scheduler._email_handler = mock_email
        scheduler._responder = mock_responder

        await scheduler._respond_phase()

        with get_session() as session:
            app = session.get(Application, app_id)
            # Status must remain SUBMITTED — not REPLIED for scam/rejection
            assert app.status == ApplicationStatus.SUBMITTED


class TestRunLoop:
    async def test_run_loop_calls_run_once_then_sleeps(self) -> None:
        run_count = 0

        scheduler = make_scheduler()

        async def _run_once() -> None:
            nonlocal run_count
            run_count += 1
            if run_count >= 2:
                raise asyncio.CancelledError

        import asyncio

        scheduler.run_once = _run_once

        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_loop(interval=0.01)

        assert run_count >= 2
