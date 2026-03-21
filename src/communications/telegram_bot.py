"""Telegram bot for real-time notifications and human validation prompts."""

import asyncio
import logging
from datetime import date, datetime, time as _time

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.config.settings import ConfigurationError, settings
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

logger = logging.getLogger(__name__)

_DEFAULT_APPROVAL_TIMEOUT = 300  # seconds


class TelegramBot:
    """Send notifications and receive validation decisions via Telegram.

    The bot sends a message for each job that passes the match threshold,
    and waits for a thumbs-up / thumbs-down reply before submitting any
    application. This is the primary human-in-the-loop mechanism.

    Usage::

        bot = TelegramBot()
        approved = await bot.request_approval(job, application)
        if approved:
            await email_handler.send(...)
    """

    def __init__(self) -> None:
        """Initialise python-telegram-bot Application from Settings."""
        if not settings.telegram_bot_token:
            raise ConfigurationError(
                "TELEGRAM_BOT_TOKEN is not set — cannot initialise TelegramBot"
            )
        if not settings.telegram_chat_id:
            raise ConfigurationError(
                "TELEGRAM_CHAT_ID is not set — cannot initialise TelegramBot"
            )
        self._chat_id = settings.telegram_chat_id
        self._bot = telegram.Bot(token=settings.telegram_bot_token)
        # Maps application.id → asyncio.Future[bool] for approval gate
        self._pending: dict[int, asyncio.Future[bool]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> telegram.Message:
        """Send an HTML-formatted message to the configured chat."""
        return await self._bot.send_message(
            chat_id=self._chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    # ------------------------------------------------------------------
    # Slice 18 — notify_new_match
    # ------------------------------------------------------------------

    async def notify_new_match(self, job: Job) -> None:
        """Send a match notification card for a new offer.

        Includes: title, company, score, salary, remote status, URL.
        """
        score = f"{job.match_score:.0f}" if job.match_score is not None else "—"
        salary = "—"
        if job.salary_min and job.salary_max:
            salary = f"{job.salary_min // 1000}k–{job.salary_max // 1000}k EUR"
        elif job.salary_min:
            salary = f"{job.salary_min // 1000}k+ EUR"
        remote = "Oui" if job.is_remote else "Non"
        company_name = job.company.name if job.company else "—"

        text = (
            f"<b>Nouveau match : {job.title}</b>\n"
            f"Entreprise : {company_name}\n"
            f"Score : {score}/100\n"
            f"Salaire : {salary}\n"
            f"Remote : {remote}\n"
        )
        if job.url:
            text += f'<a href="{job.url}">Voir l\'offre</a>'

        await self._send_message(text)

    # ------------------------------------------------------------------
    # Slice 19 — request_approval (human-in-the-loop gate)
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        job: Job,
        application: Application,
        timeout: float = _DEFAULT_APPROVAL_TIMEOUT,
    ) -> bool:
        """Send CV + cover letter preview and wait for human approval.

        Blocks until the user clicks Approve/Reject (or times out).

        Returns:
            True if the user approved, False otherwise (reject or timeout).
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[application.id] = future

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approuver", callback_data=f"approve_{application.id}"
                ),
                InlineKeyboardButton(
                    "❌ Rejeter", callback_data=f"reject_{application.id}"
                ),
            ]
        ])

        letter_preview = (application.cover_letter or "")[:300]
        text = (
            f"<b>Validation requise : {job.title}</b>\n\n"
            f"<b>Lettre de motivation (aperçu) :</b>\n{letter_preview}\n\n"
            f"CV : <code>{application.cv_path}</code>"
        )
        await self._send_message(text, reply_markup=keyboard)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(application.id, None)
            logger.warning(
                "Approval request for application %d timed out after %ss",
                application.id,
                timeout,
            )
            return False

    async def handle_callback(self, callback_data: str) -> None:
        """Resolve a pending approval future from a Telegram callback query.

        Expected callback_data format: 'approve_<app_id>' or 'reject_<app_id>'.
        """
        parts = callback_data.split("_", 1)
        if len(parts) != 2 or parts[0] not in ("approve", "reject"):
            logger.warning("Unexpected callback_data: %r", callback_data)
            return
        action, app_id_str = parts
        try:
            app_id = int(app_id_str)
        except ValueError:
            return
        future = self._pending.pop(app_id, None)
        if future is not None and not future.done():
            future.set_result(action == "approve")

    # ------------------------------------------------------------------
    # Slice 20 — notify_reply_received
    # ------------------------------------------------------------------

    async def notify_reply_received(self, job: Job, sender: str, snippet: str) -> None:
        """Notify that a recruiter has replied to an application."""
        preview = snippet[:200]
        text = (
            f"<b>Réponse reçue pour : {job.title}</b>\n"
            f"De : {sender}\n\n"
            f"{preview}"
        )
        await self._send_message(text)

    # ------------------------------------------------------------------
    # Slice 21 — send_daily_summary
    # ------------------------------------------------------------------

    async def send_daily_summary(self) -> None:
        """Send a daily digest: scanned / matched / applied / replied counts."""
        today_start = datetime.combine(date.today(), _time.min)

        with get_session() as session:
            scanned = (
                session.query(Job)
                .filter(Job.scraped_at >= today_start)
                .count()
            )
            matched = (
                session.query(Job)
                .filter(
                    Job.scraped_at >= today_start,
                    Job.status == JobStatus.MATCHED,
                )
                .count()
            )
            applied = (
                session.query(Application)
                .filter(
                    Application.created_at >= today_start,
                    Application.status == ApplicationStatus.SUBMITTED,
                )
                .count()
            )
            replied = (
                session.query(Application)
                .filter(
                    Application.created_at >= today_start,
                    Application.status == ApplicationStatus.REPLIED,
                )
                .count()
            )

        text = (
            f"<b>Résumé du jour — {date.today().isoformat()}</b>\n\n"
            f"Offres scannées : {scanned}\n"
            f"Matchées (≥ seuil) : {matched}\n"
            f"Candidatures soumises : {applied}\n"
            f"Réponses reçues : {replied}"
        )
        await self._send_message(text)
