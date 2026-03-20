"""Telegram bot for real-time notifications and human validation prompts."""

from src.storage.models import Application, Job


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
        raise NotImplementedError

    async def notify_new_match(self, job: Job) -> None:
        """Send a match notification card for a new offer.

        Includes: title, company, score, salary, remote status, URL.
        """
        raise NotImplementedError

    async def request_approval(self, job: Job, application: Application) -> bool:
        """Send CV + cover letter preview and wait for human approval.

        Blocks until the user replies with /approve or /reject (or times out).

        Args:
            job: The job being applied to.
            application: Draft application with cv_path and cover_letter.

        Returns:
            True if the user approved, False otherwise.
        """
        raise NotImplementedError

    async def notify_reply_received(self, job: Job, sender: str, snippet: str) -> None:
        """Notify that a recruiter has replied to an application.

        Args:
            job: The original job applied to.
            sender: Recruiter email or name.
            snippet: First 200 chars of the email body.
        """
        raise NotImplementedError

    async def send_daily_summary(self) -> None:
        """Send a daily digest: scanned / matched / applied / replied counts."""
        raise NotImplementedError
