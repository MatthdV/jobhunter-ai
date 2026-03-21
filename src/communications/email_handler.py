"""Gmail API wrapper — send applications, read recruiter replies."""

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from src.config.settings import ConfigurationError, settings

logger = logging.getLogger(__name__)


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
        if not settings.is_gmail_configured:
            raise ConfigurationError(
                "Gmail credentials are not configured — set GMAIL_CLIENT_ID, "
                "GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in .env"
            )
        self._user = settings.gmail_user_email or "me"
        self._service: Any = self._build_service()

    def _build_service(self) -> Any:
        """Build and return an authenticated Gmail API service object."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=["https://mail.google.com/"],
        )
        # Refresh to obtain a valid access token
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ------------------------------------------------------------------
    # Slice 29 — send
    # ------------------------------------------------------------------

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[str] | None = None,
        reply_to_thread: str | None = None,
    ) -> str:
        """Send an email and return the Gmail thread ID."""
        mime_msg = MIMEMultipart()
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        mime_msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachments:
            for file_path in attachments:
                path = Path(file_path)
                with open(path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=path.name)
                part["Content-Disposition"] = f'attachment; filename="{path.name}"'
                mime_msg.attach(part)

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        send_body: dict[str, Any] = {"raw": raw}
        if reply_to_thread:
            send_body["threadId"] = reply_to_thread

        def _do_send() -> dict[str, Any]:
            return (
                self._service.users()
                .messages()
                .send(userId="me", body=send_body)
                .execute()
            )

        result: dict[str, Any] = await asyncio.to_thread(_do_send)
        return result["threadId"]

    # ------------------------------------------------------------------
    # Slice 30 — get_unread_replies + mark_as_read
    # ------------------------------------------------------------------

    async def get_unread_replies(self, thread_ids: list[str]) -> list[EmailMessage]:
        """Fetch unread messages in the given threads."""
        if not thread_ids:
            return []

        messages: list[EmailMessage] = []

        def _fetch_thread(thread_id: str) -> dict[str, Any]:
            return (
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id)
                .execute()
            )

        for thread_id in thread_ids:
            thread: dict[str, Any] = await asyncio.to_thread(_fetch_thread, thread_id)
            for raw_msg in thread.get("messages", []):
                label_ids: list[str] = raw_msg.get("labelIds", [])
                if "UNREAD" not in label_ids:
                    continue
                payload = raw_msg.get("payload", {})
                headers = {
                    h["name"]: h["value"]
                    for h in payload.get("headers", [])
                }
                body_data = payload.get("body", {}).get("data", "")
                body_text = (
                    base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                    if body_data
                    else ""
                )
                date_str = headers.get("Date", "")
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except Exception:
                    received_at = datetime.now(tz=timezone.utc)

                messages.append(
                    EmailMessage(
                        thread_id=thread_id,
                        message_id=raw_msg["id"],
                        sender=headers.get("From", ""),
                        subject=headers.get("Subject", ""),
                        body=body_text,
                        received_at=received_at,
                    )
                )

        return messages

    async def mark_as_read(self, message_id: str) -> None:
        """Remove the UNREAD label from a message."""
        def _modify() -> None:
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

        await asyncio.to_thread(_modify)
