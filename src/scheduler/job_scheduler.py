"""Pipeline orchestrator — ties all phases together in the right order."""

import asyncio
import logging
from datetime import date, datetime
from datetime import time as _time
from pathlib import Path
from typing import Any

from src.config.settings import ConfigurationError, settings
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

logger = logging.getLogger(__name__)


class JobScheduler:
    """Orchestrate the full job search pipeline.

    Execution order per cycle:
    1. Scrape configured sources for new offers.
    2. Deduplicate against existing DB records.
    3. Score surviving offers with Scorer.
    4. Persist results; update Job.status.
    5. For each MATCHED job, generate CV + cover letter draft.
    6. Send Telegram approval request to human.
    7. On approval, submit application via EmailHandler.
    8. Poll Gmail for recruiter replies; trigger RecruiterResponder.
    9. Send daily summary via Telegram.

    Usage::

        scheduler = JobScheduler()
        await scheduler.run_once()          # Single cycle
        await scheduler.run_loop(interval=3600)  # Every hour
    """

    def __init__(
        self,
        scorer: Any = None,
        cv_gen: Any = None,
        cl_gen: Any = None,
        telegram: Any = None,
        email_handler: Any = None,
        responder: Any = None,
        dry_run: bool | None = None,
        max_applications_per_day: int | None = None,
    ) -> None:
        """Initialise all sub-components.

        Accepts optional injected components for testability.
        When not provided, instantiates from settings (requires valid config).
        """
        if scorer is None and cv_gen is None and cl_gen is None:
            # Real instantiation path — validate config first
            if not settings.is_ai_configured:
                raise ConfigurationError(
                    "ANTHROPIC_API_KEY is not set — cannot initialise JobScheduler"
                )
            from src.generators.cover_letter import CoverLetterGenerator
            from src.generators.cv_generator import CVGenerator
            from src.matching.scorer import Scorer

            scorer = Scorer()
            cv_gen = CVGenerator()
            cl_gen = CoverLetterGenerator()

            if settings.is_telegram_configured:
                from src.communications.telegram_bot import TelegramBot
                telegram = TelegramBot()

            if settings.is_gmail_configured:
                from src.communications.email_handler import EmailHandler
                from src.communications.recruiter_responder import RecruiterResponder
                email_handler = EmailHandler()
                responder = RecruiterResponder()

        self._scorer = scorer
        self._cv_gen = cv_gen
        self._cl_gen = cl_gen
        self._telegram = telegram
        self._email_handler = email_handler
        self._responder = responder
        self._dry_run = dry_run if dry_run is not None else settings.dry_run
        self._max_apps = (
            max_applications_per_day
            if max_applications_per_day is not None
            else settings.max_applications_per_day
        )
        self._output_dir = Path("data") / "cvs"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Slice 26 — run_once / run_loop
    # ------------------------------------------------------------------

    async def run_once(self) -> None:
        """Execute a full pipeline cycle (scan → match → apply → respond)."""
        if self._telegram:
            await self._telegram.start_polling()

        try:
            phases: list[tuple[str, Any]] = [
                ("scan", lambda: self._scan_phase()),
                ("match", lambda: self._match_phase()),
                ("apply", lambda: self._apply_phase()),
                ("respond", lambda: self._respond_phase()),
            ]
            for name, phase_fn in phases:
                try:
                    count = await phase_fn()
                    logger.info("Phase '%s' completed: %s items", name, count)
                except Exception:
                    logger.exception("Phase '%s' raised an error — continuing", name)

            if self._telegram:
                try:
                    await self._telegram.send_daily_summary()
                except Exception:
                    logger.exception("Daily summary failed")
        finally:
            if self._telegram:
                await self._telegram.stop_polling()

    async def run_loop(self, interval: int = 3600) -> None:
        """Run the pipeline on a recurring schedule.

        Args:
            interval: Seconds between cycles. Default: 1 hour.
        """
        while True:
            await self.run_once()
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Slice 23 — _scan_phase
    # ------------------------------------------------------------------

    async def _scan_phase(self, scrapers: list[Any] | None = None) -> int:
        """Run all scrapers and persist new jobs. Returns count of new jobs."""
        if not scrapers:
            return 0

        with get_session() as session:
            existing_urls: set[str] = {
                url for (url,) in session.query(Job.url).all()
            }

        new_count = 0
        for scraper in scrapers:
            try:
                async with scraper:
                    jobs = await scraper.search(
                        keywords=["automation"],
                        location="remote",
                        limit=50,
                        seen_urls=existing_urls,
                    )
            except Exception:
                logger.exception("Scraper %r raised an error", scraper)
                continue

            fresh = [j for j in jobs if j.url not in existing_urls]
            if fresh:
                with get_session() as session:
                    for job in fresh:
                        session.add(job)
                        existing_urls.add(job.url)
                new_count += len(fresh)

        return new_count

    # ------------------------------------------------------------------
    # Slice 24 — _match_phase
    # ------------------------------------------------------------------

    async def _match_phase(self) -> int:
        """Score all NEW jobs. Returns count of MATCHED jobs."""
        # Score within a session so changes are committed on exit
        with get_session() as session:
            new_jobs = session.query(Job).filter(Job.status == JobStatus.NEW).all()
            if not new_jobs:
                return 0
            await self._scorer.score_batch(new_jobs, session)

        # Notify Telegram for each MATCHED job (fresh session after commit)
        matched_count = 0
        with get_session() as session:
            for job in session.query(Job).filter(Job.status == JobStatus.MATCHED).all():
                matched_count += 1
                if self._telegram:
                    try:
                        await self._telegram.notify_new_match(job)
                    except Exception:
                        logger.exception(
                            "Telegram notify_new_match failed for job %d", job.id
                        )

        return matched_count

    # ------------------------------------------------------------------
    # Slice 25 — _apply_phase
    # ------------------------------------------------------------------

    async def _apply_phase(self) -> int:
        """Generate applications and trigger human approval flow.

        Respects self._max_apps and self._dry_run.
        Returns count of applications created (DRAFT when dry_run, else SUBMITTED).
        """
        # Identify eligible jobs (inside session to pre-load application relationship)
        with get_session() as session:
            matched_jobs = (
                session.query(Job).filter(Job.status == JobStatus.MATCHED).all()
            )
            today_start = datetime.combine(date.today(), _time.min)
            today_submitted = (
                session.query(Application)
                .filter(
                    Application.created_at >= today_start,
                    Application.status == ApplicationStatus.SUBMITTED,
                )
                .count()
            )
            remaining = max(0, self._max_apps - today_submitted)
            # Access relationship inside session to avoid DetachedInstanceError
            eligible_ids = [
                j.id for j in matched_jobs if j.application is None
            ][:remaining]

        if not eligible_ids:
            return 0

        created_count = 0
        submitted_count = 0

        for job_id in eligible_ids:
            # Fetch fresh job + derive recruiter from company (inside session)
            with get_session() as session:
                job = session.get(Job, job_id)
                recruiter_id: int | None = None
                if job and job.company and job.company.recruiters:
                    recruiter_id = job.company.recruiters[0].id

            # Generate CV and cover letter (async, outside session)
            cv_path = await self._cv_gen.generate(job, self._output_dir)
            letter = await self._cl_gen.generate(job)

            # Persist Application draft
            with get_session() as session:
                app = Application(
                    job_id=job_id,
                    recruiter_id=recruiter_id,
                    cv_path=str(cv_path),
                    cover_letter=letter,
                    status=ApplicationStatus.DRAFT,
                )
                session.add(app)
                session.flush()
                app_id = app.id

            created_count += 1

            # Request human approval and update status
            with get_session() as session:
                fresh_job = session.get(Job, job_id)
                fresh_app = session.get(Application, app_id)

                if fresh_job is None or fresh_app is None:
                    continue

                if self._telegram:
                    fresh_app.status = ApplicationStatus.PENDING_VALIDATION  # type: ignore[assignment]
                    approved = await self._telegram.request_approval(
                        fresh_job, fresh_app
                    )
                else:
                    approved = not self._dry_run

                if approved and not self._dry_run:
                    # Send email and track the Gmail thread
                    gmail_thread_id: str | None = None
                    if self._email_handler and fresh_job.company:
                        recruiter_email = (
                            fresh_app.recruiter.email
                            if fresh_app.recruiter
                            else None
                        )
                        if recruiter_email:
                            try:
                                gmail_thread_id = await self._email_handler.send(
                                    to=recruiter_email,
                                    subject=f"Candidature — {fresh_job.title}",
                                    body=fresh_app.cover_letter or "",
                                    attachments=[fresh_app.cv_path] if fresh_app.cv_path else None,
                                )
                            except Exception:
                                logger.exception(
                                    "Email send failed for job %d — leaving DRAFT", job_id
                                )
                                fresh_app.status = ApplicationStatus.DRAFT  # type: ignore[assignment]
                                continue

                    fresh_app.status = ApplicationStatus.SUBMITTED  # type: ignore[assignment]
                    fresh_app.submitted_at = datetime.utcnow()  # type: ignore[assignment]
                    fresh_app.gmail_thread_id = gmail_thread_id  # type: ignore[assignment]
                    fresh_job.status = JobStatus.APPLIED  # type: ignore[assignment]
                    submitted_count += 1
                elif not self._dry_run:
                    # Live + rejected/timeout: delete so job re-enters queue next cycle
                    session.delete(fresh_app)
                # dry_run: keep DRAFT for human review — no deletion

        return created_count if self._dry_run else submitted_count

    # ------------------------------------------------------------------
    # Slice 33 — _respond_phase
    # ------------------------------------------------------------------

    async def _respond_phase(self) -> int:
        """Check Gmail for recruiter replies and draft responses.

        Returns count of replies handled.
        """
        if self._email_handler is None or self._responder is None:
            return 0

        with get_session() as session:
            submitted_apps = (
                session.query(Application)
                .filter(
                    Application.status == ApplicationStatus.SUBMITTED,
                    Application.gmail_thread_id.isnot(None),
                )
                .all()
            )
            thread_ids = [
                a.gmail_thread_id for a in submitted_apps if a.gmail_thread_id
            ]
            app_by_thread = {
                a.gmail_thread_id: a.id
                for a in submitted_apps
                if a.gmail_thread_id
            }

        if not thread_ids:
            return 0

        replies = await self._email_handler.get_unread_replies(thread_ids)
        handled = 0

        for msg in replies:
            app_id = app_by_thread.get(msg.thread_id)
            if app_id is None:
                continue
            with get_session() as session:
                app = session.get(Application, app_id)
                if app is None:
                    continue
                draft_response = await self._responder.handle(msg, app)
                # Only mark REPLIED when the recruiter sent a meaningful message
                # (handle() returns None for scam/rejection/unrecognised intent)
                if draft_response is not None:
                    app.status = ApplicationStatus.REPLIED  # type: ignore[assignment]
                if self._telegram:
                    job = app.job
                    await self._telegram.notify_reply_received(
                        job, msg.sender, msg.body[:200]
                    )
            await self._email_handler.mark_as_read(msg.message_id)
            handled += 1

        return handled
