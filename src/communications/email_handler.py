"""Gmail API wrapper — send applications, read recruiter replies."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class EmailMessage:
    thread_id: str
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime


class EmailHandler:
    """Send and receive emails via the Gmail API.

    Authentication uses OAuth2 with offline access (refresh token stored
    in .env). Never stores credentials in code.

    Usage::

        handler = EmailHandler()
        thread_id = await handler.send(
            to="recruiter@company.com",
            subject="Application — Automation Engineer",
            body=cover_letter_text,
            attachments=[cv_path],
        )
    """

    def __init__(self) -> None:
        """Build Gmail API client from credentials in Settings."""
        raise NotImplementedError

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list | None = None,
        reply_to_thread: str | None = None,
    ) -> str:
        """Send an email and return the Gmail thread ID.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Plain text or HTML body.
            attachments: Optional list of file paths to attach.
            reply_to_thread: If set, send as a reply in this thread.

        Returns:
            Gmail thread ID for tracking replies.
        """
        raise NotImplementedError

    async def get_unread_replies(self, thread_ids: list[str]) -> list[EmailMessage]:
        """Fetch unread messages in the given threads.

        Args:
            thread_ids: List of Gmail thread IDs to check.

        Returns:
            List of new EmailMessage objects.
        """
        raise NotImplementedError

    async def mark_as_read(self, message_id: str) -> None:
        """Remove the UNREAD label from a message."""
        raise NotImplementedError

    def _build_service(self) -> object:
        """Build and return an authenticated Gmail API service object.

        Returns a `googleapiclient.discovery.Resource` instance.
        Typed as `object` here to avoid a hard dependency on the google
        client library at import time; cast at the call site.
        """
        raise NotImplementedError
